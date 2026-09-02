"""Repositórios que convertem entre entidades de domínio e ORM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session, sessionmaker

from devmate.adapters.persistence.orm_models import (
    CommitORM,
    ConversationMessageORM,
    ConversationThreadORM,
    DecisionORM,
    DocumentChangeORM,
    OpenQuestionORM,
    ProjectORM,
    ReadingCheckpointORM,
    WebConversationMessageORM,
)
from devmate.domain.models import CommitRecord, DocumentChange, Project


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StoredChange:
    id: int
    status: str
    old_path: str | None
    new_path: str | None
    additions: int
    deletions: int
    diff_text: str


@dataclass(frozen=True, slots=True)
class StoredCommit:
    id: int
    commit_hash: str
    short_hash: str
    subject: str
    branch_name: str | None
    committed_at: datetime
    parent_hashes: tuple[str, ...]
    changes: tuple[StoredChange, ...]


@dataclass(frozen=True, slots=True)
class DecisionView:
    id: int
    title: str
    description: str
    status: str
    explicitness: str
    source_path: str | None
    source_start_line: int | None
    source_end_line: int | None
    source_commit: str | None


@dataclass(frozen=True, slots=True)
class QuestionView:
    id: int
    question: str
    status: str
    source_path: str | None
    source_start_line: int | None
    source_end_line: int | None
    source_commit: str | None


@dataclass(frozen=True, slots=True)
class ThreadView:
    id: str
    project_id: int
    commit_hash: str
    scope: str
    created_at: datetime
    updated_at: datetime
    message_count: int


@dataclass(frozen=True, slots=True)
class WebMessageView:
    id: str
    thread_id: str
    role: str
    content: str
    scope: str
    status: str
    provider_name: str | None
    model_name: str | None
    sources_json: str
    created_at: datetime


class RepositoryStore:
    """Persistência de projeto isolada por sessão curta."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def ensure_project(self, project: Project) -> int:
        now = utcnow()
        with self._factory.begin() as session:
            current = session.scalar(
                select(ProjectORM).where(ProjectORM.root_path == str(project.root_path))
            )
            if current is None:
                current = ProjectORM(
                    name=project.name,
                    root_path=str(project.root_path),
                    git_common_dir=str(project.git_common_dir),
                    default_branch=project.default_branch,
                    created_at=now,
                    updated_at=now,
                )
                session.add(current)
                session.flush()
            else:
                current.name = project.name
                current.git_common_dir = str(project.git_common_dir)
                current.default_branch = project.default_branch
                current.updated_at = now
            return current.id

    def project_id(self, root: Path) -> int | None:
        with self._factory() as session:
            project = session.scalar(
                select(ProjectORM).where(ProjectORM.root_path == str(root.resolve()))
            )
            return project.id if project else None

    def upsert_commit(
        self, project_id: int, record: CommitRecord, changes: list[DocumentChange]
    ) -> bool:
        with self._factory.begin() as session:
            stored = session.scalar(
                select(CommitORM).where(
                    CommitORM.project_id == project_id, CommitORM.commit_hash == record.commit_hash
                )
            )
            created = stored is None
            if stored is None:
                stored = CommitORM(
                    project_id=project_id,
                    commit_hash=record.commit_hash,
                    short_hash=record.short_hash,
                    parent_hashes=" ".join(record.parent_hashes),
                    first_parent_hash=record.first_parent_hash,
                    branch_name=record.branch_name,
                    author_name=record.author_name,
                    author_email=record.author_email,
                    authored_at=record.authored_at,
                    committed_at=record.committed_at,
                    subject=record.subject,
                    body=record.body,
                    tree_hash=record.tree_hash,
                    is_merge=len(record.parent_hashes) > 1,
                    scanned_at=utcnow(),
                    analysis_status="metadata",
                )
                session.add(stored)
                session.flush()
                for change in changes:
                    session.add(
                        DocumentChangeORM(
                            commit_id=stored.id,
                            status=change.status.value,
                            old_path=change.old_path,
                            new_path=change.new_path,
                            extension=change.extension,
                            old_blob_hash=change.old_blob_hash,
                            new_blob_hash=change.new_blob_hash,
                            additions=change.additions,
                            deletions=change.deletions,
                            diff_text=change.diff_text,
                            content_hash=change.content_hash,
                        )
                    )
            return created

    def latest_commit(self, project_id: int) -> StoredCommit | None:
        with self._factory() as session:
            item = session.scalar(
                select(CommitORM)
                .where(CommitORM.project_id == project_id)
                .order_by(desc(CommitORM.id))
            )
            return self._commit_view(item) if item else None

    def commit(self, project_id: int, commit_hash: str) -> StoredCommit | None:
        with self._factory() as session:
            item = session.scalar(
                select(CommitORM).where(
                    CommitORM.project_id == project_id,
                    CommitORM.commit_hash.startswith(commit_hash),
                )
            )
            return self._commit_view(item) if item else None

    def commits(self, project_id: int) -> list[StoredCommit]:
        with self._factory() as session:
            items = session.scalars(
                select(CommitORM).where(CommitORM.project_id == project_id).order_by(CommitORM.id)
            ).all()
            return [self._commit_view(item) for item in items]

    @staticmethod
    def _commit_view(item: CommitORM) -> StoredCommit:
        return StoredCommit(
            id=item.id,
            commit_hash=item.commit_hash,
            short_hash=item.short_hash,
            subject=item.subject,
            branch_name=item.branch_name,
            committed_at=item.committed_at,
            parent_hashes=tuple(filter(None, item.parent_hashes.split(" "))),
            changes=tuple(
                StoredChange(
                    id=change.id,
                    status=change.status,
                    old_path=change.old_path,
                    new_path=change.new_path,
                    additions=change.additions,
                    deletions=change.deletions,
                    diff_text=change.diff_text,
                )
                for change in item.changes
            ),
        )

    def add_message(
        self,
        project_id: int,
        commit_hash: str,
        role: str,
        content: str,
        provider_name: str | None = None,
    ) -> None:
        with self._factory.begin() as session:
            session.add(
                ConversationMessageORM(
                    project_id=project_id,
                    commit_hash=commit_hash,
                    role=role,
                    content=content,
                    provider_name=provider_name,
                    created_at=utcnow(),
                )
            )

    def conversation(
        self, project_id: int, commit_hash: str, limit: int = 12
    ) -> list[tuple[str, str]]:
        with self._factory() as session:
            statements: Select[tuple[ConversationMessageORM]] = (
                select(ConversationMessageORM)
                .where(
                    ConversationMessageORM.project_id == project_id,
                    ConversationMessageORM.commit_hash == commit_hash,
                )
                .order_by(desc(ConversationMessageORM.created_at))
                .limit(limit)
            )
            return [
                (item.role, item.content) for item in reversed(session.scalars(statements).all())
            ]

    def create_thread(
        self, thread_id: str, project_id: int, commit_hash: str, scope: str
    ) -> ThreadView:
        now = utcnow()
        with self._factory.begin() as session:
            item = ConversationThreadORM(
                id=thread_id,
                project_id=project_id,
                commit_hash=commit_hash,
                scope=scope,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
        return ThreadView(thread_id, project_id, commit_hash, scope, now, now, 0)

    def thread(self, project_id: int, thread_id: str) -> ThreadView | None:
        with self._factory() as session:
            item = session.scalar(
                select(ConversationThreadORM).where(
                    ConversationThreadORM.id == thread_id,
                    ConversationThreadORM.project_id == project_id,
                )
            )
            return self._thread_view(session, item) if item else None

    def threads(self, project_id: int, commit_hash: str | None = None) -> list[ThreadView]:
        with self._factory() as session:
            statement = select(ConversationThreadORM).where(
                ConversationThreadORM.project_id == project_id
            )
            if commit_hash:
                statement = statement.where(ConversationThreadORM.commit_hash == commit_hash)
            return [
                self._thread_view(session, item)
                for item in session.scalars(
                    statement.order_by(desc(ConversationThreadORM.updated_at))
                ).all()
            ]

    @staticmethod
    def _thread_view(session: Session, item: ConversationThreadORM) -> ThreadView:
        count = (
            session.query(WebConversationMessageORM)
            .filter(WebConversationMessageORM.thread_id == item.id)
            .count()
        )
        return ThreadView(
            item.id,
            item.project_id,
            item.commit_hash,
            item.scope,
            item.created_at,
            item.updated_at,
            count,
        )

    def add_web_message(
        self,
        message_id: str,
        thread_id: str,
        role: str,
        content: str,
        scope: str,
        status: str,
        provider_name: str | None,
        model_name: str | None,
        sources_json: str = "[]",
    ) -> WebMessageView:
        now = utcnow()
        with self._factory.begin() as session:
            session.add(
                WebConversationMessageORM(
                    id=message_id,
                    thread_id=thread_id,
                    role=role,
                    content=content,
                    scope=scope,
                    status=status,
                    provider_name=provider_name,
                    model_name=model_name,
                    sources_json=sources_json,
                    created_at=now,
                )
            )
            thread = session.get(ConversationThreadORM, thread_id)
            if thread:
                thread.updated_at = now
        return WebMessageView(
            message_id,
            thread_id,
            role,
            content,
            scope,
            status,
            provider_name,
            model_name,
            sources_json,
            now,
        )

    def web_messages(
        self, project_id: int, thread_id: str, limit: int = 30
    ) -> list[WebMessageView]:
        with self._factory() as session:
            exists = session.scalar(
                select(ConversationThreadORM.id).where(
                    ConversationThreadORM.id == thread_id,
                    ConversationThreadORM.project_id == project_id,
                )
            )
            if not exists:
                return []
            return [
                WebMessageView(
                    item.id,
                    item.thread_id,
                    item.role,
                    item.content,
                    item.scope,
                    item.status,
                    item.provider_name,
                    item.model_name,
                    item.sources_json,
                    item.created_at,
                )
                for item in session.scalars(
                    select(WebConversationMessageORM)
                    .where(WebConversationMessageORM.thread_id == thread_id)
                    .order_by(WebConversationMessageORM.created_at)
                    .limit(limit)
                ).all()
            ]

    def add_decision(
        self,
        project_id: int,
        title: str,
        description: str,
        source_commit: str,
        source_path: str,
        start_line: int,
        end_line: int,
        explicitness: str = "inferred",
    ) -> None:
        with self._factory.begin() as session:
            duplicate = session.scalar(
                select(DecisionORM).where(
                    DecisionORM.project_id == project_id,
                    DecisionORM.title == title,
                    DecisionORM.source_commit == source_commit,
                )
            )
            if duplicate is None:
                session.add(
                    DecisionORM(
                        project_id=project_id,
                        title=title,
                        description=description,
                        status="candidate" if explicitness == "inferred" else "active",
                        confidence=0.7,
                        explicitness=explicitness,
                        source_commit=source_commit,
                        source_path=source_path,
                        source_heading=None,
                        source_start_line=start_line,
                        source_end_line=end_line,
                        supersedes_decision_id=None,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                )

    def add_question(
        self, project_id: int, question: str, source_commit: str, source_path: str, line: int
    ) -> None:
        with self._factory.begin() as session:
            duplicate = session.scalar(
                select(OpenQuestionORM).where(
                    OpenQuestionORM.project_id == project_id,
                    OpenQuestionORM.question == question,
                    OpenQuestionORM.source_commit == source_commit,
                )
            )
            if duplicate is None:
                session.add(
                    OpenQuestionORM(
                        project_id=project_id,
                        question=question,
                        status="open",
                        source_commit=source_commit,
                        source_path=source_path,
                        source_heading=None,
                        source_start_line=line,
                        source_end_line=line,
                        resolved_by_commit=None,
                        resolution=None,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                )

    def decisions(self, project_id: int, active_only: bool = False) -> list[DecisionView]:
        with self._factory() as session:
            statement = select(DecisionORM).where(DecisionORM.project_id == project_id)
            if active_only:
                statement = statement.where(DecisionORM.status == "active")
            items = session.scalars(statement.order_by(DecisionORM.updated_at.desc())).all()
            return [
                DecisionView(
                    id=item.id,
                    title=item.title,
                    description=item.description,
                    status=item.status,
                    explicitness=item.explicitness,
                    source_path=item.source_path,
                    source_start_line=item.source_start_line,
                    source_end_line=item.source_end_line,
                    source_commit=item.source_commit,
                )
                for item in items
            ]

    def questions(self, project_id: int, open_only: bool = False) -> list[QuestionView]:
        with self._factory() as session:
            statement = select(OpenQuestionORM).where(OpenQuestionORM.project_id == project_id)
            if open_only:
                statement = statement.where(OpenQuestionORM.status == "open")
            items = session.scalars(statement.order_by(OpenQuestionORM.updated_at.desc())).all()
            return [
                QuestionView(
                    id=item.id,
                    question=item.question,
                    status=item.status,
                    source_path=item.source_path,
                    source_start_line=item.source_start_line,
                    source_end_line=item.source_end_line,
                    source_commit=item.source_commit,
                )
                for item in items
            ]

    def save_checkpoint(
        self, project_id: int, path: str, content_hash: str, segment_index: int
    ) -> None:
        with self._factory.begin() as session:
            checkpoint = session.scalar(
                select(ReadingCheckpointORM).where(
                    ReadingCheckpointORM.project_id == project_id, ReadingCheckpointORM.path == path
                )
            )
            if checkpoint is None:
                session.add(
                    ReadingCheckpointORM(
                        project_id=project_id,
                        path=path,
                        content_hash=content_hash,
                        segment_index=segment_index,
                        updated_at=utcnow(),
                    )
                )
            else:
                checkpoint.content_hash = content_hash
                checkpoint.segment_index = segment_index
                checkpoint.updated_at = utcnow()

    def checkpoint(self, project_id: int, path: str) -> tuple[str, int] | None:
        with self._factory() as session:
            item = session.scalar(
                select(ReadingCheckpointORM).where(
                    ReadingCheckpointORM.project_id == project_id, ReadingCheckpointORM.path == path
                )
            )
            return (item.content_hash, item.segment_index) if item else None
