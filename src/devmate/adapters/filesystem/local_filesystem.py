"""Leitura de arquivos limitada ao repositório e sem segredos."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

from devmate.errors import FileTooLargeError, UnsafePathError


class LocalFilesystem:
    def __init__(
        self,
        root: Path,
        max_file_bytes: int,
        ignored_patterns: list[str],
        follow_external_symlinks: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.ignored_patterns = ignored_patterns
        self.follow_external_symlinks = follow_external_symlinks

    def resolve(self, requested_path: str) -> Path:
        raw = Path(requested_path)
        candidate = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise UnsafePathError("O caminho solicitado escapa do repositório.") from exc
        if candidate.is_symlink() and not self.follow_external_symlinks:
            resolved = candidate.resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise UnsafePathError("Symlink externo não é permitido.") from exc
        return candidate

    def is_sensitive(self, path: Path) -> bool:
        relative = path.relative_to(self.root).as_posix()
        return any(
            fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(relative, pattern)
            for pattern in self.ignored_patterns
        )

    def read_text(
        self, requested_path: str, allow_sensitive: bool = False
    ) -> tuple[Path, str, str]:
        path = self.resolve(requested_path)
        if not path.is_file():
            raise UnsafePathError("O caminho não é um arquivo regular dentro do repositório.")
        if self.is_sensitive(path) and not allow_sensitive:
            raise UnsafePathError(
                "Arquivos potencialmente sensíveis não podem ser lidos pelo DevMate."
            )
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise FileTooLargeError(f"Arquivo excede o limite de {self.max_file_bytes} bytes.")
        content = path.read_text(encoding="utf-8", errors="replace")
        return path, content, hashlib.sha256(content.encode("utf-8")).hexdigest()

    def write_text(self, requested_path: str, content: str) -> Path:
        """Único ponto de escrita do DevMate: mesmas travas de `resolve`/segredo/tamanho do read."""
        path = self.resolve(requested_path)
        if self.is_sensitive(path):
            raise UnsafePathError(
                "Arquivos potencialmente sensíveis não podem ser escritos pelo DevMate."
            )
        size = len(content.encode("utf-8"))
        if size > self.max_file_bytes:
            raise FileTooLargeError(f"Conteúdo excede o limite de {self.max_file_bytes} bytes.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
