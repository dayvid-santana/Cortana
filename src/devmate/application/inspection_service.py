"""Inspeção read-only de código apenas após autorização explícita."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from devmate.adapters.filesystem.local_filesystem import LocalFilesystem
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.context_service import ContextService
from devmate.application.working_tree_cache import WorkingTreeCache
from devmate.constants import SOURCE_FILE_EXTENSIONS, is_excluded_directory
from devmate.domain.models import ContextChunk
from devmate.errors import GitCommandError, UnsafePathError


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
        self,
        filesystem: LocalFilesystem,
        context: ContextService,
        store: RepositoryStore,
        working_tree: WorkingTreeCache | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.context = context
        self.store = store
        # Presente só quando o backend está observando o filesystem (`devmate serve`).
        # Ausente no CLI de um único comando, que sempre lê do commit — não há como
        # "observar em tempo real" um processo que já vai terminar.
        self.working_tree = working_tree

    def build(
        self,
        project_id: int,
        commit_ref: str | None,
        files: list[str],
        full_repo: bool = False,
        live: bool = False,
    ) -> InspectionContext:
        commit, docs = self.context.documentation_chunks(project_id, commit_ref)
        selected = files or ([] if not full_repo else self._source_files())
        if not selected:
            raise UnsafePathError(
                "Informe --files ou use --full-repo para autorizar o escopo de código."
            )
        if len(selected) > 200:
            raise UnsafePathError("A seleção de código excede o limite de 200 arquivos do MVP.")
        working_tree = self.working_tree if live else None
        code: list[tuple[str, str]] = []
        for requested in selected:
            path = self.filesystem.resolve(requested)
            if not path.is_file() or self.filesystem.is_sensitive(path):
                raise UnsafePathError("O arquivo selecionado não pode ser usado na inspeção.")
            relative = path.relative_to(self.filesystem.root).as_posix()
            content = (
                working_tree.get(relative)
                if working_tree is not None
                else self._content_at_commit_or_disk(commit.commit_hash, relative)
            )
            code.append((relative, content))
        return InspectionContext(
            commit.commit_hash,
            docs + self.context.code_chunks(commit.commit_hash, code),
            code_files=tuple(code),
        )

    def _content_at_commit_or_disk(self, commit_hash: str, relative: str) -> str:
        """`_source_files()` seleciona pelo que existe no disco agora; um arquivo
        criado depois do commit selecionado (ainda não commitado) existe no disco mas
        não em `git show <commit>:...`. Sem isto, essa combinação — bem comum enquanto
        se programa — derrubava a pergunta inteira com um erro de git cru, mesmo fora
        do modo `live`. Cai pro conteúdo do disco só para esse arquivo específico."""
        try:
            return self.context.git.file_at_commit(commit_hash, relative)
        except GitCommandError:
            _path, content, _hash = self.filesystem.read_text(relative)
            return content

    def _source_files(self) -> list[str]:
        results: list[str] = []
        for current_root, directory_names, file_names in os.walk(self.filesystem.root):
            # Poda em memória: evita descer para dentro de .venv/node_modules/etc.,
            # o que também torna a varredura rápida em vez de só filtrar o resultado.
            directory_names[:] = [
                name for name in directory_names if not is_excluded_directory(name)
            ]
            for file_name in file_names:
                path = Path(current_root) / file_name
                if path.suffix.lower() not in SOURCE_FILE_EXTENSIONS:
                    continue
                if self.filesystem.is_sensitive(path):
                    continue
                results.append(path.relative_to(self.filesystem.root).as_posix())
        return results
