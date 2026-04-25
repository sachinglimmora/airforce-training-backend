tags_metadata = [
    {
        "name": "auth",
        "description": (
            "Authentication endpoints. All clients start here.\n\n"
            "**Flow:** `POST /auth/login` → receive `access_token` (15 min) + `refresh_token` (7 days) → "
            "attach `Authorization: Bearer <access_token>` to every subsequent request → "
            "call `POST /auth/refresh` before expiry → `POST /auth/logout` to revoke.\n\n"
            "Tokens are RS256-signed JWTs. Public key available at `GET /auth/.well-known/jwks.json`."
        ),
    },
    {
        "name": "users",
        "description": (
            "User management and role-based access control (RBAC).\n\n"
            "Roles: **trainee**, **instructor**, **evaluator**, **admin**. "
            "Admins can create users and assign roles; instructors can read their trainees. "
            "Soft-delete via `deleted_at` — records are never physically removed."
        ),
    },
    {
        "name": "content",
        "description": (
            "Content ingestion pipeline for flight operations documents.\n\n"
            "Supported types: **FCOM**, **QRH**, **AMM**, **SOP**, **syllabus**.\n\n"
            "Upload is asynchronous (Celery). After upload the source enters `parsing` status; "
            "poll `GET /content/sources/{id}` or subscribe to the job WebSocket (Phase 2).\n\n"
            "**RAG contract:** `GET /content/sources/{id}/tree` returns the parsed section hierarchy "
            "that Shreyansh's RAG chunker consumes. Every section carries a stable `citation_key` "
            "(e.g. `B737-FCOM-3.2.1`) used by the AI gateway for citation injection."
        ),
    },
    {
        "name": "ai",
        "description": (
            "AI / LLM gateway — all LLM calls must go through here. "
            "No direct provider calls from the frontend.\n\n"
            "**`POST /ai/complete`** accepts a message array plus optional `context_citations` "
            "(citation keys resolved to section text and injected into the prompt server-side). "
            "PII filter runs before every provider call. Responses are cached for 24 h when "
            "`temperature < 0.3`.\n\n"
            "**Provider fallback:** auto → Gemini first, OpenAI on failure, 502 if both down.\n\n"
            "**Rate limits:** 60 req/min (trainee) · 200 req/min (instructor) · 2 000 req/min (global)."
        ),
    },
    {
        "name": "checklists",
        "description": (
            "Checklist engine supporting three execution modes:\n\n"
            "- **challenge_response** — caller reads challenge, respondent reads response\n"
            "- **read_do** — trainee reads and performs each item\n"
            "- **do_verify** — trainee does the action, verifier confirms\n\n"
            "Session flow: `POST /{id}/sessions` → loop `POST /sessions/{sid}/items/{item_id}/call` "
            "then `POST /sessions/{sid}/items/{item_id}/respond` → `POST /sessions/{sid}/complete`.\n\n"
            "Scoring (computed on complete): items responded / total, out-of-order count, "
            "timing violations vs `target_time_seconds`, critical-item misses."
        ),
    },
    {
        "name": "procedures",
        "description": (
            "Normal and emergency procedure execution engine.\n\n"
            "Procedures are directed acyclic graphs of `ProcedureStep` nodes. "
            "Emergency procedures use `parent_step_id` + `branch_condition` to model QRH branch logic.\n\n"
            "`GET /{id}/flow` returns the full DAG for frontend rendering.\n\n"
            "Deviation detection runs on `POST /sessions/{sid}/steps/{step_id}/complete`: "
            "timing violations (vs `target_time_seconds`) and skipped critical steps are "
            "recorded to the `deviations` table."
        ),
    },
    {
        "name": "scenarios",
        "description": (
            "High-risk scenario engine — pre-defined triggers for:\n\n"
            "- **v1_cut** — engine failure at V1 during takeoff roll\n"
            "- **windshear** — severe windshear encounter on approach\n"
            "- **tcas_ra** — TCAS Resolution Advisory in cruise\n"
            "- **engine_fire** — in-flight engine fire QRH execution\n\n"
            "The backend owns **decision logic and scoring**; visuals live in the frontend (Harish) "
            "and VR runtime (Subhash).\n\n"
            "Session flow: `POST /{id}/sessions` → `POST /sessions/{sid}/trigger` (fires the event) "
            "→ loop `POST /sessions/{sid}/action` → `GET /sessions/{sid}/result`."
        ),
    },
    {
        "name": "simulations",
        "description": (
            "Frontend-compatibility alias for the scenarios engine. "
            "All paths mirror `/scenarios` — prefer `/scenarios` for new integrations."
        ),
    },
    {
        "name": "analytics",
        "description": (
            "Analytics and procedural compliance reporting.\n\n"
            "- **Deviations** — step-level timing and sequence deviations for a session\n"
            "- **Trainee progression** — competency evidence trend over time\n"
            "- **Trainee summary** — aggregated session / completion stats\n"
            "- **Cohort summary** — instructor-level view across a group of trainees\n"
            "- **Compliance report** — organisation-wide procedural compliance"
        ),
    },
    {
        "name": "competency",
        "description": (
            "Competency tracking, evaluation rubrics, and graded evaluations.\n\n"
            "**Competency evidence** is recorded per session and per competency code "
            "(e.g. `PROC-ADH`, `CRM`, `DECISION`).\n\n"
            "**Rubrics** define weighted criteria with max scores. "
            "Instructors and evaluators submit `Evaluation` records against a rubric "
            "after each assessed session."
        ),
    },
    {
        "name": "vr",
        "description": (
            "VR telemetry ingestion — **Subhash ↔ Sachin contract**.\n\n"
            "Session flow:\n"
            "1. `POST /vr/sessions` — register device + link to a `training_session`\n"
            "2. `POST /vr/sessions/{vid}/events` — batch ingest up to 500 events per call "
            "(head pose, controller state, interaction targets). Client-generated UUIDv7 `id` "
            "enables idempotent retry.\n"
            "3. `POST /vr/sessions/{vid}/end` — mark session ended, record avg frame rate.\n\n"
            "Events are stored in `vr_telemetry_events` (append-only; partition by month at scale)."
        ),
    },
    {
        "name": "audit",
        "description": (
            "Tamper-evident audit log — every entry is hash-chained (SHA-256).\n\n"
            "**Actions logged:** auth events, user CRUD, content approvals, AI queries, "
            "data access, config changes, session evaluations.\n\n"
            "`GET /audit/logs/verify` recomputes the chain and returns `integrity: ok | compromised`.\n\n"
            "Access restricted to `audit:read` (admin in Phase 1)."
        ),
    },
    {
        "name": "assets",
        "description": (
            "3D asset catalogue — glTF / glb files for cockpit, exterior, subsystem, and environment models.\n\n"
            "Files are stored in MinIO (S3-compatible). `GET /assets/{id}/download` returns a "
            "**presigned URL** valid for 15 minutes — the download bypasses the app server entirely. "
            "Harish (frontend) and Subhash (VR) both consume this endpoint.\n\n"
            "Filter by `aircraft_id`, `type` (`exterior | cockpit | subsystem | environment`), "
            "and `fidelity` (`low | medium | high`)."
        ),
    },
    {
        "name": "training",
        "description": (
            "Training catalogue — courses and learning modules.\n\n"
            "Courses group related modules (e.g. *Jet Engine Systems* → Turbine Blade Inspection, "
            "Fuel Nozzle Maintenance). Modules track completion state per trainee.\n\n"
            "Instructors can upload or trigger generation of module videos."
        ),
    },
    {
        "name": "instructor",
        "description": (
            "Instructor-specific views — trainee oversight, session management, "
            "scenario authoring, and analytics dashboards."
        ),
    },
    {
        "name": "progress",
        "description": (
            "Trainee progress aggregation — overall readiness score, competency levels, "
            "simulation hours, and recent activity feed."
        ),
    },
    {
        "name": "ai-assistant",
        "description": (
            "Conversational AI assistant for trainees. "
            "Wraps `POST /ai/complete` with session-scoped message history. "
            "History is stored server-side and returned on `GET /ai-assistant/history`."
        ),
    },
    {
        "name": "alerts",
        "description": (
            "In-app notification and alert management. "
            "Alerts are created by the system (deviation detected, evaluation submitted, etc.) "
            "and surfaced to the relevant user. "
            "Supports per-alert and bulk read marking."
        ),
    },
    {
        "name": "instructor-videos",
        "description": (
            "Instructor-produced video library. Instructors upload videos and assign them to "
            "specific trainees. Trainees see their assignments via `GET /instructor-videos/my-assignments`."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Platform administration — dashboard KPIs, role management, "
            "audit log access, system health, and AI token/cost analytics."
        ),
    },
    {
        "name": "digital-twin",
        "description": (
            "Aircraft digital twin — live system and component state. "
            "Each aircraft system (engine, hydraulics, electrical, avionics, landing gear, fuel, weapons) "
            "exposes components with health percentages and maintenance schedules."
        ),
    },
    {
        "name": "compatibility",
        "description": (
            "Legacy compatibility shim for older frontend builds. "
            "These endpoints mirror core functionality under alternate paths. "
            "**Prefer the canonical endpoints** for new integrations."
        ),
    },
    {
        "name": "health",
        "description": (
            "Liveness, readiness, version, and Prometheus metrics.\n\n"
            "- `GET /health` — liveness (always 200 if process is alive)\n"
            "- `GET /health/ready` — readiness (checks DB + Redis connectivity)\n"
            "- `GET /version` — build SHA, version string, environment\n"
            "- `GET /metrics` — Prometheus text format (restrict to internal network in production)"
        ),
    },
]
