from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aegis",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="content.parse_document")
def parse_document(source_id: str, source_type: str, file_bytes: bytes):
    """Parse an uploaded document and extract sections."""
    import asyncio
    import structlog
    from app.database import async_session_factory
    from app.modules.content.models import ContentSource, ContentSection, ContentReference
    from app.modules.content.parsers.factory import ParserFactory
    from sqlalchemy import select

    log = structlog.get_logger()
    log.info("parse_document_started", source_id=source_id, source_type=source_type)

    async def _parse():
        async with async_session_factory() as db:
            # 1. Get source
            result = await db.execute(select(ContentSource).where(ContentSource.id == source_id))
            source = result.scalar_one_or_none()
            if not source:
                log.error("source_not_found", source_id=source_id)
                return

            try:
                # 2. Parse
                parser = ParserFactory.get_parser(source_type)
                sections = parser.parse(file_bytes)

                # 3. Save sections recursively
                async def _save_sections(parsed_sections, parent_id=None):
                    for ps in parsed_sections:
                        sec = ContentSection(
                            source_id=source.id,
                            parent_section_id=parent_id,
                            section_number=ps.section_number,
                            title=ps.title,
                            content_markdown=ps.content_markdown,
                            page_number=ps.page_number,
                            ordinal=ps.ordinal,
                        )
                        db.add(sec)
                        await db.flush()

                        # Create citation reference
                        ref = ContentReference(
                            source_id=source.id,
                            section_id=sec.id,
                            citation_key=f"{source.source_type.upper()}-{source.version}-{ps.section_number}",
                            display_label=f"{source.source_type.upper()} §{ps.section_number} — {ps.title}",
                        )
                        db.add(ref)

                        if ps.children:
                            await _save_sections(ps.children, sec.id)

                await _save_sections(sections)
                await db.commit()

                # 4. Index in Meilisearch
                from meilisearch_python_async import Client
                from app.config import get_settings
                settings = get_settings()

                async with Client(settings.MEILI_URL, settings.MEILI_MASTER_KEY) as client:
                    index = client.index("content_sections")
                    documents = []
                    # Simple flattening for indexing
                    def _collect_for_indexing(parsed_sections):
                        for ps in parsed_sections:
                            documents.append({
                                "id": f"{source_id}_{ps.section_number.replace('.', '_')}",
                                "source_id": source_id,
                                "section_number": ps.section_number,
                                "title": ps.title,
                                "content": ps.content_markdown,
                            })
                            if ps.children:
                                _collect_for_indexing(ps.children)
                    
                    _collect_for_indexing(sections)
                    if documents:
                        await index.add_documents(documents)

                log.info("parse_document_completed", source_id=source_id, sections_count=len(sections))

            except Exception as e:
                log.error("parse_document_failed", source_id=source_id, error=str(e))
                await db.rollback()

    asyncio.run(_parse())
    return {"source_id": source_id, "status": "completed"}
