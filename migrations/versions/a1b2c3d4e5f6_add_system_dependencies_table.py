"""add_system_dependencies_table

Revision ID: a1b2c3d4e5f6
Revises: 2b5785d05c7d
Create Date: 2026-05-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "2b5785d05c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_dependencies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_system_id", sa.UUID(), nullable=False),
        sa.Column("target_system_id", sa.UUID(), nullable=False),
        sa.Column("dependency_type", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["aircraft_systems.id"],
            name="fk_system_dependencies_source",
        ),
        sa.ForeignKeyConstraint(
            ["target_system_id"],
            ["aircraft_systems.id"],
            name="fk_system_dependencies_target",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_system_dependencies_source_system_id"),
        "system_dependencies",
        ["source_system_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_dependencies_target_system_id"),
        "system_dependencies",
        ["target_system_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_system_dependencies_target_system_id"), table_name="system_dependencies"
    )
    op.drop_index(
        op.f("ix_system_dependencies_source_system_id"), table_name="system_dependencies"
    )
    op.drop_table("system_dependencies")
