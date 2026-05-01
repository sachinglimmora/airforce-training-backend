import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.modules.auth.models import User
from app.modules.procedures.models import Procedure, ProcedureStep
from app.modules.scenarios.models import Scenario
from app.modules.competency.models import Rubric, Competency, CompetencyEvidence, Evaluation
from app.modules.analytics.models import TrainingSession, SessionEvent
from app.modules.content.models import Aircraft
from app.modules.checklist.models import Checklist, ChecklistItem
from app.modules.training.models import Course, TrainingModule

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def seed_sessions():
    print(f"Connecting to: {settings.DATABASE_URL[:60]}…")
    async with AsyncSession_() as db:
        async with db.begin():
            # 1. Fetch dependencies
            print("Fetching users...")
            trainee1 = (await db.execute(select(User).where(User.email == "trainee1@aegis.internal"))).scalar_one_or_none()
            instructor = (await db.execute(select(User).where(User.email == "instructor@aegis.internal"))).scalar_one_or_none()
            evaluator = (await db.execute(select(User).where(User.email == "evaluator@aegis.internal"))).scalar_one_or_none()
            
            if not trainee1 or not instructor or not evaluator:
                print("Missing users. Run seed_full.py first.")
                return

            print("Fetching content...")
            procedure = (await db.execute(select(Procedure).where(Procedure.name == "Engine Fire — In Flight"))).scalar_one_or_none()
            scenario = (await db.execute(select(Scenario).where(Scenario.scenario_code == "ENG-FIRE-INFLIGHT-B737"))).scalar_one_or_none()
            rubric = (await db.execute(select(Rubric).where(Rubric.name == "Standard Procedure Evaluation"))).scalar_one_or_none()
            competency_sys = (await db.execute(select(Competency).where(Competency.code == "SYS-KNW"))).scalar_one_or_none()
            competency_dec = (await db.execute(select(Competency).where(Competency.code == "DECISION"))).scalar_one_or_none()

            if not procedure or not scenario or not rubric:
                print("Missing content (procedure/scenario/rubric). Run seed_full.py first.")
                return

            procedure_steps = (await db.execute(select(ProcedureStep).where(ProcedureStep.procedure_id == procedure.id).order_by(ProcedureStep.ordinal))).scalars().all()

            # 2. Create a Completed Training Session
            print("Creating past completed session...")
            past_start = datetime.now(UTC) - timedelta(days=1, hours=2)
            past_end = past_start + timedelta(minutes=45)
            
            completed_session = TrainingSession(
                trainee_id=trainee1.id,
                instructor_id=instructor.id,
                session_type="vr",
                procedure_id=procedure.id,
                scenario_id=scenario.id,
                started_at=past_start,
                ended_at=past_end,
                status="completed",
                metadata_json={"sim_id": "SIM-42", "weather": "VMC"}
            )
            db.add(completed_session)
            await db.flush()

            # 3. Create Session Events for the completed session
            print("Creating session events...")
            for i, step in enumerate(procedure_steps[:5]): # simulate completing first 5 steps
                event = SessionEvent(
                    session_id=completed_session.id,
                    event_type="step_completed",
                    step_id=step.id,
                    timestamp=past_start + timedelta(minutes=i*2),
                    elapsed_ms=120000,
                    payload={"success": True, "action": step.action_text}
                )
                db.add(event)
            await db.flush()

            # 4. Create Evaluation for the completed session
            print("Creating evaluation...")
            evaluation = Evaluation(
                session_id=completed_session.id,
                evaluator_id=evaluator.id,
                rubric_id=rubric.id,
                scores={
                    "procedural_compliance": 8.5,
                    "systems_knowledge": 9.0,
                    "decision_making": 8.0,
                    "crm": 7.5
                },
                total_score=Decimal("84.50"),
                grade="satisfactory",
                comments="Good handling of the engine fire, but communication could be slightly faster.",
                evaluated_at=past_end + timedelta(hours=1)
            )
            db.add(evaluation)
            await db.flush()

            # 5. Create Competency Evidence
            print("Creating competency evidence...")
            if competency_sys:
                db.add(CompetencyEvidence(
                    trainee_id=trainee1.id,
                    competency_id=competency_sys.id,
                    session_id=completed_session.id,
                    score=Decimal("9.0"),
                    recorded_at=past_end + timedelta(hours=1)
                ))
            if competency_dec:
                db.add(CompetencyEvidence(
                    trainee_id=trainee1.id,
                    competency_id=competency_dec.id,
                    session_id=completed_session.id,
                    score=Decimal("8.0"),
                    recorded_at=past_end + timedelta(hours=1)
                ))
            await db.flush()

            # 6. Create an In-Progress Training Session
            print("Creating an active session...")
            active_start = datetime.now(UTC) - timedelta(minutes=15)
            active_session = TrainingSession(
                trainee_id=trainee1.id,
                instructor_id=instructor.id,
                session_type="scenario",
                scenario_id=scenario.id,
                started_at=active_start,
                status="in_progress",
                metadata_json={"sim_id": "SIM-43", "weather": "IMC"}
            )
            db.add(active_session)
            await db.flush()
            
            # Active session events
            event1 = SessionEvent(
                session_id=active_session.id,
                event_type="telemetry",
                timestamp=active_start + timedelta(minutes=5),
                payload={"airspeed_kts": 250, "altitude_ft": 10000, "pitch": 5.0, "roll": 0.0}
            )
            event2 = SessionEvent(
                session_id=active_session.id,
                event_type="scenario_triggered",
                timestamp=active_start + timedelta(minutes=10),
                payload={"trigger": "ENG FIRE 1"}
            )
            db.add(event1)
            db.add(event2)
            await db.flush()

    print("\nSession data seeded successfully.")

if __name__ == "__main__":
    asyncio.run(seed_sessions())
