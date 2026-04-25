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

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Requires audit:read permission (admin only in Phase 1)"}}
_404 = {404: {"description": "Audit entry not found"}}


@router.get(
    "/logs",
    response_model=dict,
    summary="Query the audit log",
    description=(
        "Returns audit log entries in reverse-chronological order. "
        "Filter by actor, action, resource type, and/or time range.\n\n"
        "**Actions logged:** `auth.login` · `auth.logout` · `auth.password_changed` · "
        "`user.created` · `user.deleted` · `user.role_assigned` · "
        "`content.uploaded` · `content.approved` · `ai.query` · "
        "`data.accessed` · `config.changed` · `session.evaluated`\n\n"
        "**Required permission:** `audit:read`"
    ),
    responses={**_401, **_403},
    operation_id="audit_logs_list",
)
async def list_audit_logs(
    actor: str | None = Query(None, description="Filter by actor user UUID"),
    action: str | None = Query(None, description="Filter by action string e.g. auth.login"),
    resource_type: str | None = Query(None, description="Filter by resource type e.g. users, content"),
    from_time: datetime | None = Query(None, description="Start of time range (RFC 3339)"),
    to_time: datetime | None = Query(None, description="End of time range (RFC 3339)"),
    limit: int = Query(50, le=200, description="Max results (max 200)"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
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


@router.get(
    "/logs/{log_id}",
    response_model=dict,
    summary="Get a single audit log entry",
    description=(
        "Returns a single audit entry including its `row_hash` and `prev_hash` "
        "for manual chain verification."
    ),
    responses={**_401, **_403, **_404},
    operation_id="audit_logs_get",
)
async def get_audit_log(
    log_id: int,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get(
    "/logs/verify",
    response_model=dict,
    summary="Verify audit log hash chain integrity",
    description=(
        "Recomputes the SHA-256 hash chain from the first entry to the last and "
        "returns whether it is intact.\n\n"
        "Response: `{ \"total_entries\": 1240, \"integrity\": \"ok\", \"broken_at_id\": null }`\n\n"
        "If `integrity` is `compromised`, `broken_at_id` identifies the first tampered entry."
    ),
    responses={**_401, **_403},
    operation_id="audit_logs_verify",
)
async def verify_chain(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuditService(db)
    result = await svc.verify_chain()
    return {"data": result}
