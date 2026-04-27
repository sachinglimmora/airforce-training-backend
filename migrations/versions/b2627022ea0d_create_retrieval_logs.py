"""create_retrieval_logs

Revision ID: b2627022ea0d
Revises: e5e83a383a46
Create Date: 2026-04-27 16:58:26.890771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2627022ea0d'
down_revision: Union[str, None] = 'e5e83a383a46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE retrieval_logs (
            id UUID PRIMARY KEY,
            request_id VARCHAR(36) NULL,
            session_id UUID NULL REFERENCES chat_sessions(id),
            user_id UUID NULL,
            original_query TEXT NOT NULL,
            rewritten_query TEXT NULL,
            query_skipped_rewrite BOOLEAN NOT NULL DEFAULT FALSE,
            aircraft_scope_id UUID NULL,
            top_k INTEGER NOT NULL,
            hits JSONB NOT NULL,
            grounded VARCHAR(16) NOT NULL,
            latency_ms JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_retrieval_logs_request_id", "retrieval_logs", ["request_id"])
    op.create_index("ix_retrieval_logs_session_id", "retrieval_logs", ["session_id"])
    op.create_index("ix_retrieval_logs_created_at", "retrieval_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_logs_created_at", table_name="retrieval_logs")
    op.drop_index("ix_retrieval_logs_session_id", table_name="retrieval_logs")
    op.drop_index("ix_retrieval_logs_request_id", table_name="retrieval_logs")
    op.execute("DROP TABLE retrieval_logs")
