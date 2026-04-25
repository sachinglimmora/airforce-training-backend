from typing import Annotated, List, Optional
import uuid
from datetime import UTC, datetime
from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

@router.get("", response_model=dict)
async def get_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
    type: Optional[str] = Query(None),
    unread: Optional[bool] = Query(None),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Mock alerts
    alerts = [
        {
            "id": str(uuid.uuid4()),
            "type": "critical",
            "title": "System Fault Detected",
            "message": "Hydraulic Pressure low in System A",
            "timestamp": datetime.now(UTC).isoformat(),
            "isRead": False
        },
        {
            "id": str(uuid.uuid4()),
            "type": "info",
            "title": "Training Update",
            "message": "New simulation scenarios available for B737",
            "timestamp": datetime.now(UTC).isoformat(),
            "isRead": True
        }
    ]
    return {"data": alerts}

@router.patch("/{alert_id}/read", response_model=dict)
async def mark_read(
    alert_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"id": str(alert_id), "isRead": True}}

@router.patch("/read-all", response_model=dict)
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "All alerts marked as read"}}

@router.delete("", response_model=dict)
async def clear_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Alerts cleared"}}
