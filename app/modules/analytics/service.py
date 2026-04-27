import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procedures.models import Deviation, ProcedureSession

log = structlog.get_logger()


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_compliance_report(self) -> dict:
        # Aggregate deviations by type
        q = select(Deviation.deviation_type, func.count(Deviation.id).label("count")).group_by(
            Deviation.deviation_type
        )

        result = await self.db.execute(q)
        type_counts = {r.deviation_type: r.count for r in result.all()}

        # Aggregate by severity
        q_sev = select(Deviation.severity, func.count(Deviation.id).label("count")).group_by(
            Deviation.severity
        )

        result_sev = await self.db.execute(q_sev)
        severity_counts = {r.severity: r.count for r in result_sev.all()}

        # Calculate pass/fail rate (mock logic: fail if any critical deviation)
        total_sessions_q = select(func.count(ProcedureSession.id))
        total_sessions = (await self.db.execute(total_sessions_q)).scalar() or 0

        failed_sessions_q = select(func.count(func.distinct(Deviation.session_id))).where(
            Deviation.severity == "critical"
        )
        failed_sessions = (await self.db.execute(failed_sessions_q)).scalar() or 0

        pass_rate = (
            ((total_sessions - failed_sessions) / total_sessions * 100)
            if total_sessions > 0
            else 100
        )

        return {
            "summary": {
                "total_deviations": sum(type_counts.values()),
                "pass_rate_percentage": round(pass_rate, 2),
                "total_sessions_analyzed": total_sessions,
            },
            "by_type": type_counts,
            "by_severity": severity_counts,
        }
