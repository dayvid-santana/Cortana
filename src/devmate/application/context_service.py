"""Seleção de contexto mínimo e rastreável para cada pergunta."""

from __future__ import annotations

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.persistence.repositories import RepositoryStore, StoredCommit
from devmate.domain.enums import Scope
from devmate.domain.models import ContextChunk, SourceReference
from devmate.errors import CommitNotFoundError
from devmate.markdown.parser import MarkdownParser


class ContextService:
    def __init__(
        self, git: SubprocessGit, store: RepositoryStore, parser: MarkdownParser | None = None
    ) -> None:
        self.git = git
        self.store = store
        self.parser = parser or MarkdownParser()

    def selected_commit(self, project_id: int, reference: str | None = None) -> StoredCommit:
        selected_hash = reference or self.git.head()
        commit = self.store.commit(project_id, selected_hash)
        if commit is None:
            raise CommitNotFoundError("O commit atual não foi indexado. Execute `devmate scan`.")
        return commit

    def documentation_chunks(
        self, project_id: int, reference: str | None = None
    ) -> tuple[StoredCommit, tuple[ContextChunk, ...]]:
        commit = self.selected_commit(project_id, reference)
        chunks: list[ContextChunk] = []
        for change in commit.changes:
            path = change.new_path
            if path is None:
                continue
            try:
                content = self.git.file_at_commit(commit.commit_hash, path)
            except Exception:
                continue
            blocks = self.parser.blocks(content)
            if not blocks:
                blocks = []
            for block in blocks:
                chunks.append(
                    ContextChunk(
                        text=block.content,
                        reference=SourceReference(
                            path=path,
                            start_line=block.start_line,
                            end_line=block.end_line,
                            commit_hash=commit.commit_hash,
                            heading=block.heading,
                        ),
                    )
                )
        if not chunks:
            for change in commit.changes:
                path = change.new_path or change.old_path
                if path:
                    chunks.append(
                        ContextChunk(
                            text=change.diff_text,
                            reference=SourceReference(path, 1, 1, commit.commit_hash),
                        )
                    )
        return commit, tuple(chunks)

    @staticmethod
    def code_chunks(commit_hash: str, contents: list[tuple[str, str]]) -> tuple[ContextChunk, ...]:
        chunks: list[ContextChunk] = []
        for path, content in contents:
            lines = content.splitlines() or [""]
            chunks.append(
                ContextChunk(
                    text=content,
                    reference=SourceReference(path, 1, len(lines), commit_hash, heading=None),
                )
            )
        return tuple(chunks)

    def build(
        self, project_id: int, scope: Scope, reference: str | None = None
    ) -> tuple[StoredCommit, tuple[ContextChunk, ...]]:
        if scope is not Scope.DOCS:
            raise ValueError(
                "Contexto de código requer seleção explícita pelo serviço de inspeção."
            )
        return self.documentation_chunks(project_id, reference)
