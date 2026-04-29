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
    imports=("app.modules.rag.tasks",),
)

celery_app.conf.beat_schedule = {
    "auto-close-idle-sessions-daily": {
        "task": "rag.auto_close_idle_sessions",
        "schedule": 24 * 60 * 60,  # every 24h
    },
}


@celery_app.task(name="content.parse_document")
def parse_document(source_id: str, source_type: str, minio_object_key: str):
    """Download document from MinIO then parse and index its sections."""
    import asyncio

    import structlog
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.modules.content.models import ContentReference, ContentSection, ContentSource
    from app.modules.content.parsers.factory import ParserFactory

    log = structlog.get_logger()
    log.info("parse_document_started", source_id=source_id, source_type=source_type)

    def _download_from_minio() -> bytes:
        from minio import Minio

        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        bucket = settings.MINIO_BUCKET_CONTENT
        response = client.get_object(bucket, minio_object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def _parse():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ContentSource).where(ContentSource.id == source_id))
            source = result.scalar_one_or_none()
            if not source:
                log.error("source_not_found", source_id=source_id)
                return

            try:
                file_bytes = _download_from_minio()

                parser = ParserFactory.get_parser(source_type)
                sections = parser.parse(file_bytes)

                async def _save_sections(parsed_sections, parent_id=None):
                    for ps in parsed_sections:
                        sec = ContentSection(
                            source_id=source.id,
                            parent_section_id=parent_id,
                            section_number=ps.section_number or "0",
                            title=ps.title,
                            content_markdown=ps.content_markdown,
                            page_number=ps.page_number,
                            ordinal=ps.ordinal,
                        )
                        db.add(sec)
                        await db.flush()

                        safe_section_num = (ps.section_number or str(ps.ordinal)).replace("/", "-")
                        citation_key = (
                            f"{source.source_type.upper()}-{source.version}-{safe_section_num}"
                        )
                        ref = ContentReference(
                            source_id=source.id,
                            section_id=sec.id,
                            citation_key=citation_key,
                            display_label=f"{source.source_type.upper()} §{ps.section_number} — {ps.title}",
                        )
                        db.add(ref)

                        if ps.children:
                            await _save_sections(ps.children, sec.id)

                await _save_sections(sections)
                await db.commit()

                # Index in Meilisearch
                try:
                    from meilisearch_python_async import Client

                    async with Client(settings.MEILI_URL, settings.MEILI_MASTER_KEY) as client:
                        index = client.index("content_sections")
                        documents = []

                        def _collect(parsed_sections):
                            for ps in parsed_sections:
                                safe_num = (ps.section_number or str(ps.ordinal)).replace(".", "_")
                                documents.append(
                                    {
                                        "id": f"{source_id}_{safe_num}",
                                        "source_id": source_id,
                                        "section_number": ps.section_number,
                                        "title": ps.title,
                                        "content": ps.content_markdown,
                                    }
                                )
                                if ps.children:
                                    _collect(ps.children)

                        _collect(sections)
                        if documents:
                            await index.add_documents(documents)
                except Exception as meili_err:
                    log.warning("meilisearch_index_failed", error=str(meili_err))

                log.info("parse_document_completed", source_id=source_id, sections=len(sections))

            except Exception as e:
                log.error("parse_document_failed", source_id=source_id, error=str(e))
                await db.rollback()

    asyncio.run(_parse())
    return {"source_id": source_id, "status": "completed"}
