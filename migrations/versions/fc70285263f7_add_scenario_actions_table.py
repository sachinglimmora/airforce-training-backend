"""add scenario_actions table

Revision ID: fc70285263f7
Revises: 2b5785d05c7d
Create Date: 2026-05-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fc70285263f7"
down_revision: str | None = "2b5785d05c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["scenario_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scenario_actions_session_id", "scenario_actions", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_scenario_actions_session_id", table_name="scenario_actions")
    op.drop_table("scenario_actions")
