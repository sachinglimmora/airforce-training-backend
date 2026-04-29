"""add_content_lifecycle_columns

Revision ID: 961df38f299a
Revises: 8ebeeb1ea596
Create Date: 2026-04-29 18:39:35.112230

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '961df38f299a'
down_revision: Union[str, None] = '64edd87f8670'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("content_sources", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_sources", sa.Column("last_reviewed_by", sa.UUID(), nullable=True))
    op.add_column("content_sources", sa.Column("next_review_due", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_sources", sa.Column("deprecation_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        "content_sources_last_reviewed_by_fkey",
        "content_sources", "users",
        ["last_reviewed_by"], ["id"],
    )
    op.create_index("ix_content_sources_next_review_due", "content_sources", ["next_review_due"])
    op.create_index("ix_content_sources_deprecation_date", "content_sources", ["deprecation_date"])


def downgrade() -> None:
    op.drop_index("ix_content_sources_deprecation_date", table_name="content_sources")
    op.drop_index("ix_content_sources_next_review_due", table_name="content_sources")
    op.drop_constraint("content_sources_last_reviewed_by_fkey", "content_sources", type_="foreignkey")
    op.drop_column("content_sources", "deprecation_date")
    op.drop_column("content_sources", "next_review_due")
    op.drop_column("content_sources", "last_reviewed_by")
    op.drop_column("content_sources", "last_reviewed_at")
