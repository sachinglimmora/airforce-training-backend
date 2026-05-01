from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.content.models import Aircraft, ContentSource

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}

_SOURCE_TYPE_TO_CATEGORY = {
    "fcom": "manual",
    "qrh": "procedure",
    "amm": "manual",
    "sop": "procedure",
    "syllabus": "manual",
}

_SAMPLE_DOCUMENTS = [
    {
        "id": "doc-001",
        "title": "Su-30MKI Flight Crew Operating Manual Vol.1",
        "description": "Primary operating manual covering normal procedures, limitations, and aircraft systems for the Su-30MKI Flanker.",
        "category": "manual",
        "aircraft": "su-30mki",
        "system": "general",
        "fileType": "pdf",
        "fileSize": 15728640,
        "tags": ["FCOM", "Su-30MKI", "normal procedures", "limitations"],
        "uploadedBy": "Technical Publications",
        "viewCount": 284,
        "createdAt": "2024-06-01T00:00:00Z",
        "updatedAt": "2025-01-10T00:00:00Z",
    },
    {
        "id": "doc-002",
        "title": "Su-30MKI Quick Reference Handbook",
        "description": "QRH containing abnormal and emergency checklists for in-flight use. Must be accessible in cockpit at all times.",
        "category": "procedure",
        "aircraft": "su-30mki",
        "system": "general",
        "fileType": "pdf",
        "fileSize": 2097152,
        "tags": ["QRH", "emergency", "abnormal", "checklist"],
        "uploadedBy": "Technical Publications",
        "viewCount": 512,
        "createdAt": "2024-06-01T00:00:00Z",
        "updatedAt": "2025-01-15T00:00:00Z",
    },
    {
        "id": "doc-003",
        "title": "AL-31FP Engine Maintenance Manual",
        "description": "Detailed maintenance procedures for the Saturn AL-31FP turbofan engine including inspection intervals, replacement limits, and troubleshooting.",
        "category": "manual",
        "aircraft": "su-30mki",
        "system": "engine",
        "fileType": "pdf",
        "fileSize": 23068672,
        "tags": ["AMM", "engine", "AL-31FP", "maintenance", "Su-30MKI"],
        "uploadedBy": "Technical Publications",
        "viewCount": 156,
        "createdAt": "2024-05-15T00:00:00Z",
        "updatedAt": "2024-11-20T00:00:00Z",
    },
    {
        "id": "doc-004",
        "title": "Hydraulic System Diagram — Su-30MKI",
        "description": "Engineering diagram showing dual hydraulic circuit architecture, pump locations, accumulator positions, and selector valve routing.",
        "category": "diagram",
        "aircraft": "su-30mki",
        "system": "hydraulics",
        "fileType": "pdf",
        "fileSize": 3145728,
        "tags": ["diagram", "hydraulics", "Su-30MKI", "system schematic"],
        "uploadedBy": "Technical Publications",
        "viewCount": 98,
        "createdAt": "2024-04-01T00:00:00Z",
        "updatedAt": "2024-10-05T00:00:00Z",
    },
    {
        "id": "doc-005",
        "title": "N011M BARS Radar — Operator's Technical Order",
        "description": "Technical order for the Phazotron N011M BARS radar system including mode operation, BIT procedures, and fault code matrix.",
        "category": "technical-order",
        "aircraft": "su-30mki",
        "system": "avionics",
        "fileType": "pdf",
        "fileSize": 8388608,
        "tags": ["technical-order", "radar", "N011M", "BARS", "avionics"],
        "uploadedBy": "Technical Publications",
        "viewCount": 201,
        "createdAt": "2024-03-10T00:00:00Z",
        "updatedAt": "2024-12-01T00:00:00Z",
    },
    {
        "id": "doc-006",
        "title": "Engine Start Checklist — Laminated Card",
        "description": "Laminated cockpit checklist for normal engine start sequence including APU start, ignition, post-start monitoring, and abort criteria.",
        "category": "checklist",
        "aircraft": "su-30mki",
        "system": "engine",
        "fileType": "pdf",
        "fileSize": 524288,
        "tags": ["checklist", "engine start", "Su-30MKI", "normal procedures"],
        "uploadedBy": "Technical Publications",
        "viewCount": 634,
        "createdAt": "2024-02-20T00:00:00Z",
        "updatedAt": "2025-01-05T00:00:00Z",
    },
    {
        "id": "doc-007",
        "title": "MiG-29 Flight Manual",
        "description": "Comprehensive flight manual for the MiG-29 Fulcrum covering all normal, abnormal, and emergency procedures.",
        "category": "manual",
        "aircraft": "mig-29",
        "system": "general",
        "fileType": "pdf",
        "fileSize": 12582912,
        "tags": ["manual", "MiG-29", "Fulcrum", "normal procedures"],
        "uploadedBy": "Technical Publications",
        "viewCount": 178,
        "createdAt": "2024-01-15T00:00:00Z",
        "updatedAt": "2024-09-30T00:00:00Z",
    },
    {
        "id": "doc-008",
        "title": "Fuel System Technical Bulletin — TB-2024-047",
        "description": "Technical bulletin addressing fuel probe calibration drift identified across fleet. Mandatory compliance within 30 days of issue.",
        "category": "bulletin",
        "aircraft": "su-30mki",
        "system": "fuel",
        "fileType": "pdf",
        "fileSize": 1048576,
        "tags": ["bulletin", "fuel", "mandatory", "calibration", "Su-30MKI"],
        "uploadedBy": "Fleet Support",
        "viewCount": 445,
        "createdAt": "2024-11-15T00:00:00Z",
        "updatedAt": "2024-11-15T00:00:00Z",
    },
    {
        "id": "doc-009",
        "title": "HAL Tejas — Pilot's Information File",
        "description": "Operating information file for the Tejas Mk1A including performance charts, limitations, and normal procedures.",
        "category": "manual",
        "aircraft": "tejas",
        "system": "general",
        "fileType": "pdf",
        "fileSize": 9437184,
        "tags": ["Tejas", "Mk1A", "HAL", "PIF", "normal procedures"],
        "uploadedBy": "Technical Publications",
        "viewCount": 312,
        "createdAt": "2024-07-01T00:00:00Z",
        "updatedAt": "2024-12-20T00:00:00Z",
    },
    {
        "id": "doc-010",
        "title": "TCAS II Resolution Advisory Procedures",
        "description": "Standard operating procedures for TCAS II RA responses, crew coordination, and ATC communication requirements.",
        "category": "procedure",
        "aircraft": "general",
        "system": "avionics",
        "fileType": "pdf",
        "fileSize": 786432,
        "tags": ["TCAS", "RA", "collision avoidance", "general", "SOP"],
        "uploadedBy": "Flight Safety",
        "viewCount": 267,
        "createdAt": "2024-05-20T00:00:00Z",
        "updatedAt": "2024-10-15T00:00:00Z",
    },
]


def _source_to_doc(source: ContentSource, aircraft_name: str = "general") -> dict:
    category = _SOURCE_TYPE_TO_CATEGORY.get(source.source_type, "manual")
    return {
        "id": str(source.id),
        "title": source.title,
        "description": f"{source.source_type.upper()} — Version {source.version}",
        "category": category,
        "aircraft": aircraft_name,
        "system": "general",
        "fileType": "pdf",
        "fileSize": 0,
        "tags": [source.source_type, aircraft_name],
        "uploadedBy": "Technical Publications",
        "viewCount": 0,
        "createdAt": source.created_at.isoformat(),
        "updatedAt": source.updated_at.isoformat(),
    }


@router.get(
    "",
    response_model=dict,
    summary="List document library",
    responses={**_401},
    operation_id="documents_list",
)
async def list_documents(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None),
    category: str | None = Query(None),
    aircraft: str | None = Query(None),
    system: str | None = Query(None),
):
    # Try DB content sources first
    db_result = await db.execute(
        select(ContentSource, Aircraft)
        .outerjoin(Aircraft, ContentSource.aircraft_id == Aircraft.id)
        .where(ContentSource.status == "approved")
    )
    rows = db_result.all()

    if rows:
        docs = [_source_to_doc(src, ac.type_code if ac else "general") for src, ac in rows]
    else:
        docs = list(_SAMPLE_DOCUMENTS)

    # Apply filters
    if search:
        q = search.lower()
        docs = [
            d for d in docs
            if q in d["title"].lower() or q in d["description"].lower()
            or any(q in t.lower() for t in d["tags"])
        ]
    if category:
        docs = [d for d in docs if d["category"] == category]
    if aircraft:
        docs = [d for d in docs if d["aircraft"] == aircraft]
    if system:
        docs = [d for d in docs if d["system"] == system]

    categories = sorted({d["category"] for d in docs})
    aircrafts = sorted({d["aircraft"] for d in docs})
    systems = sorted({d["system"] for d in docs})

    return {
        "data": {
            "documents": docs,
            "categories": categories,
            "aircraft": aircrafts,
            "systems": systems,
        }
    }


@router.get(
    "/{doc_id}",
    response_model=dict,
    summary="Get document detail",
    responses={**_401},
    operation_id="documents_get",
)
async def get_document(
    doc_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Check sample docs
    for doc in _SAMPLE_DOCUMENTS:
        if doc["id"] == doc_id:
            return {"data": doc}

    # Try DB
    try:
        import uuid
        uid = uuid.UUID(doc_id)
        result = await db.execute(
            select(ContentSource, Aircraft)
            .outerjoin(Aircraft, ContentSource.aircraft_id == Aircraft.id)
            .where(ContentSource.id == uid)
        )
        row = result.one_or_none()
        if row:
            src, ac = row
            return {"data": _source_to_doc(src, ac.type_code if ac else "general")}
    except (ValueError, Exception):
        pass

    from app.core.exceptions import NotFound
    raise NotFound("Document")
