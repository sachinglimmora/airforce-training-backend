import hashlib
import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog

log = structlog.get_logger()


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        action: str,
        actor_user_id: str | None = None,
        actor_ip: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: str = "success",
        metadata: dict | None = None,
    ) -> AuditLog:
        # Fetch last entry to continue the hash chain
        last_result = await self.db.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
        )
        last = last_result.scalar_one_or_none()
        prev_hash = last.row_hash if last else None

        entry = AuditLog(
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata_json=metadata,
            prev_hash=prev_hash,
        )
        self.db.add(entry)
        await self.db.flush()

        # Compute row hash
        row_data = {
            "id": entry.id,
            "timestamp": entry.timestamp.isoformat(),
            "actor_user_id": actor_user_id,
            "action": action,
            "outcome": outcome,
            "prev_hash": prev_hash,
        }
        entry.row_hash = hashlib.sha256(json.dumps(row_data, sort_keys=True).encode()).hexdigest()

        log.info("audit_logged", action=action, actor=actor_user_id, outcome=outcome)
        return entry

    async def verify_chain(self) -> dict:
        result = await self.db.execute(select(AuditLog).order_by(AuditLog.id.asc()))
        entries = result.scalars().all()

        broken_at = None
        for entry in entries:
            row_data = {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "actor_user_id": entry.actor_user_id,
                "action": entry.action,
                "outcome": entry.outcome,
                "prev_hash": entry.prev_hash,
            }
            expected = hashlib.sha256(json.dumps(row_data, sort_keys=True).encode()).hexdigest()
            if entry.row_hash and entry.row_hash != expected:
                broken_at = entry.id
                break

        return {
            "total_entries": len(entries),
            "integrity": "ok" if broken_at is None else "compromised",
            "broken_at_id": broken_at,
        }
