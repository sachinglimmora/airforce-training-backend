import uuid
from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.content.models import ContentSection, ContentSource

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}

_SAMPLE_ENTRIES = [
    {
        "id": "k-001",
        "title": "Engine Start Procedure — Su-30MKI",
        "summary": "Step-by-step ground start procedure for the AL-31FP turbofan engines, including pre-start checks, ignition sequence, and post-start monitoring.",
        "category": "Procedures",
        "aircraft": "su-30mki",
        "system": "engine",
        "difficulty": "intermediate",
        "tags": ["engine", "startup", "su-30mki", "AL-31FP"],
        "lastUpdated": "2025-01-10T00:00:00Z",
        "content": """## Engine Start Procedure — Su-30MKI AL-31FP

### Pre-Start Checks
1. Confirm fuel quantity — minimum 3,000 kg for engine start
2. Verify hydraulic pressure accumulator charged — 210 ± 5 bar
3. Check oil level sight glass — between MIN and MAX marks
4. Confirm APU running and supplying bleed air

### Ignition Sequence
1. **Left engine first** — rotate left throttle to IDLE gate
2. Monitor N1 — should reach 15% within 10 seconds
3. At N1 ≥ 15%: EGT will start rising — normal up to 650°C during light-off
4. N1 stabilises at 60–65% IDLE — confirm within 45 seconds
5. Repeat sequence for **right engine**

### Post-Start Monitoring
- EGT at idle: 420–460°C
- Oil pressure: 4.5–6.0 kg/cm²
- Hydraulic pressure: 210 bar both systems
- Generator voltage: 115 V AC ± 2 V

### Abort Criteria
- EGT exceeds 730°C during start
- N1 does not reach 15% within 10 s
- Oil pressure below 3 kg/cm² after stabilisation
""",
    },
    {
        "id": "k-002",
        "title": "Hydraulic System Overview — Su-30MKI",
        "summary": "Architecture and operation of the dual-redundant hydraulic system, including system 1 and system 2 pressure management and emergency procedures.",
        "category": "Technical Reference",
        "aircraft": "su-30mki",
        "system": "hydraulics",
        "difficulty": "advanced",
        "tags": ["hydraulics", "su-30mki", "systems", "emergency"],
        "lastUpdated": "2025-01-08T00:00:00Z",
        "content": """## Hydraulic System — Su-30MKI

### System Architecture
The Su-30MKI uses two independent hydraulic systems (System 1 and System 2) operating at **210 bar** nominal pressure.

**System 1 (Primary):**
- Flight controls: elevators, rudders, canards
- Landing gear actuation
- Wheel brakes (primary)

**System 2 (Secondary):**
- Ailerons and spoilers
- Flap actuation
- Canopy seal and emergency
- Wheel brakes (backup)

### Normal Operation
- Both systems maintained at 210 ± 5 bar by engine-driven pumps
- System 1 pump driven by left engine, System 2 by right engine
- Electric backup pump maintains pressure with one engine inoperative

### Emergency — Single System Loss
If System 1 pressure drops below 140 bar:
1. Check left engine RPM — confirm N2 above 60%
2. Select HYDRAULIC BACKUP switch — ON
3. Limit airspeed to 450 kt
4. Avoid aggressive manoeuvres above 3g

### Fluid Specification
- Fluid type: AMG-10 hydraulic oil
- Capacity: 22 litres per system
- Servicing temperature: +15°C to +25°C
""",
    },
    {
        "id": "k-003",
        "title": "N011M BARS Radar — Operating Modes",
        "summary": "Overview of the Phazotron N011M BARS passive electronically scanned array radar, including air-to-air, air-to-ground, and terrain-avoidance modes.",
        "category": "Technical Reference",
        "aircraft": "su-30mki",
        "system": "avionics",
        "difficulty": "advanced",
        "tags": ["radar", "N011M", "BARS", "avionics", "su-30mki"],
        "lastUpdated": "2025-01-05T00:00:00Z",
        "content": """## N011M BARS Radar

### Specifications
- Type: Passive Electronically Scanned Array (PESA)
- Frequency: X-band
- Detection range (air target, RCS 5m²): 140 km (head-on), 60 km (tail-on)
- Simultaneous tracking: 15 targets
- Simultaneous engagement: 4 targets (R-77 missile)

### Air-to-Air Modes
| Mode | Description |
|------|-------------|
| RWS | Range While Search — wide area search |
| TWS | Track While Scan — multi-target tracking |
| STT | Single Target Track — fire-control quality |
| VS | Vertical Scan — close combat acquisition |

### Air-to-Ground Modes
| Mode | Description |
|------|-------------|
| RBM | Real Beam Map — terrain mapping |
| DBS | Doppler Beam Sharpening — enhanced resolution |
| SAR | Synthetic Aperture Radar — high resolution |
| GMT | Ground Moving Target — vehicle tracking |

### Radar BIT
Run BIT from AVIONICS panel before first flight of day:
1. Select RADAR — ON
2. Allow 3-minute warm-up
3. Press BIT — confirm GO indication within 90 seconds
4. Failed BIT: enter fault code in tech log, do not fly
""",
    },
    {
        "id": "k-004",
        "title": "Emergency — Engine Fire In Flight",
        "summary": "Immediate actions and follow-on procedures for an engine fire warning during flight, including shutdown, fire bottle discharge, and diversion.",
        "category": "Emergency Procedures",
        "aircraft": "su-30mki",
        "system": "engine",
        "difficulty": "advanced",
        "tags": ["emergency", "fire", "engine", "QRH", "su-30mki"],
        "lastUpdated": "2025-01-03T00:00:00Z",
        "content": """## Engine Fire — In Flight (Immediate Actions)

> **Memorise these actions. Do not read the checklist until fire is extinguished.**

### Immediate Actions (from memory)
1. **Affected throttle** — IDLE, then OFF
2. **Fire handle** (affected engine) — PULL
3. **Fire bottle 1** — DISCHARGE (press and hold 2 seconds)
4. **FIRE warning light** — should extinguish within 5 seconds

### If Fire Warning Persists After 15 seconds
5. **Fire bottle 2** — DISCHARGE
6. **Declare MAYDAY** — squawk 7700
7. **Divert** — nearest suitable airfield

### Single-Engine Landing Considerations
- Increase final approach speed by +15 kt
- Do not extend speed brakes below 1000 ft AGL
- Plan for longer landing roll — one brake system may be degraded
- Have crash/fire/rescue on standby

### Post-Landing
- Do not taxi — stop on runway
- Evacuate aircraft if smoke continues
- Complete post-fire inspection before next flight
""",
    },
    {
        "id": "k-005",
        "title": "Pre-Flight Inspection Sequence — Su-30MKI",
        "summary": "Standardised walk-around pre-flight inspection covering airframe, engines, control surfaces, and weapons stations.",
        "category": "Checklists",
        "aircraft": "su-30mki",
        "system": "general",
        "difficulty": "beginner",
        "tags": ["pre-flight", "inspection", "walk-around", "su-30mki"],
        "lastUpdated": "2024-12-28T00:00:00Z",
        "content": """## Pre-Flight Walk-Around Inspection

### Starting Position: Nose, Left Side

**Nose Section**
- Pitot tube covers removed — confirm both probes clear
- Radome — no delamination or damage
- Cannon muzzle — cover removed, bore clear

**Left Main Gear**
- Tyre condition — no cuts, inflation correct (16.5 kg/cm²)
- Brake wear indicators — within limits
- Gear door hydraulic lines — no leaks

**Left Engine Intake**
- FOD inspection — no debris, birds, or ingested objects
- Intake ramp actuators — no hydraulic seepage
- Fan blade inspection — first stage visible blades, no nicks

**Left Wingtip / Weapons**
- AAM pylon secure — all pins installed if weapons loaded
- Wingtip ECM pod — no damage

**Tail Section**
- Thrust vectoring nozzle — paddles symmetric at neutral
- Tail hook (if fitted) — stowed and locked
- Engine exhaust — no oil streaks or combustion residue

**Right Side** — Mirror of left side checks

### Completion
Sign maintenance log Form 700 certifying aircraft serviceable before boarding.
""",
    },
    {
        "id": "k-006",
        "title": "TCAS RA Response Procedures",
        "summary": "Correct crew response to Traffic Collision Avoidance System Resolution Advisories, including climb, descend, and crossing manoeuvres.",
        "category": "Procedures",
        "aircraft": "general",
        "system": "avionics",
        "difficulty": "intermediate",
        "tags": ["TCAS", "collision avoidance", "RA", "general"],
        "lastUpdated": "2024-12-20T00:00:00Z",
        "content": """## TCAS Resolution Advisory (RA) Response

### Immediate Response (within 5 seconds of RA)
1. **Disengage autopilot** — immediately
2. **Respond to RA** — do not wait for ATC clearance
3. **Fly to green arc** on vertical speed indicator
4. **Advise ATC** — "TCAS RA" as soon as practical

### RA Types and Required Actions
| RA Display | Required Action |
|------------|----------------|
| CLIMB | Increase VSI to +1500 ft/min minimum |
| DESCEND | Increase VSI to −1500 ft/min minimum |
| MAINTAIN CLIMB | Continue climb, do not level off |
| LEVEL OFF | Reduce VSI toward 0 |
| CROSSING CLIMB | Climb through threat altitude |

### Priority
- TCAS RA **overrides** ATC instruction
- Inform ATC: "Unable, TCAS RA"
- Resume ATC clearance only after "CLEAR OF CONFLICT"

### After the RA
- Return to assigned clearance
- Report to ATC: "Returning to [clearance], previous TCAS RA"
- Complete airprox report if applicable
""",
    },
]

_CATEGORIES = sorted({e["category"] for e in _SAMPLE_ENTRIES})
_SYSTEMS = sorted({e["system"] for e in _SAMPLE_ENTRIES})


def _entry_from_db(source: ContentSource, section: ContentSection | None) -> dict:
    return {
        "id": str(source.id),
        "title": source.title,
        "summary": section.content_markdown[:200] if section and section.content_markdown else source.title,
        "category": source.source_type.upper(),
        "aircraft": "general",
        "system": "general",
        "difficulty": "intermediate",
        "tags": [source.source_type],
        "lastUpdated": source.updated_at.isoformat(),
        "content": section.content_markdown if section else "",
    }


@router.get(
    "",
    response_model=dict,
    summary="List knowledge base entries",
    responses={**_401},
    operation_id="knowledge_list",
)
async def list_knowledge(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    system: str | None = Query(None),
    difficulty: str | None = Query(None),
):
    # Try DB content first
    db_result = await db.execute(select(ContentSource).where(ContentSource.status == "approved"))
    sources = db_result.scalars().all()

    if sources:
        entries = [_entry_from_db(src, None) for src in sources]
    else:
        entries = list(_SAMPLE_ENTRIES)

    if system:
        entries = [e for e in entries if e["system"] == system]
    if difficulty:
        entries = [e for e in entries if e["difficulty"] == difficulty]

    categories = sorted({e["category"] for e in entries})
    systems = sorted({e["system"] for e in entries})

    return {"data": {"entries": entries, "categories": categories, "systems": systems}}


@router.post(
    "/search",
    response_model=dict,
    summary="Search knowledge base",
    responses={**_401},
    operation_id="knowledge_search",
)
async def search_knowledge(
    body: dict,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    query = (body.get("query") or "").lower().strip()
    if not query:
        return {"data": {"results": []}}

    # Try DB content sections with text search
    db_result = await db.execute(
        select(ContentSection).where(
            or_(
                ContentSection.title.ilike(f"%{query}%"),
                ContentSection.content_markdown.ilike(f"%{query}%"),
            )
        ).limit(10)
    )
    db_sections = db_result.scalars().all()

    if db_sections:
        results = [
            {
                "entry": {
                    "id": str(s.id),
                    "title": s.title,
                    "summary": (s.content_markdown or "")[:200],
                    "category": "Technical Reference",
                    "aircraft": "general",
                    "system": "general",
                    "difficulty": "intermediate",
                    "tags": [],
                    "lastUpdated": "",
                },
                "score": 1.0,
                "contextMatches": [s.title],
            }
            for s in db_sections
        ]
    else:
        # Search sample entries
        terms = query.split()
        results = []
        for entry in _SAMPLE_ENTRIES:
            searchable = f"{entry['title']} {entry['summary']} {' '.join(entry['tags'])}".lower()
            matches = sum(1 for t in terms if t in searchable)
            if matches > 0:
                context = [
                    tag for tag in entry["tags"] if any(t in tag for t in terms)
                ] or [entry["category"]]
                results.append(
                    {
                        "entry": {k: v for k, v in entry.items() if k != "content"},
                        "score": round(matches / len(terms), 2),
                        "contextMatches": context[:3],
                    }
                )
        results.sort(key=lambda r: r["score"], reverse=True)

    return {"data": {"results": results}}


@router.get(
    "/{entry_id}",
    response_model=dict,
    summary="Get knowledge article",
    responses={**_401},
    operation_id="knowledge_get",
)
async def get_knowledge_entry(
    entry_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Check sample entries first
    for entry in _SAMPLE_ENTRIES:
        if entry["id"] == entry_id:
            return {"data": entry}

    # Try DB by UUID
    try:
        uid = uuid.UUID(entry_id)
        section = (
            await db.execute(select(ContentSection).where(ContentSection.id == uid))
        ).scalar_one_or_none()
        if section:
            return {
                "data": {
                    "id": str(section.id),
                    "title": section.title,
                    "summary": (section.content_markdown or "")[:200],
                    "content": section.content_markdown or "",
                    "category": "Technical Reference",
                    "aircraft": "general",
                    "system": "general",
                    "difficulty": "intermediate",
                    "tags": [],
                    "lastUpdated": "",
                }
            }
    except ValueError:
        pass

    from app.core.exceptions import NotFound
    raise NotFound("Knowledge entry")


@router.post(
    "/generate",
    response_model=dict,
    summary="AI-generate a knowledge article",
    responses={**_401},
    operation_id="knowledge_generate",
)
async def generate_knowledge(
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    topic = body.get("topic", "")
    aircraft = body.get("aircraft", "general")
    system = body.get("system", "general")

    try:
        from app.modules.ai.schemas import CompletionRequest, MessageIn
        from app.modules.ai.service import AIService

        prompt = (
            f"Generate a comprehensive technical knowledge article for airforce pilots about: {topic}. "
            f"Aircraft: {aircraft}. System: {system}. "
            "Format in Markdown with sections: Overview, Key Concepts, Procedures/Steps, "
            "Important Limits/Numbers, and Common Errors to Avoid. "
            "Keep it concise but technically accurate. Include specific numbers where relevant."
        )
        svc = AIService(db)
        req = CompletionRequest(
            messages=[MessageIn(role="user", content=prompt)],
            temperature=0.4,
            max_tokens=1200,
        )
        result = await svc.complete(req, str(current_user.id))
        content = result.get("response", "")
    except Exception:
        content = f"## {topic}\n\nArticle content for {topic} ({aircraft} — {system}).\n\nThis article is being generated. Please check back shortly."

    entry = {
        "id": f"gen-{uuid.uuid4().hex[:8]}",
        "title": topic or f"{system.title()} — {aircraft.upper()}",
        "summary": f"AI-generated article on {topic}",
        "category": "Technical Reference",
        "aircraft": aircraft,
        "system": system,
        "difficulty": "intermediate",
        "tags": [system, aircraft, "ai-generated"],
        "lastUpdated": "",
        "content": content,
    }
    return {"data": entry}
