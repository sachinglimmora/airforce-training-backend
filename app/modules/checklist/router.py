from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.checklist.models import Checklist, ChecklistSession

router = APIRouter()


class StartSessionRequest(BaseModel):
    mode: str = "challenge_response"
    trainee_id: str | None = None


class ItemActionRequest(BaseModel):
    response: str | None = None


@router.get("", summary="List checklists")
async def list_checklists(
    aircraft_id: str | None = Query(None),
    phase: str | None = Query(None),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    q = select(Checklist)
    if aircraft_id:
        q = q.where(Checklist.aircraft_id == aircraft_id)
    if phase:
        q = q.where(Checklist.phase == phase)
    result = await db.execute(q)
    checklists = result.scalars().all()
    return {"data": [{"id": str(c.id), "name": c.name, "phase": c.phase} for c in checklists]}


@router.get("/{checklist_id}", summary="Get checklist definition")
async def get_checklist(
    checklist_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Checklist).where(Checklist.id == checklist_id))
    cl = result.scalar_one_or_none()
    if not cl:
        from app.core.exceptions import NotFound
        raise NotFound("Checklist")
    return {
        "data": {
            "id": str(cl.id),
            "name": cl.name,
            "phase": cl.phase,
            "items": [
                {
                    "id": str(item.id),
                    "ordinal": item.ordinal,
                    "challenge": item.challenge,
                    "expected_response": item.expected_response,
                    "mode": item.mode,
                    "target_time_seconds": item.target_time_seconds,
                    "is_critical": item.is_critical,
                }
                for item in cl.items
            ],
        }
    }


@router.post("/{checklist_id}/sessions", status_code=201, summary="Start checklist session")
async def start_session(
    checklist_id: str,
    body: StartSessionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.models import TrainingSession

    ts = TrainingSession(
        trainee_id=body.trainee_id or current_user.id,
        session_type="checklist",
        status="in_progress",
    )
    db.add(ts)
    await db.flush()

    session = ChecklistSession(
        id=ts.id,
        checklist_id=checklist_id,
        trainee_id=ts.trainee_id,
    )
    db.add(session)
    await db.flush()

    result = await db.execute(select(Checklist).where(Checklist.id == checklist_id))
    cl = result.scalar_one_or_none()
    await db.commit()

    return {
        "data": {
            "session_id": str(ts.id),
            "checklist_id": checklist_id,
            "items": [
                {
                    "id": str(item.id),
                    "ordinal": item.ordinal,
                    "challenge": item.challenge,
                    "expected_response": item.expected_response,
                    "target_time_seconds": item.target_time_seconds,
                }
                for item in (cl.items if cl else [])
            ],
            "started_at": ts.started_at.isoformat(),
        }
    }


@router.post("/sessions/{session_id}/items/{item_id}/call", summary="Trainee calls a checklist item (challenge)")
async def call_item(
    session_id: str,
    item_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.models import SessionEvent

    event = SessionEvent(
        session_id=session_id,
        event_type="checklist_item_called",
        payload={"item_id": item_id, "actor": str(current_user.id)},
    )
    db.add(event)
    await db.commit()
    return {"data": {"session_id": session_id, "item_id": item_id, "status": "called"}}


@router.post("/sessions/{session_id}/items/{item_id}/respond", summary="Respond to a checklist item (response)")
async def respond_item(
    session_id: str,
    item_id: str,
    body: ItemActionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.models import SessionEvent

    event = SessionEvent(
        session_id=session_id,
        event_type="checklist_item_responded",
        payload={"item_id": item_id, "response": body.response, "actor": str(current_user.id)},
    )
    db.add(event)
    await db.commit()
    return {"data": {"session_id": session_id, "item_id": item_id, "response": body.response, "status": "responded"}}


@router.post("/sessions/{session_id}/complete", status_code=200, summary="Complete checklist session")
async def complete_session(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime

    result = await db.execute(select(ChecklistSession).where(ChecklistSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.ended_at = datetime.now(UTC)
    return {"data": {"session_id": session_id, "status": "completed"}}


@router.get("/sessions/{session_id}", summary="Get checklist session state")
async def get_session(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(ChecklistSession).where(ChecklistSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound
        raise NotFound("Checklist session")
    return {
        "data": {
            "session_id": str(session.id),
            "status": session.status,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        }
    }
