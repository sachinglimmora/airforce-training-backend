"""enable_pgvector_extension

Revision ID: 9270e8657838
Revises: 2b5785d05c7d
Create Date: 2026-04-27 16:37:12.969152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9270e8657838'
down_revision: Union[str, None] = '2b5785d05c7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
