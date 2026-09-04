"""Persist the remote provider's response id, to continue a thread without resending history.

Revision ID: 0003_response_thread_id
Revises: 0002_web_conversations
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_response_thread_id"
down_revision = "0002_web_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("conversation_messages")}
    if "provider_response_id" not in columns:
        op.add_column(
            "conversation_messages",
            sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("conversation_messages", "provider_response_id")
