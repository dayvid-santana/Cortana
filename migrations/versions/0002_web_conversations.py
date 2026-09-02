"""Persist web conversation threads and messages.

Revision ID: 0002_web_conversations
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_web_conversations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "conversation_threads" not in tables:
        op.create_table(
            "conversation_threads",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("commit_hash", sa.String(length=64), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_conversation_threads_project_id", "conversation_threads", ["project_id"]
        )
        op.create_index(
            "ix_conversation_threads_commit_hash", "conversation_threads", ["commit_hash"]
        )
    if "web_conversation_messages" not in tables:
        op.create_table(
            "web_conversation_messages",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "thread_id",
                sa.String(length=64),
                sa.ForeignKey("conversation_threads.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("provider_name", sa.String(length=100)),
            sa.Column("model_name", sa.String(length=255)),
            sa.Column("sources_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_web_conversation_messages_thread_id", "web_conversation_messages", ["thread_id"]
        )


def downgrade() -> None:
    op.drop_table("web_conversation_messages")
    op.drop_table("conversation_threads")
