"""add module context columns to chat_sessions

Revision ID: 211adeedd70f
Revises: 961df38f299a
Create Date: 2026-04-29 19:25:39.650098

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '211adeedd70f'
down_revision: str | None = '961df38f299a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('current_module_id', sa.String(length=128), nullable=True))
    op.add_column('chat_sessions', sa.Column('current_step_id', sa.String(length=128), nullable=True))
    op.add_column(
        'chat_sessions',
        sa.Column('module_context_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column('chat_sessions', sa.Column('context_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'context_updated_at')
    op.drop_column('chat_sessions', 'module_context_data')
    op.drop_column('chat_sessions', 'current_step_id')
    op.drop_column('chat_sessions', 'current_module_id')
