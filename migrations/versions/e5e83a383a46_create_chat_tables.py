"""create_chat_tables

Revision ID: e5e83a383a46
Revises: 797781e12aa4
Create Date: 2026-04-27 16:56:00.804820

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5e83a383a46'
down_revision: Union[str, None] = '797781e12aa4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE chat_session_status AS ENUM ('active', 'closed')")
    op.execute("CREATE TYPE chat_message_role AS ENUM ('user', 'assistant')")
    op.execute("CREATE TYPE grounded_state AS ENUM ('strong', 'soft', 'refused')")

    op.execute(
        """
        CREATE TABLE chat_sessions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            aircraft_id UUID NULL REFERENCES aircraft(id),
            title VARCHAR(255) NULL,
            status chat_session_status NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at TIMESTAMPTZ NULL
        )
        """
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_last_activity_at", "chat_sessions", ["last_activity_at"])

    op.execute(
        """
        CREATE TABLE chat_messages (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES chat_sessions(id),
            role chat_message_role NOT NULL,
            content TEXT NOT NULL,
            citations JSONB NULL,
            grounded grounded_state NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.execute("DROP TABLE chat_messages")
    op.drop_index("ix_chat_sessions_last_activity_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.execute("DROP TABLE chat_sessions")
    op.execute("DROP TYPE grounded_state")
    op.execute("DROP TYPE chat_message_role")
    op.execute("DROP TYPE chat_session_status")
