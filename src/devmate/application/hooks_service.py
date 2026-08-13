"""Instalação de hook Git local sem chamadas de rede."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from devmate.errors import ConfigurationError

HOOK_MARKER = "# DevMate managed post-commit hook"
HOOK_CONTENT = """#!/bin/sh
# DevMate managed post-commit hook
# Apenas indexa metadados locais; nunca chama providers de rede.
devmate scan --quiet --metadata-only
"""


def hook_path(git_common_dir: Path) -> Path:
    return git_common_dir / "hooks" / "post-commit"


def install_hook(git_common_dir: Path) -> Path:
    path = hook_path(git_common_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and HOOK_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        raise ConfigurationError(f"Hook existente não gerenciado pelo DevMate: {path}")
    path.write_text(HOOK_CONTENT, encoding="utf-8")
    with suppress(OSError):
        path.chmod(path.stat().st_mode | 0o111)
    return path


def uninstall_hook(git_common_dir: Path) -> bool:
    path = hook_path(git_common_dir)
    if not path.exists():
        return False
    if HOOK_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        raise ConfigurationError(f"Hook existente não gerenciado pelo DevMate: {path}")
    path.unlink()
    return True


def hook_installed(git_common_dir: Path) -> bool:
    path = hook_path(git_common_dir)
    return path.exists() and HOOK_MARKER in path.read_text(encoding="utf-8", errors="replace")
