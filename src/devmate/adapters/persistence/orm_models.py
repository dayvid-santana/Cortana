"""Modelos ORM privados à camada de persistência."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProjectORM(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    root_path: Mapped[str] = mapped_column(String(2048), unique=True)
    git_common_dir: Mapped[str] = mapped_column(String(2048))
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    commits: Mapped[list[CommitORM]] = relationship(back_populates="project")


class CommitORM(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("project_id", "commit_hash", name="uq_project_commit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    commit_hash: Mapped[str] = mapped_column(String(64))
    short_hash: Mapped[str] = mapped_column(String(16))
    parent_hashes: Mapped[str] = mapped_column(Text, default="")
    first_parent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255))
    author_email: Mapped[str] = mapped_column(String(320))
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    tree_hash: Mapped[str] = mapped_column(String(64))
    is_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    analysis_status: Mapped[str] = mapped_column(String(32), default="metadata")
    project: Mapped[ProjectORM] = relationship(back_populates="commits")
    changes: Mapped[list[DocumentChangeORM]] = relationship(
        back_populates="commit", cascade="all, delete-orphan"
    )


class DocumentChangeORM(Base):
    __tablename__ = "document_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    old_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    new_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    extension: Mapped[str] = mapped_column(String(8))
    old_blob_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_blob_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    additions: Mapped[int] = mapped_column(Integer)
    deletions: Mapped[int] = mapped_column(Integer)
    diff_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commit: Mapped[CommitORM] = relationship(back_populates="changes")


class CommitAnalysisORM(Base):
    __tablename__ = "commit_analyses"
    __table_args__ = (
        UniqueConstraint(
            "commit_id",
            "provider_name",
            "model_name",
            "prompt_version",
            "analysis_version",
            name="uq_commit_analysis_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), index=True)
    provider_name: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(255), default="")
    prompt_version: Mapped[str] = mapped_column(String(100))
    analysis_version: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    raw_structured_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectFactORM(Base):
    __tablename__ = "project_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    confidence: Mapped[float] = mapped_column(default=0.5)
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_heading: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_start_line: Mapped[int | None] = mapped_column(nullable=True)
    source_end_line: Mapped[int | None] = mapped_column(nullable=True)
    introduced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DecisionORM(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    confidence: Mapped[float] = mapped_column(default=0.5)
    explicitness: Mapped[str] = mapped_column(String(32), default="inferred")
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_heading: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_start_line: Mapped[int | None] = mapped_column(nullable=True)
    source_end_line: Mapped[int | None] = mapped_column(nullable=True)
    supersedes_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpenQuestionORM(Base):
    __tablename__ = "open_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_heading: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_start_line: Mapped[int | None] = mapped_column(nullable=True)
    source_end_line: Mapped[int | None] = mapped_column(nullable=True)
    resolved_by_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationMessageORM(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    commit_hash: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationThreadORM(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    commit_hash: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebConversationMessageORM(Base):
    __tablename__ = "web_conversation_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="complete")
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReadingCheckpointORM(Base):
    __tablename__ = "reading_checkpoints"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_checkpoint_project_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    path: Mapped[str] = mapped_column(String(2048))
    content_hash: Mapped[str] = mapped_column(String(64))
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
