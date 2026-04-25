from typing import Annotated, List, Optional
import uuid
from datetime import UTC, datetime
from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.auth.models import User, Role
from app.modules.audit.models import AuditLog

router = APIRouter()

@router.get("/dashboard", response_model=dict)
async def get_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # Aggregated stats for admin
    return {
        "data": {
            "totalUsers": 150,
            "totalTrainees": 120,
            "totalInstructors": 15,
            "recentAuditLogs": [],
            "systemStatus": [
                {"service": "API", "status": "operational", "uptime": "99.9%", "lastChecked": datetime.now(UTC).isoformat()},
                {"service": "Database", "status": "operational", "uptime": "100%", "lastChecked": datetime.now(UTC).isoformat()},
                {"service": "Redis", "status": "operational", "uptime": "100%", "lastChecked": datetime.now(UTC).isoformat()}
            ],
            "charts": {
                "trainingCompletion": [],
                "readinessTrend": [],
                "simulationUsage": [],
                "skillDistribution": []
            }
        }
    }

@router.get("/roles", response_model=dict)
async def get_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Role))
    roles = result.scalars().all()
    return {"data": [{"id": str(r.id), "name": r.name, "userCount": 0} for r in roles]}

@router.post("/roles", response_model=dict)
async def create_role(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    role = Role(name=body["name"], description=body.get("description"))
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return {"data": {"id": str(role.id), "name": role.name}}

@router.get("/audit-logs", response_model=dict)
async def get_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    module: Optional[str] = Query(None),
    userId: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    q = select(AuditLog)
    # Add filters...
    result = await db.execute(q.limit(limit).offset(offset))
    logs = result.scalars().all()
    
    return {
        "data": {
            "total": 100, # Mock total
            "logs": [
                {
                    "id": str(l.id),
                    "userId": str(l.actor_user_id),
                    "userName": "System", # Mock
                    "action": l.action,
                    "module": l.resource_type,
                    "details": str(l.metadata),
                    "timestamp": l.timestamp.isoformat(),
                    "ipAddress": str(l.actor_ip)
                }
                for l in logs
            ]
        }
    }

@router.get("/system-status", response_model=dict)
async def get_system_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": [
            {"service": "API", "status": "operational", "uptime": "99.9%", "lastChecked": datetime.now(UTC).isoformat()},
            {"service": "Database", "status": "operational", "uptime": "100%", "lastChecked": datetime.now(UTC).isoformat()}
        ]
    }

@router.get("/analytics", response_model=dict)
async def get_admin_analytics(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "trainingCompletion": [],
            "readinessTrend": [],
            "simulationUsage": [],
            "skillDistribution": []
        }
    }

@router.get("/security-settings", response_model=dict)
async def get_security_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "mfaRequired": False,
            "passwordPolicy": "strict",
            "sessionTimeout": 3600
        }
    }
