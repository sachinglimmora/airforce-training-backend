"""quiz_tables

Revision ID: c3d4e5f6a7b8
Revises: 2b5785d05c7d
Create Date: 2026-05-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "2b5785d05c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aircraft", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("system", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("time_limit", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("passing_score", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("generated_by", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("quiz_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "question_type",
            sa.Enum(
                "multiple-choice",
                "true-false",
                "fill-blank",
                "matching",
                name="question_type",
            ),
            nullable=False,
            server_default="multiple-choice",
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("difficulty", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("topic", sa.String(length=128), nullable=False, server_default="general"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("quiz_id", sa.UUID(), nullable=False),
        sa.Column("trainee_id", sa.UUID(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("time_taken", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainee_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    op.create_index("ix_quiz_attempts_trainee_id", "quiz_attempts", ["trainee_id"])


def downgrade() -> None:
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_questions")
    op.drop_table("quizzes")
    op.execute("DROP TYPE IF EXISTS question_type")
