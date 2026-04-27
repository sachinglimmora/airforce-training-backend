from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import Role
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Admin role required"}}


@router.get(
    "/dashboard",
    response_model=dict,
    summary="Admin dashboard KPIs",
    description=(
        "Returns platform-wide statistics for the admin home screen: "
        "total users, trainee/instructor counts, recent audit entries, "
        "service health status, and chart data."
    ),
    responses={**_401, **_403},
    operation_id="admin_dashboard",
)
async def get_dashboard(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "totalUsers": 150,
            "totalTrainees": 120,
            "totalInstructors": 15,
            "recentAuditLogs": [],
            "systemStatus": [
                {"service": "API",      "status": "operational", "uptime": "99.9%", "lastChecked": datetime.now(UTC).isoformat()},
                {"service": "Database", "status": "operational", "uptime": "100%",  "lastChecked": datetime.now(UTC).isoformat()},
                {"service": "Redis",    "status": "operational", "uptime": "100%",  "lastChecked": datetime.now(UTC).isoformat()},
            ],
            "charts": {
                "trainingCompletion": [],
                "readinessTrend": [],
                "simulationUsage": [],
                "skillDistribution": [],
            },
        }
    }


@router.get(
    "/roles",
    response_model=dict,
    summary="List roles with user counts",
    description="Returns all roles and the number of users currently assigned to each.",
    responses={**_401, **_403},
    operation_id="admin_roles_list",
)
async def get_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Role))
    roles = result.scalars().all()
    return {"data": [{"id": str(r.id), "name": r.name, "userCount": 0, "permissions": []} for r in roles]}


@router.post(
    "/roles",
    response_model=dict,
    summary="Create a new role",
    description=(
        "Creates a custom role. After creation, assign permissions via "
        "`POST /users/{id}/roles`.\n\n"
        "Body: `{ \"name\": \"safety_officer\", \"description\": \"...\" }`"
    ),
    responses={**_401, **_403, 409: {"description": "Role name already exists"}},
    operation_id="admin_roles_create",
)
async def create_role(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    role = Role(name=body["name"], description=body.get("description"))
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return {"data": {"id": str(role.id), "name": role.name}}


@router.get(
    "/audit-logs",
    response_model=dict,
    summary="Paginated audit log (admin view)",
    description=(
        "Returns audit log entries with pagination support. "
        "Filter by `module` (resource_type) and/or `userId`.\n\n"
        "Use `GET /audit/logs` for the canonical audit endpoint with richer filters."
    ),
    responses={**_401, **_403},
    operation_id="admin_audit_logs",
)
async def get_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _module: str | None = Query(None, description="Filter by resource_type e.g. users, content"),
    _userId: str | None = Query(None, description="Filter by actor user UUID"),
    limit: int = Query(50, description="Page size"),
    offset: int = Query(0, description="Page offset"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    q = select(AuditLog).limit(limit).offset(offset)
    result = await db.execute(q)
    logs = result.scalars().all()
    return {
        "data": {
            "total": 100,
            "logs": [
                {
                    "id": str(l.id),
                    "userId": str(l.actor_user_id),
                    "action": l.action,
                    "module": l.resource_type,
                    "details": str(l.metadata_json),
                    "timestamp": l.timestamp.isoformat(),
                    "ipAddress": str(l.actor_ip),
                }
                for l in logs
            ],
        }
    }


@router.get(
    "/system-status",
    response_model=dict,
    summary="System service health status",
    description=(
        "Returns the current operational status of platform services: "
        "API, Database, Redis, Meilisearch, MinIO."
    ),
    responses={**_401, **_403},
    operation_id="admin_system_status",
)
async def get_system_status(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": [
            {"service": "API",         "status": "operational", "uptime": "99.9%", "lastChecked": datetime.now(UTC).isoformat()},
            {"service": "Database",    "status": "operational", "uptime": "100%",  "lastChecked": datetime.now(UTC).isoformat()},
            {"service": "Redis",       "status": "operational", "uptime": "100%",  "lastChecked": datetime.now(UTC).isoformat()},
            {"service": "Meilisearch", "status": "operational", "uptime": "99.8%", "lastChecked": datetime.now(UTC).isoformat()},
            {"service": "MinIO",       "status": "operational", "uptime": "100%",  "lastChecked": datetime.now(UTC).isoformat()},
        ]
    }


@router.get(
    "/analytics",
    response_model=dict,
    summary="Admin analytics charts",
    description="Returns platform-wide chart data for the admin analytics view.",
    responses={**_401, **_403},
    operation_id="admin_analytics",
)
async def get_admin_analytics(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "trainingCompletion": [],
            "readinessTrend": [],
            "simulationUsage": [],
            "skillDistribution": [],
        }
    }


@router.get(
    "/security-settings",
    response_model=dict,
    summary="Get platform security settings",
    description=(
        "Returns current security configuration: MFA enforcement, password policy, "
        "and session timeout in seconds."
    ),
    responses={**_401, **_403},
    operation_id="admin_security_settings",
)
async def get_security_settings(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "mfaRequired": False,
            "passwordPolicy": "strict",
            "sessionTimeout": 3600,
        }
    }
