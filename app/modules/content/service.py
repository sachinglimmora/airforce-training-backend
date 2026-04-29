import hashlib
import io
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config import get_settings as _get_settings_for_cadence
from app.core.exceptions import NotFound
from app.modules.content.models import ContentReference, ContentSection, ContentSource
from app.modules.rag.tasks import embed_source

log = structlog.get_logger()
_settings = get_settings()


def _cadence_for(source_type: str) -> int:
    """Returns review cadence in days based on source type."""
    s = _get_settings_for_cadence()
    return {
        "fcom": s.CONTENT_REVIEW_CADENCE_DAYS_FCOM,
        "qrh": s.CONTENT_REVIEW_CADENCE_DAYS_QRH,
        "amm": s.CONTENT_REVIEW_CADENCE_DAYS_AMM,
        "sop": s.CONTENT_REVIEW_CADENCE_DAYS_SOP,
        "syllabus": s.CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS,
    }.get(source_type, s.CONTENT_REVIEW_CADENCE_DAYS_DEFAULT)


def _upload_to_minio_sync(file_bytes: bytes, object_key: str) -> None:
    from minio import Minio

    client = Minio(
        _settings.MINIO_ENDPOINT,
        access_key=_settings.MINIO_ACCESS_KEY,
        secret_key=_settings.MINIO_SECRET_KEY,
        secure=_settings.MINIO_SECURE,
    )
    bucket = _settings.MINIO_BUCKET_CONTENT
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(bucket, object_key, io.BytesIO(file_bytes), len(file_bytes))


class ContentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sources(
        self,
        source_type: str | None = None,
        aircraft_id: str | None = None,
        status: str | None = None,
    ) -> list[ContentSource]:
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

    async def create_source(
        self, data, file_bytes: bytes, uploader_id: str
    ) -> tuple[ContentSource, str]:  # noqa: ARG002
        import asyncio

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

        job_id = f"job_{uuid.uuid4().hex[:12]}"

        if _settings.MINIO_ACCESS_KEY and _settings.MINIO_SECRET_KEY:
            object_key = f"content/{source.id}/{data.source_type}_{data.version}"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _upload_to_minio_sync, file_bytes, object_key)
            source.original_file_url = f"{_settings.MINIO_BUCKET_CONTENT}/{object_key}"

            from app.worker import parse_document

            parse_document.delay(str(source.id), data.source_type, object_key)
            log.info("content_ingestion_queued", source_id=str(source.id), job_id=job_id)
        else:
            log.warning(
                "minio_not_configured_parse_skipped",
                source_id=str(source.id),
                hint="Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY to enable document parsing",
            )

        return source, job_id

    async def approve_source(self, source_id: str, approver_id: str) -> ContentSource:
        from datetime import UTC, datetime

        source = await self.get_source(source_id)
        source.approved_by = approver_id
        source.approved_at = datetime.now(UTC)
        source.status = "approved"
        if source.next_review_due is None:
            from datetime import UTC, datetime, timedelta
            source.next_review_due = datetime.now(UTC) + timedelta(days=_cadence_for(source.source_type))
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
        result = await self.db.execute(
            select(ContentSection).where(ContentSection.id == section_id)
        )
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

    async def mark_reviewed(self, source_id: str, reviewer_id, override_days: int | None = None) -> ContentSource:
        from datetime import UTC, datetime, timedelta
        source = await self.get_source(source_id)
        cadence = override_days if override_days is not None else _cadence_for(source.source_type)
        source.last_reviewed_at = datetime.now(UTC)
        source.last_reviewed_by = reviewer_id
        source.next_review_due = datetime.now(UTC) + timedelta(days=cadence)
        await self.db.flush()
        return source

    async def list_needs_review(
        self,
        source_type: str | None = None,
        aircraft_id=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentSource]:
        from datetime import UTC, datetime
        q = select(ContentSource).where(
            ContentSource.status == "approved",
            ContentSource.next_review_due.isnot(None),
            ContentSource.next_review_due <= datetime.now(UTC),
        )
        if source_type:
            q = q.where(ContentSource.source_type == source_type)
        if aircraft_id:
            q = q.where(ContentSource.aircraft_id == aircraft_id)
        q = q.order_by(ContentSource.next_review_due.asc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def list_expiring_soon(
        self,
        within_days: int = 14,
        source_type: str | None = None,
        aircraft_id=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentSource]:
        from datetime import UTC, datetime, timedelta
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=within_days)
        q = select(ContentSource).where(
            ContentSource.status == "approved",
            ContentSource.next_review_due.isnot(None),
            ContentSource.next_review_due > now,
            ContentSource.next_review_due <= cutoff,
        )
        if source_type:
            q = q.where(ContentSource.source_type == source_type)
        if aircraft_id:
            q = q.where(ContentSource.aircraft_id == aircraft_id)
        q = q.order_by(ContentSource.next_review_due.asc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def search(self, q: str, limit: int = 20) -> list[dict]:
        from meilisearch_python_async import Client

        from app.config import get_settings

        settings = get_settings()

        async with Client(settings.MEILI_URL, settings.MEILI_MASTER_KEY) as client:
            index = client.index("content_sections")
            search_results = await index.search(q, limit=limit)
            return search_results.hits
