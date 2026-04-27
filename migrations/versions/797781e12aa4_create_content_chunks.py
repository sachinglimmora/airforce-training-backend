"""create_content_chunks

Revision ID: 797781e12aa4
Revises: 9270e8657838
Create Date: 2026-04-27 16:53:33.197372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '797781e12aa4'
down_revision: Union[str, None] = '9270e8657838'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE content_chunks (
            id UUID PRIMARY KEY,
            source_id UUID NOT NULL REFERENCES content_sources(id),
            section_id UUID NOT NULL REFERENCES content_sections(id),
            citation_keys JSONB NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            ordinal INTEGER NOT NULL DEFAULT 0,
            embedding vector(1536) NOT NULL,
            embedding_model VARCHAR(64) NOT NULL,
            embedding_dim INTEGER NOT NULL,
            superseded_by_source_id UUID NULL REFERENCES content_sources(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_content_chunks_source_id", "content_chunks", ["source_id"])
    op.create_index("ix_content_chunks_section_id", "content_chunks", ["section_id"])
    op.create_index("ix_content_chunks_superseded_by", "content_chunks", ["superseded_by_source_id"])
    op.create_index("ix_content_chunks_source_ordinal", "content_chunks", ["source_id", "ordinal"])
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding ON content_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_embedding")
    op.drop_index("ix_content_chunks_source_ordinal", table_name="content_chunks")
    op.drop_index("ix_content_chunks_superseded_by", table_name="content_chunks")
    op.drop_index("ix_content_chunks_section_id", table_name="content_chunks")
    op.drop_index("ix_content_chunks_source_id", table_name="content_chunks")
    op.execute("DROP TABLE content_chunks")
