"""Inspeção read-only de código apenas após autorização explícita."""

from __future__ import annotations

from dataclasses import dataclass

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.context_service import ContextService
from devmate.domain.models import ContextChunk
from devmate.errors import UnsafePathError


@dataclass(frozen=True, slots=True)
class InspectionContext:
    commit_hash: str
    chunks: tuple[ContextChunk, ...]


class InspectionService:
    def __init__(
        self, filesystem: LocalFilesystem, context: ContextService, store: RepositoryStore
    ) -> None:
        self.filesystem = filesystem
        self.context = context
        self.store = store

    def build(
        self, project_id: int, commit_ref: str | None, files: list[str], full_repo: bool = False
    ) -> InspectionContext:
        commit, docs = self.context.documentation_chunks(project_id, commit_ref)
        selected = files or ([] if not full_repo else self._source_files())
        if not selected:
            raise UnsafePathError(
                "Informe --files ou use --full-repo para autorizar o escopo de código."
            )
        if len(selected) > 200:
            raise UnsafePathError("A seleção de código excede o limite de 200 arquivos do MVP.")
        code: list[tuple[str, str]] = []
        for requested in selected:
            path = self.filesystem.resolve(requested)
            if not path.is_file() or self.filesystem.is_sensitive(path):
                raise UnsafePathError("O arquivo selecionado não pode ser usado na inspeção.")
            relative = path.relative_to(self.filesystem.root).as_posix()
            content = self.context.git.file_at_commit(commit.commit_hash, relative)
            code.append((relative, content))
        return InspectionContext(
            commit.commit_hash, docs + self.context.code_chunks(commit.commit_hash, code)
        )

    def _source_files(self) -> list[str]:
        results: list[str] = []
        for path in self.filesystem.root.rglob("*"):
            if not path.is_file() or ".git" in path.parts or ".devmate" in path.parts:
                continue
            if path.suffix.lower() not in {
                ".py",
                ".js",
                ".ts",
                ".tsx",
                ".go",
                ".java",
                ".rs",
                ".rb",
            }:
                continue
            if self.filesystem.is_sensitive(path):
                continue
            results.append(path.relative_to(self.filesystem.root).as_posix())
        return results
