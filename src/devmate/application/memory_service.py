"""Extração conservadora de candidatas a decisão e perguntas abertas."""

from __future__ import annotations

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.domain.models import DocumentChange
from devmate.markdown.parser import MarkdownParser


class MemoryService:
    def __init__(
        self, git: SubprocessGit, store: RepositoryStore, parser: MarkdownParser | None = None
    ) -> None:
        self.git = git
        self.store = store
        self.parser = parser or MarkdownParser()

    def extract(self, project_id: int, commit_hash: str, changes: list[DocumentChange]) -> None:
        for change in changes:
            path = change.new_path
            if not path:
                continue
            try:
                text = self.git.file_at_commit(commit_hash, path)
            except Exception:
                continue
            for block in self.parser.blocks(text):
                lowered = block.content.casefold()
                if block.kind == "heading" and ("decisão" in lowered or "decision" in lowered):
                    self.store.add_decision(
                        project_id,
                        title=block.content,
                        description=(
                            "Decisão identificada por heading da documentação; "
                            "requer confirmação humana."
                        ),
                        source_commit=commit_hash,
                        source_path=path,
                        start_line=block.start_line,
                        end_line=block.end_line,
                    )
                if "?" in block.content and block.kind in {"paragraph", "list_item"}:
                    self.store.add_question(
                        project_id,
                        question=block.content,
                        source_commit=commit_hash,
                        source_path=path,
                        line=block.start_line,
                    )
