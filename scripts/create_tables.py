import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.database import Base


# Import all models to ensure they are registered with Base.metadata
def import_models():
    try:
        from app.modules.auth.models import (
            Permission,
            RefreshToken,
            Role,
            RolePermission,
            User,
            UserRole,
        )
    except ImportError:
        pass
    try:
        from app.modules.content.models import (
            Aircraft,
            ContentReference,
            ContentSection,
            ContentSource,
        )
    except ImportError:
        pass
    try:
        from app.modules.training.models import Course, TrainingModule
    except ImportError:
        pass
    try:
        from app.modules.checklist.models import Checklist, ChecklistItem, ChecklistSession
    except ImportError:
        pass
    try:
        from app.modules.procedures.models import (
            Deviation,
            Procedure,
            ProcedureSession,
            ProcedureStep,
        )
    except ImportError:
        pass
    try:
        from app.modules.analytics.models import SessionEvent, TrainingSession
    except ImportError:
        pass
    try:
        from app.modules.scenarios.models import Scenario, ScenarioSession
    except ImportError:
        pass
    try:
        from app.modules.competency.models import Competency, CompetencyEvidence, Evaluation, Rubric
    except ImportError:
        pass
    try:
        from app.modules.assets.models import Asset
    except ImportError:
        pass
    try:
        from app.modules.audit.models import AuditLog
    except ImportError:
        pass
    try:
        from app.modules.ai.models import AIRequest
    except ImportError:
        pass
    try:
        from app.modules.digital_twin.models import AircraftSystem, Component
    except ImportError:
        pass
    try:
        from app.modules.vr_telemetry.models import VRSession, VRTelemetryEvent
    except ImportError:
        pass
    try:
        from app.modules.instructor_videos.models import InstructorVideo
    except ImportError:
        pass


import_models()


async def create_tables():
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)

    async with engine.begin() as conn:
        print("Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(create_tables())
