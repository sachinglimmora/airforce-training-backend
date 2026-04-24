from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.service import AuditService
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()


@router.get("/logs", summary="Query audit log")
async def list_audit_logs(
    actor: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    from_time: datetime | None = Query(None),
    to_time: datetime | None = Query(None),
    limit: int = Query(50, le=200),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    q = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    if actor:
        q = q.where(AuditLog.actor_user_id == actor)
    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if from_time:
        q = q.where(AuditLog.timestamp >= from_time)
    if to_time:
        q = q.where(AuditLog.timestamp <= to_time)

    result = await db.execute(q)
    entries = result.scalars().all()
    return {
        "data": [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "actor_user_id": e.actor_user_id,
                "actor_ip": e.actor_ip,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "outcome": e.outcome,
            }
            for e in entries
        ]
    }


@router.get("/logs/{log_id}", summary="Get single audit entry")
async def get_audit_log(
    log_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
    entry = result.scalar_one_or_none()
    if not entry:
        from app.core.exceptions import NotFound
        raise NotFound("Audit log entry")
    return {
        "data": {
            "id": entry.id,
            "timestamp": entry.timestamp.isoformat(),
            "actor_user_id": entry.actor_user_id,
            "action": entry.action,
            "outcome": entry.outcome,
            "row_hash": entry.row_hash,
            "prev_hash": entry.prev_hash,
        }
    }


@router.get("/logs/verify", summary="Verify audit log hash chain integrity")
async def verify_chain(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuditService(db)
    result = await svc.verify_chain()
    return {"data": result}
