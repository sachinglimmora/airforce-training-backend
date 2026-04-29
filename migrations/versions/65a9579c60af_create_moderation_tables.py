"""create_moderation_tables

Revision ID: 65a9579c60af
Revises: 8ebeeb1ea596
Create Date: 2026-04-29 17:54:47.596568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65a9579c60af'
down_revision: Union[str, None] = '8ebeeb1ea596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    op.execute("CREATE TYPE moderation_category AS ENUM ('classification', 'banned_phrase', 'profanity', 'casual')")
    op.execute("CREATE TYPE moderation_pattern_type AS ENUM ('regex', 'literal')")
    op.execute("CREATE TYPE moderation_action AS ENUM ('block', 'redact', 'log')")
    op.execute("CREATE TYPE moderation_severity AS ENUM ('critical', 'high', 'medium', 'low')")
    op.execute("CREATE TYPE moderation_log_category AS ENUM ('classification', 'banned_phrase', 'ungrounded', 'profanity', 'casual')")
    op.execute("CREATE TYPE moderation_action_taken AS ENUM ('block', 'redact', 'log')")
    op.execute("CREATE TYPE moderation_log_severity AS ENUM ('critical', 'high', 'medium', 'low')")

    # moderation_rules
    op.execute(
        """
        CREATE TABLE moderation_rules (
            id UUID PRIMARY KEY,
            category moderation_category NOT NULL,
            pattern TEXT NOT NULL,
            pattern_type moderation_pattern_type NOT NULL DEFAULT 'regex',
            action moderation_action NOT NULL,
            severity moderation_severity NOT NULL,
            description TEXT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_moderation_rules_category", "moderation_rules", ["category"])
    op.create_index("ix_moderation_rules_active", "moderation_rules", ["active"])
    op.create_index("ix_moderation_rules_category_active", "moderation_rules", ["category", "active"])

    # moderation_logs
    op.execute(
        """
        CREATE TABLE moderation_logs (
            id UUID PRIMARY KEY,
            request_id VARCHAR(36) NULL,
            session_id UUID NULL REFERENCES chat_sessions(id),
            user_id UUID NULL,
            rule_id UUID NULL REFERENCES moderation_rules(id),
            category moderation_log_category NOT NULL,
            matched_text TEXT NOT NULL,
            original_response TEXT NOT NULL,
            action_taken moderation_action_taken NOT NULL,
            severity moderation_log_severity NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_moderation_logs_request_id", "moderation_logs", ["request_id"])
    op.create_index("ix_moderation_logs_session_id", "moderation_logs", ["session_id"])
    op.create_index("ix_moderation_logs_created_at", "moderation_logs", ["created_at"])
    op.create_index("ix_moderation_logs_severity_created_at", "moderation_logs", ["severity", "created_at"])

    # Seed default rules — classification (BLOCK, critical)
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'classification', '\\bSECRET//\\w+', 'regex', 'block', 'critical', 'US classification marker SECRET//', TRUE),
            (gen_random_uuid(), 'classification', '\\bTOP\\s+SECRET\\b', 'regex', 'block', 'critical', 'US classification marker TOP SECRET', TRUE),
            (gen_random_uuid(), 'classification', '\\bTS//SCI\\b', 'regex', 'block', 'critical', 'US classification marker TS//SCI', TRUE),
            (gen_random_uuid(), 'classification', '\\bNOFORN\\b', 'regex', 'block', 'critical', 'US classification dissemination control NOFORN', TRUE),
            (gen_random_uuid(), 'classification', '\\bREL\\s+TO\\s+\\w+', 'regex', 'block', 'critical', 'US classification dissemination control REL TO', TRUE),
            (gen_random_uuid(), 'classification', '\\bCONFIDENTIAL//\\w+', 'regex', 'block', 'critical', 'US classification marker CONFIDENTIAL//', TRUE)
        """
    )

    # Seed default rules — profanity (REDACT, medium) — minimal English list
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'profanity', '\\bdamn\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bhell\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bcrap\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bshit\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bfuck\\w*', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bbitch\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bass\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE)
        """
    )

    # Seed default rules — casual register (LOG, low)
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'casual', '\\b(lol|lmao|haha|hehe)\\b', 'regex', 'log', 'low', 'Casual interjection', TRUE),
            (gen_random_uuid(), 'casual', '\\b(dude|guys)\\b', 'regex', 'log', 'low', 'Informal address', TRUE),
            (gen_random_uuid(), 'casual', '\\b(gonna|wanna|kinda|gotta)\\b', 'regex', 'log', 'low', 'Informal contraction', TRUE)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_logs_severity_created_at", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_created_at", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_session_id", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_request_id", table_name="moderation_logs")
    op.execute("DROP TABLE moderation_logs")
    op.drop_index("ix_moderation_rules_category_active", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_active", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_category", table_name="moderation_rules")
    op.execute("DROP TABLE moderation_rules")
    op.execute("DROP TYPE moderation_log_severity")
    op.execute("DROP TYPE moderation_action_taken")
    op.execute("DROP TYPE moderation_log_category")
    op.execute("DROP TYPE moderation_severity")
    op.execute("DROP TYPE moderation_action")
    op.execute("DROP TYPE moderation_pattern_type")
    op.execute("DROP TYPE moderation_category")
