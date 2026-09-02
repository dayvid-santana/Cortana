"""Registro persistente dos repositórios locais expostos pela API web."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.application.project_service import initialize_project
from devmate.bootstrap import Runtime, load_runtime
from devmate.errors import RepositoryNotFoundError


def web_project_id(root: Path) -> str:
    """Gera o mesmo ID estável que o frontend usava para caminhos locais."""
    normalized = re.sub(r"[^a-z0-9]+", "-", str(root).lower()).strip("-")
    return f"proj_{normalized}"


@dataclass(frozen=True, slots=True)
class RegisteredProject:
    id: str
    root: Path
    name: str


class ProjectRegistry:
    """Lista explicitamente autorizada de repositórios disponíveis à API local."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.environ.get("DEVMATE_API_PROJECTS_FILE")
        self.path = path or (
            Path(configured) if configured else Path.home() / ".devmate-web" / "projects.json"
        )

    def list(self) -> list[RegisteredProject]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        projects: list[RegisteredProject] = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("root"), str):
                continue
            root = Path(item["root"])
            project_id = web_project_id(root)
            name = item["name"] if isinstance(item.get("name"), str) else root.name
            projects.append(RegisteredProject(project_id, root, name))
        return projects

    def get(self, project_id: str) -> RegisteredProject:
        for project in self.list():
            if project.id == project_id:
                return project
        raise RepositoryNotFoundError("Projeto não encontrado.")

    def register(self, requested_path: str, name: str | None = None) -> RegisteredProject:
        root = SubprocessGit.from_start(Path(requested_path).expanduser()).root
        project = RegisteredProject(web_project_id(root), root, name or root.name)
        existing = {item.id: item for item in self.list()}
        existing[project.id] = project
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"root": str(item.root), "name": item.name}
            for item in sorted(existing.values(), key=lambda item: item.name.casefold())
        ]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        initialize_project(root)
        runtime = load_runtime(root)
        runtime.scan_service().scan(runtime.project_id)
        return project

    def runtime(self, project_id: str) -> tuple[RegisteredProject, Runtime]:
        project = self.get(project_id)
        return project, load_runtime(project.root)
