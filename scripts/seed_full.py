"""Full Phase 1 seed — idempotent, safe to re-run.

Creates:
  - Roles + RBAC permissions
  - Aircraft
  - Users  (admin, instructor, evaluator, 3 trainees)
  - Checklists  (B737-800 pre-flight, before-takeoff, after-landing)
  - Procedures  (normal engine start, emergency engine fire with branches)
  - Scenarios   (V1 cut, windshear, TCAS RA, engine fire)
  - Competencies
  - Rubric

Run with:
  python -m scripts.seed_full
"""

import asyncio
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.checklist.models import Checklist, ChecklistItem
from app.modules.competency.models import Competency, Rubric
from app.modules.content.models import Aircraft
from app.modules.procedures.models import Procedure, ProcedureStep
from app.modules.scenarios.models import Scenario

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

ROLES = [
    ("trainee",    "Pilot trainee — execute checklist/procedure sessions"),
    ("instructor", "Instructor — manage trainees, run sessions, create scenarios"),
    ("evaluator",  "Evaluator — submit and review evaluations"),
    ("admin",      "Platform administrator — full access"),
]

# (resource, action)
PERMISSIONS = [
    ("user",        "create"),
    ("user",        "read"),
    ("user",        "update"),
    ("user",        "delete"),
    ("user",        "assign_role"),
    ("content",     "create"),
    ("content",     "read"),
    ("content",     "update"),
    ("content",     "delete"),
    ("content",     "approve"),
    ("session",     "read"),
    ("session",     "update"),
    ("scenario",    "create"),
    ("scenario",    "read"),
    ("scenario",    "update"),
    ("scenario",    "delete"),
    ("evaluation",  "create"),
    ("evaluation",  "read"),
    ("evaluation",  "update"),
    ("asset",       "read"),
    ("audit",       "read"),
    ("ai",          "query"),
    ("rubric",      "create"),
    ("rubric",      "read"),
]

# role → set of (resource, action)
ROLE_PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "trainee": [
        ("content",    "read"),
        ("session",    "read"),
        ("scenario",   "read"),
        ("evaluation", "read"),
        ("asset",      "read"),
        ("ai",         "query"),
        ("rubric",     "read"),
    ],
    "instructor": [
        ("content",    "read"),
        ("user",       "read"),
        ("session",    "read"),
        ("session",    "update"),
        ("scenario",   "create"),
        ("scenario",   "read"),
        ("scenario",   "update"),
        ("scenario",   "delete"),
        ("evaluation", "create"),
        ("evaluation", "read"),
        ("evaluation", "update"),
        ("asset",      "read"),
        ("ai",         "query"),
        ("rubric",     "create"),
        ("rubric",     "read"),
    ],
    "evaluator": [
        ("content",    "read"),
        ("user",       "read"),
        ("session",    "read"),
        ("scenario",   "read"),
        ("evaluation", "create"),
        ("evaluation", "read"),
        ("evaluation", "update"),
        ("asset",      "read"),
        ("audit",      "read"),
        ("ai",         "query"),
        ("rubric",     "read"),
    ],
    "admin": [p for p in PERMISSIONS],  # all
}

AIRCRAFT = [
    ("B737-800", "Boeing",  "Boeing 737-800"),
    ("A320",     "Airbus",  "Airbus A320"),
]

USERS = [
    # (email, full_name, employee_id, password, role)
    ("admin@aegis.internal",      "Platform Admin",   "ADMIN-001", "Aegis@Admin2026!",      "admin"),
    ("instructor@aegis.internal", "Wing Cdr. Sharma", "INST-001",  "Aegis@Inst2026!",       "instructor"),
    ("evaluator@aegis.internal",  "Sqn Ldr. Patel",   "EVAL-001",  "Aegis@Eval2026!",       "evaluator"),
    ("trainee1@aegis.internal",   "Flt Lt. Arjun",    "TRN-001",   "Aegis@Trainee2026!",    "trainee"),
    ("trainee2@aegis.internal",   "Flt Lt. Priya",    "TRN-002",   "Aegis@Trainee2026!",    "trainee"),
    ("trainee3@aegis.internal",   "Fg Offr. Rohan",   "TRN-003",   "Aegis@Trainee2026!",    "trainee"),
]

# Checklists: (name, phase, aircraft_type_code, items)
# item: (ordinal, challenge, expected_response, mode, target_sec, is_critical)
CHECKLISTS = [
    (
        "B737-800 Before Start",
        "pre-flight",
        "B737-800",
        [
            (1,  "Parking Brake",            "SET",           "challenge_response", 3,  True),
            (2,  "Fuel Quantity",             "CHECKED",       "challenge_response", 5,  True),
            (3,  "Hydraulic Fluid Quantity",  "CHECKED",       "challenge_response", 5,  False),
            (4,  "Oxygen — Crew",             "CHECKED / SET", "challenge_response", 5,  False),
            (5,  "Emergency Equipment",       "CHECKED",       "challenge_response", 5,  False),
            (6,  "Seat / Harness",            "ADJUSTED / LOCKED", "challenge_response", 5, False),
            (7,  "Avionics Master Switch",    "ON",            "challenge_response", 3,  True),
            (8,  "Battery Switch",            "ON",            "challenge_response", 3,  True),
            (9,  "Navigation Lights",         "ON",            "challenge_response", 3,  False),
            (10, "Transponder",               "TA/RA",         "challenge_response", 3,  True),
        ],
    ),
    (
        "B737-800 Before Takeoff",
        "takeoff",
        "B737-800",
        [
            (1,  "Flaps",               "SET ___",    "challenge_response", 5,  True),
            (2,  "Trim",                "SET",        "challenge_response", 3,  True),
            (3,  "Thrust Levers",       "SET",        "challenge_response", 3,  True),
            (4,  "Auto-Brake",          "RTO",        "challenge_response", 3,  True),
            (5,  "Landing Lights",      "ON",         "challenge_response", 3,  False),
            (6,  "Transponder",         "TA/RA",      "challenge_response", 3,  True),
            (7,  "Cabin Ready",         "CONFIRMED",  "challenge_response", 5,  False),
            (8,  "Doors",               "CLOSED",     "challenge_response", 3,  True),
            (9,  "ATC Clearance",       "RECEIVED",   "challenge_response", 10, True),
            (10, "TCAS",                "ON",         "challenge_response", 3,  True),
        ],
    ),
    (
        "B737-800 After Landing",
        "landing",
        "B737-800",
        [
            (1,  "Thrust Reversers",    "STOWED",     "do_verify",          5,  True),
            (2,  "Speed Brakes",        "DOWN / OFF", "do_verify",          3,  True),
            (3,  "Auto-Brake",          "OFF",        "challenge_response",  3, False),
            (4,  "Landing Lights",      "OFF",        "challenge_response",  3, False),
            (5,  "Radar",               "OFF",        "challenge_response",  3, False),
            (6,  "APU",                 "START",      "challenge_response",  5, False),
        ],
    ),
]

# Procedures: (name, procedure_type, phase, aircraft_type_code, steps)
# step: (ordinal, action_text, expected_response, mode, target_sec, is_critical, parent_ordinal, branch_condition)
PROCEDURES = [
    (
        "Engine Start — Normal",
        "normal",
        "pre-flight",
        "B737-800",
        [
            (1, "APU — START / RUNNING",                    "APU GEN ON",    "do_verify",          10, True,  None, None),
            (2, "Fuel Control Switch (ENG 1) — RUN",        None,            "do_verify",          5,  True,  None, None),
            (3, "Starter switch ENG 1 — GRD",               None,            "do_verify",          5,  True,  None, None),
            (4, "N2 > 25% — confirm",                       "N2 RISING",     "challenge_response", 15, True,  None, None),
            (5, "ENG START switch — OFF when N1 stable",    "ENGINE STABLE", "do_verify",          20, True,  None, None),
            (6, "Fuel Control Switch (ENG 2) — RUN",        None,            "do_verify",          5,  True,  None, None),
            (7, "Starter switch ENG 2 — GRD",               None,            "do_verify",          5,  True,  None, None),
            (8, "N2 > 25% ENG 2 — confirm",                 "N2 RISING",     "challenge_response", 15, True,  None, None),
            (9, "ENG START switch ENG 2 — OFF when stable", "ENGINE STABLE", "do_verify",          20, True,  None, None),
        ],
    ),
    (
        "Engine Fire — In Flight",
        "emergency",
        "cruise",
        "B737-800",
        [
            (1,  "Thrust lever (affected engine) — IDLE",     None,                 "do_verify",          5,  True,  None,  None),
            (2,  "Engine master switch — OFF",                 None,                 "do_verify",          5,  True,  None,  None),
            (3,  "Fire warning check",                         "FIRE LIGHT ON/OFF",  "challenge_response", 10, True,  None,  None),
            # branch from step 3: fire persists → step 4; fire extinguished → step 7
            (4,  "Fire extinguisher 1 — DISCHARGE",           None,                 "do_verify",          5,  True,  3, "fire persists"),
            (5,  "Wait 30 seconds",                           "TIMER RUNNING",      "do_verify",          30, False, 3, "fire persists"),
            (6,  "Fire still active?",                        "FIRE LIGHT STATUS",  "challenge_response", 5,  True,  3, "fire persists"),
            (7,  "Configure single-engine ops",               None,                 "do_verify",          10, True,  3, "fire extinguished"),
            (8,  "Fire extinguisher 2 — DISCHARGE",           None,                 "do_verify",          5,  True,  6, "fire persists after bottle 1"),
            (9,  "Declare MAYDAY — divert to nearest field",  None,                 "do_verify",          10, True,  6, "fire persists after bottle 1"),
        ],
    ),
]

SCENARIOS = [
    {
        "scenario_code": "V1-CUT-B737",
        "name":          "V1 Engine Failure — B737-800",
        "scenario_type": "v1_cut",
        "aircraft":      "B737-800",
        "description":   "Engine failure at V1 during takeoff roll. Crew must continue takeoff and execute single-engine departure.",
        "initial_conditions": {
            "airspeed_kts": 0, "altitude_ft": 0, "phase": "takeoff_roll",
            "engine_1": "running", "engine_2": "running",
        },
        "trigger_config": {
            "trigger_at": "V1", "affected_engine": 2,
            "failure_mode": "complete_failure", "warning": "ENG FAIL"
        },
    },
    {
        "scenario_code": "WINDSHEAR-APP-B737",
        "name":          "Windshear Encounter — Approach",
        "scenario_type": "windshear",
        "aircraft":      "B737-800",
        "description":   "Severe windshear at 500 ft AGL on final approach. Crew must execute escape manoeuvre.",
        "initial_conditions": {
            "airspeed_kts": 140, "altitude_ft": 1500, "phase": "approach",
            "flaps": 30, "gear": "down",
        },
        "trigger_config": {
            "trigger_altitude_ft": 500, "wind_shear_fps": -20,
            "warning": "WINDSHEAR WINDSHEAR WINDSHEAR"
        },
    },
    {
        "scenario_code": "TCAS-RA-CRUISE",
        "name":          "TCAS Resolution Advisory — Cruise",
        "scenario_type": "tcas_ra",
        "aircraft":      "B737-800",
        "description":   "TCAS RA issued during cruise. Crew must follow RA and coordinate with ATC.",
        "initial_conditions": {
            "airspeed_kts": 460, "altitude_ft": 35000, "phase": "cruise",
        },
        "trigger_config": {
            "ra_type": "CLIMB", "intruder_alt_ft": 34800,
            "warning": "CLIMB CLIMB NOW"
        },
    },
    {
        "scenario_code": "ENG-FIRE-INFLIGHT-B737",
        "name":          "Engine Fire — In Flight (B737-800)",
        "scenario_type": "engine_fire",
        "aircraft":      "B737-800",
        "description":   "Engine fire warning during cruise at FL350. Crew must execute QRH engine fire procedure.",
        "initial_conditions": {
            "airspeed_kts": 460, "altitude_ft": 35000, "phase": "cruise",
            "engine_1": "running", "engine_2": "running",
        },
        "trigger_config": {
            "affected_engine": 1, "fire_duration_seconds": 30,
            "warning": "ENG FIRE 1"
        },
    },
]

COMPETENCIES = [
    ("PROC-ADH",  "Procedural Adherence",      "Technical",   "Follows SOPs and checklists without deviation"),
    ("SYS-KNW",   "Systems Knowledge",          "Technical",   "Demonstrates understanding of aircraft systems"),
    ("DECISION",  "Decision Making",            "Cognitive",   "Makes timely and correct decisions under pressure"),
    ("CRM",       "Crew Resource Management",   "Non-Technical", "Effectively coordinates with crew and ATC"),
    ("SIT-AWR",   "Situational Awareness",      "Cognitive",   "Maintains awareness of aircraft state and environment"),
    ("WORKLOAD",  "Workload Management",        "Non-Technical", "Prioritises tasks and manages workload under stress"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create(db: AsyncSession, model, filter_kwargs: dict, create_kwargs: dict | None = None):
    stmt = select(model)
    for k, v in filter_kwargs.items():
        stmt = stmt.where(getattr(model, k) == v)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing, False
    obj = model(**(create_kwargs or filter_kwargs))
    db.add(obj)
    await db.flush()
    return obj, True


# ---------------------------------------------------------------------------
# Main seed
# ---------------------------------------------------------------------------

async def seed():
    print(f"Connecting to: {settings.DATABASE_URL[:60]}…")
    async with AsyncSession_() as db:
        async with db.begin():

            # ── Roles ──────────────────────────────────────────────────────
            role_map: dict[str, Role] = {}
            for name, desc in ROLES:
                r, created = await _get_or_create(db, Role, {"name": name}, {"name": name, "description": desc})
                role_map[name] = r
                if created:
                    print(f"  + role: {name}")

            # ── Permissions ────────────────────────────────────────────────
            perm_map: dict[tuple[str, str], Permission] = {}
            for resource, action in PERMISSIONS:
                p, created = await _get_or_create(
                    db, Permission, {"resource": resource, "action": action},
                    {"resource": resource, "action": action,
                     "description": f"{action} on {resource}"},
                )
                perm_map[(resource, action)] = p
                if created:
                    print(f"  + permission: {resource}:{action}")

            # ── Role ↔ Permission mapping ──────────────────────────────────
            for role_name, perms in ROLE_PERMISSIONS.items():
                role = role_map[role_name]
                for resource, action in perms:
                    perm = perm_map.get((resource, action))
                    if not perm:
                        continue
                    existing = (await db.execute(
                        select(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm.id,
                        )
                    )).scalar_one_or_none()
                    if not existing:
                        db.add(RolePermission(role_id=role.id, permission_id=perm.id))

            # ── Aircraft ───────────────────────────────────────────────────
            aircraft_map: dict[str, Aircraft] = {}
            for type_code, manufacturer, display_name in AIRCRAFT:
                ac, created = await _get_or_create(
                    db, Aircraft, {"type_code": type_code},
                    {"type_code": type_code, "manufacturer": manufacturer,
                     "display_name": display_name, "active": True},
                )
                aircraft_map[type_code] = ac
                if created:
                    print(f"  + aircraft: {type_code}")

            # ── Users ──────────────────────────────────────────────────────
            user_map: dict[str, User] = {}
            for email, full_name, employee_id, password, role_name in USERS:
                u, created = await _get_or_create(
                    db, User, {"email": email},
                    {
                        "email":         email,
                        "full_name":     full_name,
                        "employee_id":   employee_id,
                        "password_hash": hash_password(password),
                    },
                )
                user_map[email] = u
                if created:
                    print(f"  + user: {email}  ({role_name})")

                # Assign role
                role = role_map[role_name]
                existing_ur = (await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == u.id, UserRole.role_id == role.id
                    )
                )).scalar_one_or_none()
                if not existing_ur:
                    db.add(UserRole(user_id=u.id, role_id=role.id))

            # ── Checklists ─────────────────────────────────────────────────
            for cl_name, phase, ac_code, items in CHECKLISTS:
                cl, created = await _get_or_create(
                    db, Checklist, {"name": cl_name},
                    {"name": cl_name, "phase": phase,
                     "aircraft_id": aircraft_map[ac_code].id},
                )
                if created:
                    print(f"  + checklist: {cl_name}")
                    for ordinal, challenge, exp_resp, mode, target_sec, is_critical in items:
                        db.add(ChecklistItem(
                            checklist_id=cl.id,
                            ordinal=ordinal,
                            challenge=challenge,
                            expected_response=exp_resp,
                            mode=mode,
                            target_time_seconds=target_sec,
                            is_critical=is_critical,
                        ))
                    await db.flush()

            # ── Procedures ─────────────────────────────────────────────────
            proc_map: dict[str, Procedure] = {}
            for proc_name, proc_type, phase, ac_code, steps in PROCEDURES:
                proc, created = await _get_or_create(
                    db, Procedure, {"name": proc_name},
                    {
                        "name":           proc_name,
                        "procedure_type": proc_type,
                        "phase":          phase,
                        "aircraft_id":    aircraft_map[ac_code].id,
                    },
                )
                proc_map[proc_name] = proc
                if created:
                    print(f"  + procedure: {proc_name}")
                    # First pass: create all steps, track ordinal → step id
                    step_by_ordinal: dict[int, ProcedureStep] = {}
                    for ordinal, action, exp_resp, mode, target_sec, is_critical, _, _ in steps:
                        s = ProcedureStep(
                            procedure_id=proc.id,
                            ordinal=ordinal,
                            action_text=action,
                            expected_response=exp_resp,
                            mode=mode,
                            target_time_seconds=target_sec,
                            is_critical=is_critical,
                        )
                        db.add(s)
                        await db.flush()
                        step_by_ordinal[ordinal] = s

                    # Second pass: wire parent_step_id for branching steps
                    for ordinal, _, _, _, _, _, parent_ordinal, branch_cond in steps:
                        if parent_ordinal is not None:
                            child = step_by_ordinal[ordinal]
                            child.parent_step_id = step_by_ordinal[parent_ordinal].id
                            child.branch_condition = branch_cond
                    await db.flush()

            # ── Scenarios ──────────────────────────────────────────────────
            for sc in SCENARIOS:
                ac = aircraft_map.get(sc["aircraft"])
                _, created = await _get_or_create(
                    db, Scenario, {"scenario_code": sc["scenario_code"]},
                    {
                        "scenario_code":      sc["scenario_code"],
                        "name":               sc["name"],
                        "scenario_type":      sc["scenario_type"],
                        "aircraft_id":        ac.id if ac else None,
                        "description":        sc["description"],
                        "initial_conditions": sc["initial_conditions"],
                        "trigger_config":     sc["trigger_config"],
                        "procedure_id":       proc_map.get("Engine Fire — In Flight", Procedure()).id
                                              if sc["scenario_type"] == "engine_fire" else None,
                    },
                )
                if created:
                    print(f"  + scenario: {sc['name']}")

            # ── Competencies ───────────────────────────────────────────────
            for code, name, category, description in COMPETENCIES:
                _, created = await _get_or_create(
                    db, Competency, {"code": code},
                    {"code": code, "name": name, "category": category, "description": description},
                )
                if created:
                    print(f"  + competency: {code} — {name}")

            # ── Rubric ─────────────────────────────────────────────────────
            rubric_name = "Standard Procedure Evaluation"
            _, created = await _get_or_create(
                db, Rubric, {"name": rubric_name},
                {
                    "name": rubric_name,
                    "criteria": {
                        "procedural_compliance": {"weight": 0.40, "max": 10},
                        "systems_knowledge":     {"weight": 0.25, "max": 10},
                        "decision_making":       {"weight": 0.20, "max": 10},
                        "crm":                   {"weight": 0.15, "max": 10},
                    },
                    "max_score": Decimal("100.00"),
                },
            )
            if created:
                print(f"  + rubric: {rubric_name}")

    print("\nSeed complete.\n")
    print("=" * 54)
    print("  LOGIN CREDENTIALS")
    print("=" * 54)
    print(f"  {'Role':<12} {'Email':<35} Password")
    print("-" * 54)
    for email, _, _, password, role_name in USERS:
        print(f"  {role_name:<12} {email:<35} {password}")
    print("=" * 54)


if __name__ == "__main__":
    asyncio.run(seed())
