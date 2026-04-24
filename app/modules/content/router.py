from typing import Annotated

from fastapi import Depends, File, Form, Query, UploadFile
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.content.schemas import ContentReferenceOut, ContentSourceOut, IngestionJobOut
from app.modules.content.service import ContentService

router = APIRouter()


@router.get("/sources", summary="List content sources")
async def list_sources(
    source_type: str | None = Query(None),
    aircraft_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = ContentService(db)
    sources = await svc.list_sources(source_type, aircraft_id, status)
    return {"data": [ContentSourceOut.model_validate(s).model_dump() for s in sources]}


@router.post("/sources", status_code=202, summary="Upload and parse a document")
async def upload_source(
    file: UploadFile = File(...),
    source_type: str = Form(...),
    title: str = Form(...),
    version: str = Form(...),
    aircraft_id: str | None = Form(None),
    effective_date: str | None = Form(None),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    from app.modules.content.schemas import UploadSourceRequest
    from datetime import date

    data = UploadSourceRequest(
        source_type=source_type,
        title=title,
        version=version,
        aircraft_id=aircraft_id,
        effective_date=date.fromisoformat(effective_date) if effective_date else None,
    )
    file_bytes = await file.read()
    svc = ContentService(db)
    source, job_id = await svc.create_source(data, file_bytes, current_user.id)
    return {"data": IngestionJobOut(source_id=source.id, status="parsing", job_id=job_id).model_dump()}


@router.get("/sources/{source_id}", summary="Get source metadata")
async def get_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.get_source(source_id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.get("/sources/{source_id}/tree", summary="Get full section hierarchy (RAG contract)")
async def get_source_tree(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.get_source_tree(source_id)

    def _serialize_section(sec) -> dict:
        citation_key = sec.reference.citation_key if sec.reference else None
        return {
            "id": str(sec.id),
            "section_number": sec.section_number,
            "title": sec.title,
            "citation_key": citation_key,
            "page_number": sec.page_number,
            "content_markdown": sec.content_markdown,
            "children": [_serialize_section(c) for c in sorted(sec.children, key=lambda x: x.ordinal)],
        }

    root_sections = [s for s in src.sections if s.parent_section_id is None]
    return {
        "data": {
            "source_id": str(src.id),
            "source_type": src.source_type,
            "version": src.version,
            "sections": [_serialize_section(s) for s in sorted(root_sections, key=lambda x: x.ordinal)],
        }
    }


@router.post("/sources/{source_id}/approve", summary="Approve content source")
async def approve_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.approve_source(source_id, current_user.id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.post("/sources/{source_id}/archive", summary="Archive content source")
async def archive_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.archive_source(source_id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.get("/sections/{section_id}", summary="Get single section content")
async def get_section(
    section_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    sec = await svc.get_section(section_id)
    return {
        "data": {
            "id": str(sec.id),
            "section_number": sec.section_number,
            "title": sec.title,
            "content_markdown": sec.content_markdown,
            "page_number": sec.page_number,
        }
    }


@router.get("/references/{citation_key}", summary="Resolve citation key to section")
async def resolve_citation(
    citation_key: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    ref = await svc.resolve_citation(citation_key)
    return {"data": ContentReferenceOut.model_validate(ref).model_dump()}


@router.get("/search", summary="Full-text search over content")
async def search_content(
    q: str = Query(..., min_length=2),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = ContentService(db)
    results = await svc.search(q)
    return {"data": results}
