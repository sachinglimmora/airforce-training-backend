"""add_blocked_to_grounded_state

Revision ID: 64edd87f8670
Revises: 65a9579c60af
Create Date: 2026-04-29 18:13:59.333595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64edd87f8670'
down_revision: Union[str, None] = '65a9579c60af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE grounded_state ADD VALUE IF NOT EXISTS 'blocked'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums prior to v16; this is intentionally a no-op.
    # If you need to roll back, drop and recreate the enum on a new chat_messages migration.
    pass
