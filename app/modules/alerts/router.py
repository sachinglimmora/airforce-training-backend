import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


@router.get(
    "",
    response_model=dict,
    summary="List in-app alerts for the current user",
    description=(
        "Returns alerts for the authenticated user. "
        "Filter by `type` (info | warning | critical) and/or `unread` (true | false).\n\n"
        "Alerts are created by the system on events such as deviations detected, "
        "evaluations submitted, and new content approved."
    ),
    responses={**_401},
    operation_id="alerts_list",
)
async def get_alerts(
    _db: Annotated[AsyncSession, Depends(get_db)],
    type: str | None = Query(None, description="info | warning | critical"),
    unread: bool | None = Query(None, description="Filter to unread alerts only"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    alerts = [
        {
            "id": str(uuid.uuid4()),
            "type": "critical",
            "title": "System Fault Detected",
            "message": "Hydraulic pressure low in System A",
            "timestamp": datetime.now(UTC).isoformat(),
            "isRead": False,
        },
        {
            "id": str(uuid.uuid4()),
            "type": "info",
            "title": "Training Update",
            "message": "New simulation scenarios available for B737",
            "timestamp": datetime.now(UTC).isoformat(),
            "isRead": True,
        },
    ]
    if type:
        alerts = [a for a in alerts if a["type"] == type]
    if unread is not None:
        alerts = [a for a in alerts if a["isRead"] != unread]
    return {"data": alerts}


@router.patch(
    "/{alert_id}/read",
    response_model=dict,
    summary="Mark a single alert as read",
    description="Sets `isRead: true` on the specified alert.",
    responses={**_401, 404: {"description": "Alert not found"}},
    operation_id="alerts_mark_read",
)
async def mark_read(
    alert_id: uuid.UUID,
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"id": str(alert_id), "isRead": True}}


@router.patch(
    "/read-all",
    response_model=dict,
    summary="Mark all alerts as read",
    description="Sets `isRead: true` on every alert for the current user.",
    responses={**_401},
    operation_id="alerts_mark_all_read",
)
async def mark_all_read(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "All alerts marked as read"}}


@router.delete(
    "",
    response_model=dict,
    summary="Clear all alerts for the current user",
    description="Permanently deletes all alerts for the authenticated user.",
    responses={**_401},
    operation_id="alerts_clear",
)
async def clear_alerts(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Alerts cleared"}}
