"""Seed the Su-30MKI Engine Start — Normal procedure.

Idempotent — safe to re-run. Skips if the procedure already exists
for the first aircraft in the database.

Run with:
    .venv/Scripts/python.exe -m scripts.seed_procedures
or:
    python scripts/seed_procedures.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.modules.content.models import Aircraft
from app.modules.procedures.models import Procedure, ProcedureStep

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PROCEDURE_NAME = "Engine Start — Normal"


async def main():
    print(f"Connecting to: {settings.DATABASE_URL[:60]}…")
    async with AsyncSession_() as db:
        async with db.begin():
            # ── Load first Aircraft ─────────────────────────────────────────
            ac_result = await db.execute(select(Aircraft).limit(1))
            aircraft = ac_result.scalar_one_or_none()
            if not aircraft:
                print("ERROR: No aircraft found in database. Run seed_full.py first.")
                return

            print(f"Using aircraft: {aircraft.display_name} ({aircraft.type_code})")

            # ── Idempotency check ───────────────────────────────────────────
            existing = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.name == PROCEDURE_NAME,
                        Procedure.aircraft_id == aircraft.id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                print(f"Procedure '{PROCEDURE_NAME}' already exists — skipping.")
                return

            # ── Create Procedure ────────────────────────────────────────────
            proc = Procedure(
                name=PROCEDURE_NAME,
                procedure_type="normal",
                phase="ground",
                aircraft_id=aircraft.id,
                citation_key="SU30-FCOM-3.2.1",
            )
            db.add(proc)
            await db.flush()
            print(f"  + procedure: {proc.name} (id={proc.id})")

            # ── Create Steps (linear) ───────────────────────────────────────
            # Steps 1-5 are linear; step 5 is the EGT branch point.
            # Steps 6a (branch A) and 6b (branch B) are children of step 5.
            # Steps 7-8 are linear again (children of no one — root-level by ordinal).

            step1 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=1,
                action_text="Check cockpit switches to ground crew signal",
                mode="do_verify",
                is_critical=False,
                target_time_seconds=30,
            )
            step2 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=2,
                action_text="Fuel cock — OPEN",
                mode="do_verify",
                is_critical=True,
                target_time_seconds=10,
            )
            step3 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=3,
                action_text="Throttle — IDLE",
                mode="do_verify",
                is_critical=True,
                target_time_seconds=10,
            )
            step4 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=4,
                action_text="Engine start button — PRESS",
                mode="read_do",
                is_critical=True,
                target_time_seconds=15,
            )
            step5 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=5,
                action_text="Check EGT within limits",
                mode="do_verify",
                is_critical=True,
                target_time_seconds=20,
            )

            for s in [step1, step2, step3, step4, step5]:
                db.add(s)
            await db.flush()

            # Branch A — EGT normal
            step6a = ProcedureStep(
                procedure_id=proc.id,
                ordinal=6,
                action_text="Continue normal start sequence",
                mode="do_verify",
                is_critical=False,
                parent_step_id=step5.id,
                branch_condition="EGT normal",
            )
            # Branch B — cold weather
            step6b = ProcedureStep(
                procedure_id=proc.id,
                ordinal=6,
                action_text="Apply cold weather enrichment — throttle 3-5%",
                mode="do_verify",
                is_critical=True,
                parent_step_id=step5.id,
                branch_condition="EGT low cold weather",
                citation_key="SU30-FCOM-3.2.4",
            )

            step7 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=7,
                action_text="Monitor RPM — check 60% within 30s",
                mode="do_verify",
                is_critical=True,
                target_time_seconds=35,
            )
            step8 = ProcedureStep(
                procedure_id=proc.id,
                ordinal=8,
                action_text="Check oil pressure — GREEN",
                mode="do_verify",
                is_critical=False,
                target_time_seconds=15,
            )

            for s in [step6a, step6b, step7, step8]:
                db.add(s)
            await db.flush()

            print(f"  + step 1: {step1.action_text}")
            print(f"  + step 2: {step2.action_text}")
            print(f"  + step 3: {step3.action_text}")
            print(f"  + step 4: {step4.action_text}")
            print(f"  + step 5: {step5.action_text}  [branch point]")
            print(f"  + step 6a (branch A): {step6a.action_text}")
            print(f"  + step 6b (branch B): {step6b.action_text}")
            print(f"  + step 7: {step7.action_text}")
            print(f"  + step 8: {step8.action_text}")

    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(main())
