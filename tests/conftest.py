from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True, encoding="utf-8"
    )
    return result.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Dev Mate")
    git(tmp_path, "config", "user.email", "devmate@example.test")
    (tmp_path / "README.md").write_text("# Projeto\n\nDocumento inicial.\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "docs: adiciona README")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "auth.md").write_text(
        "# Autenticação\n\n## Decisão: JWT\n\nA API usa JWT.\n\nQual é a rotação?\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", "docs/auth.md")
    git(tmp_path, "commit", "-m", "docs: descreve autenticação")
    return tmp_path
