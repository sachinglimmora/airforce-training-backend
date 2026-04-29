"""Celery tasks: embed_source, reembed_source, reembed_all_dim_mismatch, auto_close_idle_sessions."""

import asyncio

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.modules.content.models import ContentSection, ContentSource
from app.modules.rag.chunker import chunk_section_tree
from app.modules.rag.embedder import embed_and_validate
from app.modules.rag.models import ContentChunk
from app.worker import celery_app

log = structlog.get_logger()
_settings = get_settings()
_BATCH_SIZE = 50


async def _load_source_with_tree(db, source_id: str) -> ContentSource | None:
    result = await db.execute(
        select(ContentSource)
        .where(ContentSource.id == source_id)
        .options(
            selectinload(ContentSource.sections).selectinload(ContentSection.children),
            selectinload(ContentSource.sections).selectinload(ContentSection.reference),
        )
    )
    return result.scalar_one_or_none()


async def _delete_chunks(db, source_id: str) -> int:
    from sqlalchemy import delete
    result = await db.execute(delete(ContentChunk).where(ContentChunk.source_id == source_id))
    return result.rowcount or 0


async def _reembed_source_async(source_id: str) -> int:
    async with AsyncSessionLocal() as db:
        deleted = await _delete_chunks(db, source_id)
        await db.commit()
        log.info("reembed_source_deleted", source_id=source_id, count=deleted)
    # Now run normal ingestion
    return await _embed_source_async(source_id)


async def _embed_source_async(source_id: str) -> int:
    print(f"[embed_source] starting for source {source_id}")
    async with AsyncSessionLocal() as db:
        source = await _load_source_with_tree(db, source_id)
        if not source:
            log.warning("embed_source_missing", source_id=source_id)
            return 0

        existing_count = (await db.execute(
            select(ContentChunk).where(ContentChunk.source_id == source.id).limit(1)
        )).first()
        if existing_count:
            log.info("embed_source_skipped_existing", source_id=source_id)
            return 0

        chunks = chunk_section_tree(source)
        if not chunks:
            log.warning("embed_source_no_chunks", source_id=source_id)
            source.embedding_status = "succeeded"
            await db.commit()
            return 0

        # Batched embedding
        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]
            try:
                vectors = await embed_and_validate([c["content"] for c in batch])
            except Exception as exc:
                log.error("embed_source_failed", source_id=source_id, error=str(exc))
                source.embedding_status = "failed"
                await db.commit()
                raise
            for chunk_dict, vec in zip(batch, vectors, strict=True):
                db.add(ContentChunk(
                    source_id=source.id,
                    section_id=chunk_dict["section_id"],
                    citation_keys=chunk_dict["citation_keys"],
                    content=chunk_dict["content"],
                    token_count=chunk_dict["token_count"],
                    ordinal=chunk_dict["ordinal"],
                    embedding=vec,
                    embedding_model=_settings.EMBEDDING_MODEL_HINT,
                    embedding_dim=_settings.EMBEDDING_DIM,
                ))

        # Supersedence sweep
        prior = (await db.execute(
            select(ContentSource).where(
                ContentSource.source_type == source.source_type,
                ContentSource.aircraft_id == source.aircraft_id,
                ContentSource.title == source.title,
                ContentSource.id != source.id,
                ContentSource.status == "approved",
            )
        )).scalars().all()
        for old in prior:
            old.status = "archived"
            await db.execute(
                ContentChunk.__table__.update()
                .where(ContentChunk.source_id == old.id)
                .values(superseded_by_source_id=source.id)
            )

        source.embedding_status = "succeeded"
        await db.commit()
        print(f"[embed_source] completed, returned {len(chunks)}")
        return len(chunks)


@celery_app.task(name="rag.embed_source", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def embed_source(source_id: str) -> int:
    return asyncio.run(_embed_source_async(source_id))


@celery_app.task(name="rag.reembed_source", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reembed_source(source_id: str) -> int:
    return asyncio.run(_reembed_source_async(source_id))


async def _reembed_all_dim_mismatch_async() -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ContentChunk.source_id)
            .where(ContentChunk.embedding_dim != _settings.EMBEDDING_DIM)
            .distinct()
        )).scalars().all()
    count = 0
    for source_id in rows:
        reembed_source.delay(str(source_id))
        count += 1
    log.info("reembed_all_dim_mismatch_enqueued", count=count)
    return count


@celery_app.task(name="rag.reembed_all_dim_mismatch")
def reembed_all_dim_mismatch() -> int:
    return asyncio.run(_reembed_all_dim_mismatch_async())


async def _auto_close_idle_sessions_async() -> int:
    from datetime import UTC, datetime, timedelta
    cutoff = datetime.now(UTC) - timedelta(days=_settings.CHAT_SESSION_AUTO_CLOSE_DAYS)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import update

        from app.modules.ai_assistant.models import ChatSession
        result = await db.execute(
            update(ChatSession)
            .where(ChatSession.status == "active", ChatSession.last_activity_at < cutoff)
            .values(status="closed", closed_at=datetime.now(UTC))
        )
        await db.commit()
        return result.rowcount or 0


@celery_app.task(name="rag.auto_close_idle_sessions")
def auto_close_idle_sessions() -> int:
    return asyncio.run(_auto_close_idle_sessions_async())
