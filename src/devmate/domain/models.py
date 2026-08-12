"""Modelos imutáveis do domínio."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from devmate.domain.enums import ChangeStatus, Scope


@dataclass(frozen=True, slots=True)
class SourceReference:
    path: str
    start_line: int
    end_line: int
    commit_hash: str
    heading: str | None = None

    def render(self) -> str:
        suffix = f" ({self.heading})" if self.heading else ""
        return f"[{self.path}:L{self.start_line}-L{self.end_line}@{self.commit_hash[:7]}]{suffix}"


@dataclass(frozen=True, slots=True)
class Project:
    id: int | None
    name: str
    root_path: Path
    git_common_dir: Path
    default_branch: str | None


@dataclass(frozen=True, slots=True)
class CommitRecord:
    commit_hash: str
    short_hash: str
    parent_hashes: tuple[str, ...]
    branch_name: str | None
    author_name: str
    author_email: str
    authored_at: datetime
    committed_at: datetime
    subject: str
    body: str
    tree_hash: str

    @property
    def first_parent_hash(self) -> str | None:
        return self.parent_hashes[0] if self.parent_hashes else None


@dataclass(frozen=True, slots=True)
class DocumentChange:
    status: ChangeStatus
    old_path: str | None
    new_path: str | None
    extension: str
    additions: int
    deletions: int
    diff_text: str
    old_blob_hash: str | None = None
    new_blob_hash: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ContextChunk:
    text: str
    reference: SourceReference
    trusted: bool = False


@dataclass(frozen=True, slots=True)
class LLMRequest:
    task: str
    question: str
    scope: Scope
    chunks: tuple[ContextChunk, ...]
    system_instructions: str
    model: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    references: tuple[SourceReference, ...] = field(default_factory=tuple)
    raw: str | None = None


@dataclass(frozen=True, slots=True)
class NarrationSegment:
    ordinal: int
    text: str
    start_line: int
    end_line: int
    heading: str | None = None
