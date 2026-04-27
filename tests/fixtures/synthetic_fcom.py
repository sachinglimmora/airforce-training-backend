"""Synthetic FCOM-shaped section tree for RAG integration tests.

Builds real ContentSource + ContentSection + ContentReference rows so the
ingestion pipeline can be tested without Sachin's real parsers.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentReference, ContentSection, ContentSource


async def seed_synthetic_fcom(db: AsyncSession, aircraft_id: uuid.UUID | None = None) -> ContentSource:
    """Insert one approved FCOM-shaped source with 4 sections, return the source."""
    source = ContentSource(
        id=uuid.uuid4(),
        source_type="fcom",
        aircraft_id=aircraft_id,
        title="Synthetic FCOM",
        version="Rev 1",
        effective_date=datetime.now(UTC).date(),
        status="approved",
        approved_by=None,
        approved_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()

    sections_data = [
        ("3", "Engines", 0, None,
         "Engine systems overview. " * 5,
         "SYN-FCOM-3", 100),
        ("3.1", "Engine Start - Normal", 0, None,
         "Place ENG MASTER to ON. Verify N1 rises above 25% before introducing fuel. " * 30,
         "SYN-FCOM-3.1", 105),
        ("3.2", "Engine Start - Cold Weather", 1, None,
         "Below 0 degC OAT, motor the engine for 30 seconds prior to fuel introduction. " * 30,
         "SYN-FCOM-3.2", 108),
        ("4", "Hydraulics", 1, None,
         "Two independent hydraulic systems supply flight controls. " * 25,
         "SYN-FCOM-4", 200),
    ]

    parent_section = None
    for sec_num, title, ordinal, _parent_idx, body, citation_key, page in sections_data:
        section = ContentSection(
            id=uuid.uuid4(),
            source_id=source.id,
            parent_section_id=None,  # flat for simplicity
            section_number=sec_num,
            title=title,
            content_markdown=body,
            page_number=page,
            ordinal=ordinal,
        )
        db.add(section)
        await db.flush()

        ref = ContentReference(
            id=uuid.uuid4(),
            source_id=source.id,
            section_id=section.id,
            citation_key=citation_key,
            display_label=f"FCOM §{sec_num} - {title}",
        )
        db.add(ref)

    await db.flush()
    return source
