"""add_embedding_status_to_content_sources

Revision ID: 8ebeeb1ea596
Revises: b2627022ea0d
Create Date: 2026-04-27 17:00:11.474764

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8ebeeb1ea596'
down_revision: str | None = 'b2627022ea0d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE embedding_status AS ENUM ('pending', 'succeeded', 'failed')")
    op.add_column(
        "content_sources",
        sa.Column(
            "embedding_status",
            postgresql.ENUM("pending", "succeeded", "failed", name="embedding_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("content_sources", "embedding_status")
    op.execute("DROP TYPE embedding_status")
