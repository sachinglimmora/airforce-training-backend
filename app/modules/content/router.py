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

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Insufficient permissions"}}
_404 = {404: {"description": "Resource not found"}}


@router.get(
    "/sources",
    response_model=dict,
    summary="List content sources",
    description=(
        "Returns all ingested documents. Filter by `source_type` "
        "(fcom | qrh | amm | sop | syllabus), `aircraft_id`, or "
        "`status` (draft | approved | archived).\n\n"
        "**Required permission:** `content:read`"
    ),
    responses={**_401, **_403},
    operation_id="content_sources_list",
)
async def list_sources(
    source_type: str | None = Query(None, description="fcom | qrh | amm | sop | syllabus"),
    aircraft_id: str | None = Query(None, description="Filter to a specific aircraft UUID"),
    status: str | None = Query(None, description="draft | approved | archived"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = ContentService(db)
    sources = await svc.list_sources(source_type, aircraft_id, status)
    return {"data": [ContentSourceOut.model_validate(s).model_dump() for s in sources]}


@router.post(
    "/sources",
    status_code=202,
    response_model=dict,
    summary="Upload and parse a source document",
    description=(
        "Upload a PDF or DOCX document for async parsing. "
        "The document is stored in MinIO, parsed by the matching parser "
        "(FCOM → `fcom.py`, QRH → `qrh.py`, etc.) via a Celery worker, "
        "and sections are written to `content_sections` with `citation_key` references.\n\n"
        "**Returns 202** with `source_id` and `job_id`. "
        "Poll `GET /content/sources/{source_id}` until `status` leaves `parsing`.\n\n"
        "**Form fields:**\n"
        "- `file` (required) — the document binary\n"
        "- `source_type` (required) — fcom | qrh | amm | sop | syllabus\n"
        "- `title` (required) — display name\n"
        "- `version` (required) — document revision string, e.g. `Rev 42`\n"
        "- `aircraft_id` (optional) — link to a specific aircraft\n"
        "- `effective_date` (optional) — ISO date, e.g. `2026-01-15`\n\n"
        "**Required permission:** `content:create`"
    ),
    responses={**_401, **_403, 400: {"description": "Unsupported file type or malformed form data"}},
    operation_id="content_sources_upload",
)
async def upload_source(
    file: UploadFile = File(..., description="PDF or DOCX source document"),
    source_type: str = Form(..., description="fcom | qrh | amm | sop | syllabus"),
    title: str = Form(...),
    version: str = Form(...),
    aircraft_id: str | None = Form(None),
    effective_date: str | None = Form(None, description="ISO date e.g. 2026-01-15"),
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


@router.get(
    "/sources/{source_id}",
    response_model=dict,
    summary="Get source metadata",
    description=(
        "Returns metadata for a single content source including parse status, "
        "version, effective date, and approval state. Poll this after upload to detect completion."
    ),
    responses={**_401, **_404},
    operation_id="content_sources_get",
)
async def get_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.get_source(source_id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.get(
    "/sources/{source_id}/tree",
    response_model=dict,
    summary="Get full section hierarchy (RAG contract with Shreyansh)",
    description=(
        "Returns the parsed section tree for a source document. "
        "This is the **primary contract** for Shreyansh's RAG chunking pipeline.\n\n"
        "Each node includes `citation_key` (stable ID like `B737-FCOM-3.2.1`), "
        "`content_markdown`, and `children` recursively.\n\n"
        "The RAG pipeline retrieves chunks by `citation_key`; every AI answer must cite at least one."
    ),
    responses={**_401, **_404},
    operation_id="content_sources_tree",
)
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


@router.post(
    "/sources/{source_id}/approve",
    response_model=dict,
    summary="Approve a content source for use",
    description=(
        "Marks the source as `approved`, making it visible to trainees and instructors. "
        "Records the approver and timestamp. Only approved sources are injected into AI context.\n\n"
        "**Required permission:** `content:approve`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="content_sources_approve",
)
async def approve_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.approve_source(source_id, current_user.id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.post(
    "/sources/{source_id}/reembed",
    status_code=202,
    response_model=dict,
    summary="Force re-embedding of a source (admin)",
    description=(
        "Deletes existing chunks for the source_id and re-runs the embedding worker. "
        "Use after chunker improvements or model changes.\n\n"
        "**Required permission:** `content:approve` (admin/instructor)."
    ),
    responses={**_401, **_403, **_404},
    operation_id="content_sources_reembed",
)
async def reembed_source_endpoint(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("admin", "instructor"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    svc = ContentService(db)
    src = await svc.get_source(source_id)  # 404s if missing
    from app.modules.rag.tasks import reembed_source
    reembed_source.delay(str(src.id))
    return {"data": {"source_id": str(src.id), "status": "reembedding"}}


@router.post(
    "/sources/{source_id}/archive",
    response_model=dict,
    summary="Archive a content source",
    description=(
        "Moves the source to `archived` status. Archived sources are hidden from normal reads "
        "but preserved for audit. Use this when superseded by a new revision.\n\n"
        "**Required permission:** `content:update`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="content_sources_archive",
)
async def archive_source(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    src = await svc.archive_source(source_id)
    return {"data": ContentSourceOut.model_validate(src).model_dump()}


@router.get(
    "/sections/{section_id}",
    response_model=dict,
    summary="Get a single section's content",
    description="Returns the parsed markdown content and metadata for one content section.",
    responses={**_401, **_404},
    operation_id="content_sections_get",
)
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


@router.get(
    "/references/{citation_key}",
    response_model=dict,
    summary="Resolve a citation key to its section and source",
    description=(
        "Looks up a stable citation key (e.g. `B737-FCOM-3.2.1`) and returns the full section "
        "content plus its source metadata. Used by the AI gateway and the RAG pipeline."
    ),
    responses={**_401, 400: {"description": "CITATION_NOT_FOUND"}, **_404},
    operation_id="content_references_resolve",
)
async def resolve_citation(
    citation_key: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = ContentService(db)
    ref = await svc.resolve_citation(citation_key)
    return {"data": ContentReferenceOut.model_validate(ref).model_dump()}


@router.get(
    "/search",
    response_model=dict,
    summary="Full-text search over content (Meilisearch)",
    description=(
        "Searches all approved content sections using Meilisearch. "
        "Returns ranked results with section id, title, citation_key, and a content excerpt.\n\n"
        "Query must be at least 2 characters."
    ),
    responses={**_401},
    operation_id="content_search",
)
async def search_content(
    q: str = Query(..., min_length=2, description="Search query (min 2 characters)"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = ContentService(db)
    results = await svc.search(q)
    return {"data": results}
