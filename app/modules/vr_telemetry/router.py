from datetime import datetime
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.vr_telemetry.models import VRSession, VRTelemetryEvent

router = APIRouter()


class StartVRSessionRequest(BaseModel):
    training_session_id: str
    device_id: str
    device_type: str
    runtime: str = "webxr"
    app_version: str | None = None


class VREventIn(BaseModel):
    id: str | None = None
    event_type: str
    timestamp: datetime
    head_pose: dict | None = None
    controller_left: dict | None = None
    controller_right: dict | None = None
    interaction_target: str | None = None
    payload: dict | None = None


class BatchEventsRequest(BaseModel):
    events: list[VREventIn]


class EndVRSessionRequest(BaseModel):
    frame_rate_avg: float | None = None


@router.post("/sessions", status_code=201, summary="Register VR session start")
async def start_vr_session(
    body: StartVRSessionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = VRSession(
        training_session_id=body.training_session_id,
        device_id=body.device_id,
        device_type=body.device_type,
        runtime=body.runtime,
        app_version=body.app_version,
    )
    db.add(session)
    await db.flush()
    return {"data": {"vr_session_id": str(session.id)}}


@router.post("/sessions/{vr_session_id}/events", status_code=202, summary="Batch ingest VR events")
async def ingest_events(
    vr_session_id: str,
    body: BatchEventsRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    accepted = 0
    duplicates = 0

    for event in body.events:
        if event.id:
            # Deduplicate on client-generated ID
            existing = await db.execute(
                select(VRTelemetryEvent).where(VRTelemetryEvent.client_event_id == event.id)
            )
            if existing.scalar_one_or_none():
                duplicates += 1
                continue

        tel = VRTelemetryEvent(
            vr_session_id=vr_session_id,
            client_event_id=event.id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            head_pose=event.head_pose,
            controller_left=event.controller_left,
            controller_right=event.controller_right,
            interaction_target=event.interaction_target,
            payload=event.payload,
        )
        db.add(tel)
        accepted += 1

    return {"data": {"accepted": accepted, "duplicates": duplicates}}


@router.post("/sessions/{vr_session_id}/end", summary="Mark VR session ended")
async def end_vr_session(
    vr_session_id: str,
    body: EndVRSessionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime
    from decimal import Decimal
    result = await db.execute(select(VRSession).where(VRSession.id == vr_session_id))
    session = result.scalar_one_or_none()
    if session:
        session.ended_at = datetime.now(UTC)
        if body.frame_rate_avg is not None:
            session.frame_rate_avg = Decimal(str(body.frame_rate_avg))
    return {"data": {"vr_session_id": vr_session_id, "status": "ended"}}


@router.get("/sessions/{vr_session_id}", summary="Get VR session summary")
async def get_vr_session(
    vr_session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(VRSession).where(VRSession.id == vr_session_id))
    session = result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound
        raise NotFound("VR session")

    event_count_result = await db.execute(
        select(VRTelemetryEvent).where(VRTelemetryEvent.vr_session_id == vr_session_id)
    )
    event_count = len(event_count_result.scalars().all())

    return {
        "data": {
            "id": str(session.id),
            "device_id": session.device_id,
            "device_type": session.device_type,
            "runtime": session.runtime,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "frame_rate_avg": float(session.frame_rate_avg) if session.frame_rate_avg else None,
            "event_count": event_count,
        }
    }
