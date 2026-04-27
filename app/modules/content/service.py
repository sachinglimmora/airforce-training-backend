import hashlib
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.modules.content.models import ContentReference, ContentSection, ContentSource
from app.modules.rag.tasks import embed_source

log = structlog.get_logger()


class ContentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sources(self, source_type: str | None = None, aircraft_id: str | None = None, status: str | None = None) -> list[ContentSource]:
        q = select(ContentSource)
        if source_type:
            q = q.where(ContentSource.source_type == source_type)
        if aircraft_id:
            q = q.where(ContentSource.aircraft_id == aircraft_id)
        if status:
            q = q.where(ContentSource.status == status)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def get_source(self, source_id: str) -> ContentSource:
        result = await self.db.execute(select(ContentSource).where(ContentSource.id == source_id))
        src = result.scalar_one_or_none()
        if not src:
            raise NotFound("Content source")
        return src

    async def create_source(self, data, file_bytes: bytes, uploader_id: str) -> tuple[ContentSource, str]:
        checksum = hashlib.sha256(file_bytes).hexdigest()
        source = ContentSource(
            source_type=data.source_type,
            aircraft_id=data.aircraft_id,
            title=data.title,
            version=data.version,
            effective_date=data.effective_date,
            checksum_sha256=checksum,
            status="draft",
        )
        self.db.add(source)
        await self.db.flush()

        # Enqueue async parsing job
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        log.info("content_ingestion_queued", source_id=str(source.id), job_id=job_id)
        
        from app.worker import parse_document
        parse_document.delay(str(source.id), data.source_type, file_bytes)

        return source, job_id

    async def approve_source(self, source_id: str, approver_id: str) -> ContentSource:
        from datetime import UTC, datetime
        source = await self.get_source(source_id)
        source.approved_by = approver_id
        source.approved_at = datetime.now(UTC)
        source.status = "approved"
        await self.db.flush()
        embed_source.delay(str(source.id))
        log.info("approve_source_enqueued_embed", source_id=str(source.id))
        return source

    async def archive_source(self, source_id: str) -> ContentSource:
        source = await self.get_source(source_id)
        source.status = "archived"
        return source

    async def get_source_tree(self, source_id: str) -> ContentSource:
        source = await self.get_source(source_id)
        return source

    async def get_section(self, section_id: str) -> ContentSection:
        result = await self.db.execute(select(ContentSection).where(ContentSection.id == section_id))
        sec = result.scalar_one_or_none()
        if not sec:
            raise NotFound("Content section")
        return sec

    async def resolve_citation(self, citation_key: str) -> ContentReference:
        result = await self.db.execute(
            select(ContentReference).where(ContentReference.citation_key == citation_key)
        )
        ref = result.scalar_one_or_none()
        if not ref:
            raise NotFound(f"Citation '{citation_key}'")
        return ref

    async def search(self, q: str, limit: int = 20) -> list[dict]:
        from meilisearch_python_async import Client
        from app.config import get_settings
        settings = get_settings()

        async with Client(settings.MEILI_URL, settings.MEILI_MASTER_KEY) as client:
            index = client.index("content_sections")
            search_results = await index.search(q, limit=limit)
            return search_results.hits
