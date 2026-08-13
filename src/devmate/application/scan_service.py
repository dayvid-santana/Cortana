"""Varredura local e idempotente de commits e documentos."""

from __future__ import annotations

from dataclasses import dataclass

from devmate.adapters.git.subprocess_git import SubprocessGit
from devmate.adapters.persistence.repositories import RepositoryStore
from devmate.application.memory_service import MemoryService


@dataclass(frozen=True, slots=True)
class ScanResult:
    commits_seen: int
    commits_created: int
    documents_changed: int


class ScanService:
    def __init__(
        self, git: SubprocessGit, store: RepositoryStore, memory: MemoryService, max_diff_chars: int
    ) -> None:
        self.git = git
        self.store = store
        self.memory = memory
        self.max_diff_chars = max_diff_chars

    def scan(
        self, project_id: int, revision: str = "HEAD", first_parent: bool = False
    ) -> ScanResult:
        records = self.git.commits(revision, first_parent=first_parent)
        created = 0
        documents = 0
        for record in records:
            changes = self.git.markdown_changes(record, self.max_diff_chars)
            documents += len(changes)
            if self.store.upsert_commit(project_id, record, changes):
                created += 1
                self.memory.extract(project_id, record.commit_hash, changes)
        return ScanResult(len(records), created, documents)
