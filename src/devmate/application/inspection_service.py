"""Inspeção read-only de código apenas após autorização explícita."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.context_service import ContextService
from devmate.constants import SOURCE_FILE_EXTENSIONS
from devmate.domain.models import ContextChunk
from devmate.errors import UnsafePathError

# Diretórios de dependências, cache e build nunca são código do projeto; incluí-los
# facilmente estoura o limite de 200 arquivos (um .venv sozinho já tem milhares de .py).
_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {"venv", "node_modules", "dist", "build", "__pycache__", "site-packages"}
)


def _is_excluded_directory(name: str) -> bool:
    return name.startswith(".") or name in _EXCLUDED_DIRECTORY_NAMES or name.endswith(".egg-info")


@dataclass(frozen=True, slots=True)
class InspectionContext:
    commit_hash: str
    chunks: tuple[ContextChunk, ...]
    # Pares (caminho relativo, conteúdo no commit) dos arquivos de código explicitamente
    # selecionados — não inclui os documentos trazidos como contexto. É a lista de
    # autorização usada por EditProposalService para aceitar uma proposta de escrita.
    code_files: tuple[tuple[str, str], ...] = ()


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
            commit.commit_hash,
            docs + self.context.code_chunks(commit.commit_hash, code),
            code_files=tuple(code),
        )

    def _source_files(self) -> list[str]:
        results: list[str] = []
        for current_root, directory_names, file_names in os.walk(self.filesystem.root):
            # Poda em memória: evita descer para dentro de .venv/node_modules/etc.,
            # o que também torna a varredura rápida em vez de só filtrar o resultado.
            directory_names[:] = [
                name for name in directory_names if not _is_excluded_directory(name)
            ]
            for file_name in file_names:
                path = Path(current_root) / file_name
                if path.suffix.lower() not in SOURCE_FILE_EXTENSIONS:
                    continue
                if self.filesystem.is_sensitive(path):
                    continue
                results.append(path.relative_to(self.filesystem.root).as_posix())
        return results
