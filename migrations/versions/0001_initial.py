"""Initial schema managed by SQLAlchemy bootstrap.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Schema creation is intentionally performed by Base.metadata in MVP bootstrap."""


def downgrade() -> None:
    """No automatic destructive downgrade is provided."""
