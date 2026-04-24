# Glimmora Aegis Aerospace — Backend API Documentation

**Owner:** Sachin (Backend)
**Phase:** 1 — Foundation
**Version:** 1.0.0 (Draft)
**Last updated:** 2026-04-21

---

## Table of Contents

1. [Overview](#1-overview)
2. [Tech Stack](#2-tech-stack)
3. [Architecture](#3-architecture)
4. [Project Structure](#4-project-structure)
5. [Database Schema](#5-database-schema)
6. [Authentication & Authorization](#6-authentication--authorization)
7. [API Conventions](#7-api-conventions)
8. [API Endpoints](#8-api-endpoints)
   - [8.1 Auth](#81-auth)
   - [8.2 Users & RBAC](#82-users--rbac)
   - [8.3 Content Ingestion](#83-content-ingestion)
   - [8.4 AI / LLM Gateway](#84-ai--llm-gateway)
   - [8.5 Checklist Engine](#85-checklist-engine)
   - [8.6 Procedures (Normal & Emergency)](#86-procedures-normal--emergency)
   - [8.7 High-Risk Scenarios](#87-high-risk-scenarios)
   - [8.8 Analytics & Compliance](#88-analytics--compliance)
   - [8.9 Competency & Evaluation](#89-competency--evaluation)
   - [8.10 VR Telemetry Ingestion](#810-vr-telemetry-ingestion)
   - [8.11 Audit Log](#811-audit-log)
   - [8.12 Assets](#812-assets)
   - [8.13 Health & Ops](#813-health--ops)
9. [AI Integration Layer](#9-ai-integration-layer)
10. [Security](#10-security)
11. [Deployment & DevOps](#11-deployment--devops)
12. [Cross-Team Contracts](#12-cross-team-contracts)
13. [Error Codes](#13-error-codes)
14. [Open Questions](#14-open-questions)

---

## 1. Overview

This document specifies the backend services for Phase 1 of the Glimmora Aegis Aerospace training platform. It covers every API, data model, and subsystem that Sachin owns, along with the integration contracts that Harish (frontend), Shreyansh (RAG/AI assistants), and Subhash (VR) depend on.

**Phase 1 scope (backend):** platform core, authentication, content ingestion, AI gateway to Gemini/OpenAI, training engines (checklist, procedures, scenarios), analytics, VR telemetry ingestion, and audit logging.

**Not in scope for Phase 1:** OwnLLM (sovereign offline model, Phase 2+), multi-base deployment (Phase 3), text-to-video generation (Phase 4).

---

## 2. Tech Stack

| Layer                 | Choice                                    | Rationale                                                                  |
| --------------------- | ----------------------------------------- | -------------------------------------------------------------------------- |
| Language              | Python 3.11+                              | Native SDKs for Gemini, OpenAI, pgvector; aligns with Shreyansh's RAG work |
| Framework             | FastAPI                                   | Async, auto-generates OpenAPI spec (Harish consumes), Pydantic validation  |
| ASGI server           | Uvicorn (behind Gunicorn workers in prod) | Standard FastAPI deployment                                                |
| Database              | PostgreSQL 16                             | Relational core + `pgvector` extension for RAG embeddings (Shreyansh)      |
| Cache / session store | Redis 7                                   | Response cache, rate limit counters, session blacklist                     |
| ORM                   | SQLAlchemy 2.x (async) + Alembic          | Migrations, async queries                                                  |
| Validation            | Pydantic v2                               | Request/response schemas, config management                                |
| Auth                  | JWT (PyJWT) + bcrypt                      | Stateless access tokens, refresh token rotation                            |
| Search                | Meilisearch                               | Full-text search over ingested manuals (P1)                                |
| Object storage        | MinIO (S3-compatible)                     | Training assets, glTF files, ingested source PDFs                          |
| Task queue            | Celery + Redis broker                     | Content ingestion, embedding jobs (handoff to Shreyansh)                   |
| Container             | Docker + Docker Compose                   | Local dev + staging                                                        |
| CI/CD                 | GitHub Actions                            | Build, test, lint, container publish                                       |
| Observability         | structlog + OpenTelemetry                 | JSON logs, trace IDs                                                       |
| Testing               | pytest + pytest-asyncio + httpx           | Unit, integration, API tests                                               |

### Key Python dependencies

```
fastapi>=0.110
uvicorn[standard]>=0.29
gunicorn>=21.2
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
pydantic>=2.6
pydantic-settings>=2.2
pyjwt[crypto]>=2.8
bcrypt>=4.1
redis>=5.0
celery>=5.3
google-generativeai>=0.5
openai>=1.20
httpx>=0.27
structlog>=24.1
python-multipart>=0.0.9
meilisearch-python-async>=1.8
```

---

## 3. Architecture

### 3.1 Style

**Modular monolith** — one deployable FastAPI application, organized into clean domain modules with explicit boundaries. This is a deliberate choice for Phase 1:

- One backend engineer, tight timeline
- Modules can be split into separate services later without rewriting business logic
- Shared database and auth, which simplifies RBAC and audit logging
- Horizontal scaling via Gunicorn workers and Redis-backed session state

**Extraction candidates** for Phase 2 if load demands it: `ai-gateway`, `ingestion-worker`, `telemetry-ingestion`.

### 3.2 High-level flow

```
┌──────────┐   ┌──────────┐   ┌─────────────┐
│ Frontend │   │   VR     │   │  Shreyansh  │
│ (Harish) │   │ (Subhash)│   │  RAG svc    │
└────┬─────┘   └────┬─────┘   └──────┬──────┘
     │              │                 │
     └──────┬───────┴────────┬────────┘
            │                │
     ┌──────▼────────────────▼──────┐
     │      API Gateway (FastAPI)    │
     │  - Auth middleware (JWT)      │
     │  - Rate limit (Redis)         │
     │  - Audit middleware           │
     │  - Request validation         │
     └──────┬────────────────────────┘
            │
  ┌─────────┼─────────┬──────────┬──────────┬──────────┐
  │         │         │          │          │          │
┌─▼──┐  ┌───▼──┐  ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐
│Auth│  │Users │  │Content │ │Training│ │Analytics│ │  AI   │
│    │  │ RBAC │  │Ingest  │ │Engines │ │         │ │Gateway│
└─┬──┘  └──┬───┘  └───┬────┘ └───┬────┘ └────┬────┘ └───┬───┘
  │        │          │          │           │          │
  └────────┴──────────┼──────────┴───────────┘          │
                      │                                 │
              ┌───────▼───────┐                 ┌───────▼───────┐
              │  PostgreSQL   │                 │ Gemini/OpenAI │
              │   + pgvector  │                 │  (PII-filtered)│
              └───────────────┘                 └───────────────┘
                      │
              ┌───────▼───────┐     ┌──────────────┐     ┌─────────┐
              │     Redis     │     │ Meilisearch  │     │  MinIO  │
              │ (cache/queue) │     │    (P1)      │     │ (assets)│
              └───────────────┘     └──────────────┘     └─────────┘
```

### 3.3 Module boundaries

Every module exposes its own router and owns its own SQLAlchemy models. Modules communicate through **service classes**, never by importing each other's internal helpers. This is what makes future extraction cheap.

---

## 4. Project Structure

```
aegis-backend/
├── alembic/
│   ├── versions/
│   └── env.py
├── app/
│   ├── main.py                      # FastAPI app factory, middleware wiring
│   ├── config.py                    # Pydantic Settings (env vars)
│   ├── database.py                  # Async engine, session factory
│   ├── middleware/
│   │   ├── auth.py                  # JWT validation
│   │   ├── rbac.py                  # Permission checks
│   │   ├── audit.py                 # Audit logging
│   │   ├── rate_limit.py            # Redis-backed limiter
│   │   └── error_handler.py         # Global exception -> JSON
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   ├── schemas.py           # Pydantic DTOs
│   │   │   └── models.py            # SQLAlchemy ORM
│   │   ├── users/
│   │   ├── content/                 # FCOM/QRH/AMM/SOP/syllabus parsers
│   │   │   ├── parsers/
│   │   │   │   ├── fcom.py
│   │   │   │   ├── qrh.py
│   │   │   │   ├── amm.py
│   │   │   │   ├── sop.py
│   │   │   │   └── syllabus.py
│   │   ├── ai/
│   │   │   ├── providers/
│   │   │   │   ├── base.py          # Abstract LLMProvider (Ira owns interface)
│   │   │   │   ├── gemini.py
│   │   │   │   └── openai.py
│   │   │   ├── cache.py
│   │   │   ├── pii_filter.py        # Ira owns policy, Sachin enforces
│   │   │   └── fallback.py
│   │   ├── checklist/
│   │   ├── procedures/
│   │   ├── scenarios/               # V1 cut, windshear, TCAS RA, engine fire
│   │   ├── analytics/
│   │   ├── competency/
│   │   ├── evaluation/              # Rubrics & grading
│   │   ├── vr_telemetry/
│   │   ├── audit/
│   │   └── assets/
│   ├── core/
│   │   ├── security.py              # bcrypt, JWT helpers
│   │   ├── permissions.py           # RBAC decorators
│   │   └── exceptions.py
│   └── openapi_tags.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
│   ├── seed_db.py
│   └── rotate_api_keys.py
├── docker/
│   ├── Dockerfile
│   └── entrypoint.sh
├── docker-compose.yml
├── docker-compose.override.yml      # local dev overrides
├── .github/workflows/
│   ├── ci.yml
│   └── deploy.yml
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 5. Database Schema

All tables use UUID primary keys (`uuid_generate_v4()`), `created_at` and `updated_at` timestamps with timezone, and soft-delete via `deleted_at` where appropriate.

> **Note:** Ira owns the final ERD. The schema below is Sachin's working proposal, aligned with the Phase 1 feature breakdown. Lock it with Ira before running migrations.

### 5.1 Identity & access

**users**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | CITEXT UNIQUE NOT NULL | Case-insensitive |
| password_hash | VARCHAR(255) NOT NULL | bcrypt, cost 12 |
| full_name | VARCHAR(200) NOT NULL | |
| employee_id | VARCHAR(64) UNIQUE | Organization ID |
| status | ENUM('active','suspended','locked') | Default 'active' |
| last_login_at | TIMESTAMPTZ | |
| failed_login_count | INT DEFAULT 0 | |
| mfa_enabled | BOOLEAN DEFAULT FALSE | Phase 2 |
| created_at, updated_at, deleted_at | TIMESTAMPTZ | |

**roles**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(64) UNIQUE | `trainee`, `instructor`, `evaluator`, `admin` |
| description | TEXT | |

**permissions**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| resource | VARCHAR(64) | e.g., `content`, `scenario`, `user` |
| action | VARCHAR(32) | `create`, `read`, `update`, `delete`, `approve`, `execute` |
| description | TEXT | |
| UNIQUE (resource, action) | | |

**role_permissions** (M:M)
| Column | Type |
|---|---|
| role_id | UUID FK |
| permission_id | UUID FK |
| PK (role_id, permission_id) | |

**user_roles** (M:M)
| Column | Type |
|---|---|
| user_id | UUID FK |
| role_id | UUID FK |
| assigned_by | UUID FK users |
| assigned_at | TIMESTAMPTZ |
| PK (user_id, role_id) | |

**refresh_tokens**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| token_hash | VARCHAR(255) | SHA-256 of token (not the token itself) |
| expires_at | TIMESTAMPTZ | |
| revoked_at | TIMESTAMPTZ | |
| user_agent | VARCHAR(512) | |
| ip_address | INET | |
| created_at | TIMESTAMPTZ | |

### 5.2 Content

**content_sources**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| source_type | ENUM('fcom','qrh','amm','sop','syllabus') | |
| aircraft_id | UUID FK aircraft | Nullable for general SOPs |
| title | VARCHAR(255) | |
| version | VARCHAR(32) | Document revision |
| effective_date | DATE | |
| approved_by | UUID FK users | |
| approved_at | TIMESTAMPTZ | Null = draft |
| status | ENUM('draft','approved','archived') | |
| original_file_url | TEXT | MinIO URL |
| checksum_sha256 | VARCHAR(64) | |

**content_sections**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| source_id | UUID FK content_sources | |
| parent_section_id | UUID FK content_sections | Nullable, self-ref for hierarchy |
| section_number | VARCHAR(32) | e.g., "3.2.1" |
| title | VARCHAR(500) | |
| content_markdown | TEXT | Parsed content |
| page_number | INT | For citation |
| ordinal | INT | Sort order within parent |
| INDEX (source_id, parent_section_id, ordinal) | | |

**content_references** (citation system — **critical for Shreyansh's RAG**)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| source_id | UUID FK | |
| section_id | UUID FK | |
| citation_key | VARCHAR(128) UNIQUE | Stable ID like `B737-FCOM-3.2.1` |
| display_label | VARCHAR(255) | e.g., "FCOM §3.2.1 — Engine Start" |

> Shreyansh's RAG pipeline retrieves chunks by `citation_key`. Every answer the AI produces must cite one. This is the hand-off contract.

### 5.3 Aircraft & digital twin

**aircraft**
| Column | Type |
|---|---|
| id | UUID PK |
| type_code | VARCHAR(16) UNIQUE (e.g., `B737-800`) |
| manufacturer | VARCHAR(128) |
| display_name | VARCHAR(255) |
| active | BOOLEAN |

**assets** (Chinmay's glTF exports; Sachin serves them)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| aircraft_id | UUID FK | |
| asset_type | ENUM('exterior','cockpit','subsystem','environment') | |
| fidelity | ENUM('low','medium','high') | |
| format | VARCHAR(16) | `gltf`, `glb` |
| storage_url | TEXT | MinIO URL |
| file_size_bytes | BIGINT | |
| checksum_sha256 | VARCHAR(64) | |
| version | VARCHAR(32) | |

### 5.4 Training engines

**procedures**
| Column | Type |
|---|---|
| id | UUID PK |
| aircraft_id | UUID FK |
| procedure_type | ENUM('normal','abnormal','emergency') |
| name | VARCHAR(255) |
| phase | VARCHAR(64) (pre-flight, taxi, takeoff, cruise, approach, landing, shutdown) |
| citation_key | VARCHAR(128) FK content_references |

**procedure_steps**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| procedure_id | UUID FK | |
| ordinal | INT | |
| action_text | TEXT | |
| expected_response | TEXT | Nullable |
| mode | ENUM('challenge_response','read_do','do_verify') | |
| target_time_seconds | INT | For timing analytics |
| parent_step_id | UUID FK | For branching (emergency) |
| branch_condition | TEXT | Trigger for this branch |
| is_critical | BOOLEAN | Flag for compliance engine |

**scenarios** (high-risk: V1 cut, windshear, TCAS RA, engine fire)
| Column | Type |
|---|---|
| id | UUID PK |
| scenario_code | VARCHAR(64) UNIQUE |
| name | VARCHAR(255) |
| scenario_type | ENUM('v1_cut','windshear','tcas_ra','engine_fire','custom') |
| aircraft_id | UUID FK |
| initial_conditions | JSONB |
| trigger_config | JSONB |
| procedure_id | UUID FK procedures |

### 5.5 Sessions & analytics

**training_sessions**
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| trainee_id | UUID FK users | |
| instructor_id | UUID FK users | Nullable |
| session_type | ENUM('theory','checklist','procedure','scenario','vr','assessment') | |
| aircraft_id | UUID FK | Nullable |
| procedure_id | UUID FK | Nullable |
| scenario_id | UUID FK | Nullable |
| started_at | TIMESTAMPTZ | |
| ended_at | TIMESTAMPTZ | |
| status | ENUM('in_progress','completed','aborted') | |
| metadata | JSONB | Free-form (VR device, environment, etc.) |

**session_events** (every trainee action)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| session_id | UUID FK | |
| event_type | VARCHAR(64) | `step_completed`, `step_skipped`, `checklist_item_called`, `deviation_detected` |
| step_id | UUID FK procedure_steps | Nullable |
| timestamp | TIMESTAMPTZ | |
| elapsed_ms | INT | Since session start |
| payload | JSONB | |
| INDEX (session_id, timestamp) | | |

**deviations**
| Column | Type |
|---|---|
| id | UUID PK |
| session_id | UUID FK |
| step_id | UUID FK procedure_steps |
| deviation_type | ENUM('skip','out_of_order','timing','wrong_action','incomplete') |
| severity | ENUM('minor','moderate','major','critical') |
| detected_at | TIMESTAMPTZ |
| expected | JSONB |
| actual | JSONB |
| notes | TEXT |

### 5.6 Competency & evaluation

**competencies**
| Column | Type |
|---|---|
| id | UUID PK |
| code | VARCHAR(64) UNIQUE |
| name | VARCHAR(255) |
| category | VARCHAR(64) |
| description | TEXT |

**competency_evidence**
| Column | Type |
|---|---|
| id | UUID PK |
| trainee_id | UUID FK users |
| competency_id | UUID FK |
| session_id | UUID FK |
| score | DECIMAL(5,2) |
| recorded_at | TIMESTAMPTZ |

**rubrics**
| Column | Type |
|---|---|
| id | UUID PK |
| name | VARCHAR(255) |
| procedure_id | UUID FK | Nullable |
| scenario_id | UUID FK | Nullable |
| criteria | JSONB |
| max_score | DECIMAL(5,2) |

**evaluations**
| Column | Type |
|---|---|
| id | UUID PK |
| session_id | UUID FK |
| evaluator_id | UUID FK users |
| rubric_id | UUID FK |
| scores | JSONB |
| total_score | DECIMAL(5,2) |
| grade | ENUM('excellent','satisfactory','needs_improvement','unsatisfactory') |
| comments | TEXT |
| evaluated_at | TIMESTAMPTZ |

### 5.7 VR telemetry (Subhash → Sachin)

**vr_sessions**
| Column | Type |
|---|---|
| id | UUID PK |
| training_session_id | UUID FK training_sessions |
| device_id | VARCHAR(128) |
| device_type | VARCHAR(64) |
| runtime | ENUM('webxr','unity') |
| started_at, ended_at | TIMESTAMPTZ |
| frame_rate_avg | DECIMAL(5,2) |

**vr_telemetry_events** (append-only, high volume — consider partitioning by month)
| Column | Type |
|---|---|
| id | BIGSERIAL PK |
| vr_session_id | UUID FK |
| event_type | VARCHAR(64) |
| timestamp | TIMESTAMPTZ |
| head_pose | JSONB |
| controller_left | JSONB |
| controller_right | JSONB |
| interaction_target | VARCHAR(128) |
| payload | JSONB |
| INDEX (vr_session_id, timestamp) | |

### 5.8 AI & audit

**ai_requests** (every LLM call logged)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| session_id | UUID FK | Nullable |
| provider | ENUM('gemini','openai') | |
| model | VARCHAR(64) | |
| prompt_hash | VARCHAR(64) | SHA-256 for cache lookup |
| prompt_tokens | INT | |
| completion_tokens | INT | |
| latency_ms | INT | |
| cost_usd | DECIMAL(10,6) | |
| cached | BOOLEAN | |
| status | ENUM('success','error','filtered') | |
| citations | JSONB | Array of citation_keys used |
| created_at | TIMESTAMPTZ | |

**ai_response_cache**
| Column | Type |
|---|---|
| prompt_hash | VARCHAR(64) PK |
| provider | VARCHAR(16) |
| model | VARCHAR(64) |
| response | JSONB |
| citations | JSONB |
| created_at | TIMESTAMPTZ |
| expires_at | TIMESTAMPTZ |

**audit_log** (tamper-evident — hash chain)
| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| timestamp | TIMESTAMPTZ | |
| actor_user_id | UUID FK | Nullable for system events |
| actor_ip | INET | |
| action | VARCHAR(64) | `login`, `login_failed`, `data_access`, `ai_query`, `config_change`, `content_approve` |
| resource_type | VARCHAR(64) | |
| resource_id | VARCHAR(128) | |
| outcome | ENUM('success','denied','error') | |
| metadata | JSONB | |
| prev_hash | VARCHAR(64) | SHA-256 of previous row |
| row_hash | VARCHAR(64) | SHA-256 of this row + prev_hash |

---

## 6. Authentication & Authorization

### 6.1 Authentication flow

1. **Login** — `POST /api/v1/auth/login` with email + password. Server validates bcrypt, issues **access token** (JWT, 15 min) + **refresh token** (opaque, 7 days, stored hashed server-side).
2. **Access** — client sends `Authorization: Bearer <access_token>` on every request. Middleware verifies signature, expiry, and revocation.
3. **Refresh** — `POST /api/v1/auth/refresh` with refresh token. Server rotates the refresh token (old one revoked, new one issued).
4. **Logout** — `POST /api/v1/auth/logout` revokes current refresh token. Access token blacklisted in Redis until expiry.

### 6.2 JWT payload

```json
{
  "sub": "<user_id>",
  "roles": ["instructor"],
  "iat": 1745222400,
  "exp": 1745223300,
  "jti": "<token_id>",
  "iss": "aegis-backend"
}
```

Signed with RS256. Public key exposed at `/api/v1/auth/.well-known/jwks.json` for verification by other services.

### 6.3 Password policy

- Min 12 characters, at least one uppercase, lowercase, digit, symbol
- bcrypt cost factor 12
- Password history: last 5 blocked
- Account lockout after 5 failed attempts (15-min cooldown)

### 6.4 RBAC

Ira defines the permission matrix; Sachin enforces via a dependency:

```python
@router.delete("/users/{user_id}", dependencies=[Depends(require_permission("user", "delete"))])
async def delete_user(user_id: UUID): ...
```

**Default Phase 1 roles and permissions (draft — Ira to finalize):**

| Resource              | trainee      | instructor            | evaluator       | admin          |
| --------------------- | ------------ | --------------------- | --------------- | -------------- |
| own profile           | R, U         | R, U                  | R, U            | R, U           |
| other users           | —            | R (their trainees)    | R (assigned)    | CRUD           |
| content               | R (approved) | R (approved)          | R (approved)    | CRUD + approve |
| sessions (own)        | R            | —                     | —               | R              |
| sessions (others)     | —            | R, U (their trainees) | R               | R              |
| scenarios             | R            | CRUD                  | R               | CRUD           |
| evaluations           | R (own)      | CRUD (their trainees) | CRUD            | R              |
| audit log             | —            | —                     | R (their scope) | R              |
| AI (trainee depth)    | X            | X                     | X               | X              |
| AI (instructor depth) | —            | X                     | X               | X              |

---

## 7. API Conventions

### 7.1 Base URL

```
https://{host}/api/v1
```

### 7.2 Request/response format

- All requests and responses: `application/json; charset=utf-8`
- Timestamps: RFC 3339 UTC, e.g., `2026-04-21T10:30:00Z`
- UUIDs: lowercase hyphenated
- Pagination: cursor-based, `?cursor=<opaque>&limit=50` (max limit 200)
- Filtering: documented per endpoint
- Case: `snake_case` for all JSON fields

### 7.3 Standard success envelope

```json
{
  "data": { ... },
  "meta": {
    "request_id": "req_abc123",
    "timestamp": "2026-04-21T10:30:00Z"
  }
}
```

Paginated:

```json
{
  "data": [ ... ],
  "meta": {
    "request_id": "req_abc123",
    "next_cursor": "eyJpZCI6Li4ufQ==",
    "has_more": true
  }
}
```

### 7.4 Standard error envelope

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Human-readable summary",
    "details": [
      {"field": "email", "issue": "must be a valid email"}
    ],
    "request_id": "req_abc123"
  }
}
```

### 7.5 Status codes

`200 OK`, `201 Created`, `204 No Content`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `429 Too Many Requests`, `500 Internal Server Error`, `502 Bad Gateway` (LLM provider down), `503 Service Unavailable`.

### 7.6 Standard headers

| Header                        | Purpose                                                       |
| ----------------------------- | ------------------------------------------------------------- |
| `Authorization: Bearer <jwt>` | Every authenticated request                                   |
| `X-Request-ID`                | Client may supply; server echoes. Server generates if absent. |
| `X-RateLimit-Limit`           | Requests allowed per window (response)                        |
| `X-RateLimit-Remaining`       | Remaining in window (response)                                |
| `X-RateLimit-Reset`           | Unix epoch when window resets (response)                      |

### 7.7 OpenAPI spec

The live spec is auto-generated by FastAPI and served at:

- `/api/v1/docs` — Swagger UI (dev only)
- `/api/v1/redoc` — ReDoc (dev only)
- `/api/v1/openapi.json` — raw spec (always available, Harish pulls this)

---

## 8. API Endpoints

Every endpoint below requires `Authorization: Bearer <token>` unless marked **Public**. Permission requirements are noted as `permission: <resource>:<action>`.

### 8.1 Auth

#### POST /api/v1/auth/login — **Public**

Authenticate and receive tokens.

**Request**

```json
{
  "email": "pilot@example.com",
  "password": "••••••••••••"
}
```

**Response 200**

```json
{
  "data": {
    "access_token": "eyJhbGci...",
    "refresh_token": "rt_...",
    "token_type": "Bearer",
    "expires_in": 900,
    "user": {
      "id": "uuid",
      "email": "pilot@example.com",
      "full_name": "Jane Pilot",
      "roles": ["trainee"]
    }
  }
}
```

**Errors:** `401 INVALID_CREDENTIALS`, `423 ACCOUNT_LOCKED`, `429 TOO_MANY_ATTEMPTS`.

#### POST /api/v1/auth/refresh — **Public**

Rotate the access/refresh token pair.

**Request** `{ "refresh_token": "rt_..." }`

**Response 200** same shape as `/login`.

#### POST /api/v1/auth/logout

Revoke the current refresh token and blacklist the access token.

**Response 204**

#### GET /api/v1/auth/me

Return the authenticated user's profile + roles + permissions.

**Response 200**

```json
{
  "data": {
    "id": "uuid",
    "email": "pilot@example.com",
    "full_name": "Jane Pilot",
    "roles": ["trainee"],
    "permissions": ["content:read", "session:read:own"]
  }
}
```

#### POST /api/v1/auth/change-password

**Request** `{ "current_password": "...", "new_password": "..." }`

**Response 204**

---

### 8.2 Users & RBAC

_Permission: `user:*` as indicated._

| Method | Path                       | Permission         | Purpose                             |
| ------ | -------------------------- | ------------------ | ----------------------------------- |
| GET    | `/users`                   | `user:read`        | List users (filter by role, status) |
| POST   | `/users`                   | `user:create`      | Create user (admin invites)         |
| GET    | `/users/{id}`              | `user:read`        | Get user detail                     |
| PATCH  | `/users/{id}`              | `user:update`      | Update profile                      |
| DELETE | `/users/{id}`              | `user:delete`      | Soft-delete                         |
| POST   | `/users/{id}/roles`        | `user:assign_role` | Assign role                         |
| DELETE | `/users/{id}/roles/{role}` | `user:assign_role` | Revoke role                         |
| GET    | `/roles`                   | `role:read`        | List roles + permissions            |
| GET    | `/permissions`             | `role:read`        | List all permissions                |

#### POST /users

**Request**

```json
{
  "email": "trainee@example.com",
  "full_name": "John Trainee",
  "employee_id": "EMP-00123",
  "roles": ["trainee"],
  "temporary_password": "..."
}
```

**Response 201** — user resource. Sends password-reset email on first login (Phase 2 adds SSO).

---

### 8.3 Content Ingestion

_Permission: `content:*`._

| Method | Path                                 | Purpose                                              |
| ------ | ------------------------------------ | ---------------------------------------------------- |
| POST   | `/content/sources`                   | Upload a source document (FCOM/QRH/AMM/SOP/syllabus) |
| GET    | `/content/sources`                   | List sources (filter by type, aircraft, status)      |
| GET    | `/content/sources/{id}`              | Get source metadata                                  |
| GET    | `/content/sources/{id}/tree`         | Full section hierarchy (for Shreyansh's chunker)     |
| POST   | `/content/sources/{id}/approve`      | Approve for use (`content:approve`)                  |
| POST   | `/content/sources/{id}/archive`      | Archive old version                                  |
| GET    | `/content/sections/{id}`             | Single section content                               |
| GET    | `/content/references/{citation_key}` | Resolve a citation to full section + source          |
| GET    | `/content/search?q=...`              | Full-text search (Meilisearch, P1)                   |

#### POST /content/sources

Upload + parse a document.

**Request** (multipart/form-data)

```
file: <binary>
source_type: fcom|qrh|amm|sop|syllabus
aircraft_id: <uuid> (optional)
title: string
version: string
effective_date: 2026-01-15
```

**Response 202**

```json
{
  "data": {
    "source_id": "uuid",
    "status": "parsing",
    "job_id": "job_abc"
  }
}
```

Parsing is async (Celery). Client polls `/content/sources/{id}` or subscribes to WebSocket `/ws/jobs/{job_id}` (P2).

#### GET /content/sources/{id}/tree

Returns the parsed section hierarchy — **this is the contract with Shreyansh's RAG chunker.**

**Response 200**

```json
{
  "data": {
    "source_id": "uuid",
    "source_type": "fcom",
    "version": "Rev 42",
    "sections": [
      {
        "id": "uuid",
        "section_number": "3",
        "title": "Engines",
        "citation_key": "B737-FCOM-3",
        "page_number": 142,
        "content_markdown": "...",
        "children": [
          {
            "id": "uuid",
            "section_number": "3.2",
            "title": "Engine Start",
            "citation_key": "B737-FCOM-3.2",
            "page_number": 145,
            "content_markdown": "...",
            "children": [ ... ]
          }
        ]
      }
    ]
  }
}
```

---

### 8.4 AI / LLM Gateway

All AI calls go through this gateway. **No direct Gemini/OpenAI calls from the frontend.** PII filter runs before every provider call.

| Method | Path                   | Purpose                                             |
| ------ | ---------------------- | --------------------------------------------------- |
| POST   | `/ai/complete`         | Generic completion (for Shreyansh's RAG assistants) |
| POST   | `/ai/embed`            | Generate embeddings (used by Shreyansh's ingestion) |
| GET    | `/ai/providers/status` | Health of Gemini + OpenAI                           |
| GET    | `/ai/usage`            | Token + cost usage (admin dashboard)                |

#### POST /ai/complete

**Request**

```json
{
  "messages": [
    {"role": "system", "content": "You are an aerospace training assistant."},
    {"role": "user", "content": "Explain the purpose of the bleed air system."}
  ],
  "context_citations": ["B737-FCOM-3.2", "B737-FCOM-4.1"],
  "provider_preference": "auto",
  "temperature": 0.2,
  "max_tokens": 800,
  "cache": true
}
```

- `provider_preference`: `auto` (default, picks based on health + cost), `gemini`, or `openai`.
- `context_citations`: citation keys — retrieved content text is injected into the prompt by the gateway. Shreyansh's RAG retriever supplies these; Sachin resolves them to actual text.
- `cache`: if true and prompt hash hits cache, return cached response.

**Response 200**

```json
{
  "data": {
    "response": "The bleed air system...",
    "provider": "gemini",
    "model": "gemini-1.5-pro",
    "cached": false,
    "usage": {
      "prompt_tokens": 420,
      "completion_tokens": 180,
      "cost_usd": 0.0042
    },
    "citations": ["B737-FCOM-3.2"],
    "request_id": "ai_req_xyz"
  }
}
```

**Errors:**

- `502 ALL_PROVIDERS_DOWN` — both Gemini and OpenAI unreachable (fallback exhausted)
- `403 PII_DETECTED` — PII filter blocked the request
- `429 RATE_LIMITED` — per-user or global quota hit
- `400 CITATION_NOT_FOUND`

**Fallback behavior:** `auto` tries Gemini first; on timeout/5xx/quota, automatically retries on OpenAI within a single request. Both failures → 502.

**PII filter (enforced here, policy owned by Ira):**

- Strips trainee personal fields from messages before send: `email`, `employee_id`, `full_name`, `date_of_birth`, `phone`, session history linked to an identifiable user.
- If the filter can't safely strip (e.g., free-form text clearly contains a person's name), returns 403.
- Every call logs to `ai_requests` with the pre-filter hash for audit.

#### POST /ai/embed

For Shreyansh's document embedding pipeline.

**Request** `{ "texts": ["chunk 1...", "chunk 2..."], "model": "text-embedding-3-small" }`

**Response 200** `{ "data": { "embeddings": [[...], [...]], "model": "...", "usage": {...} } }`

---

### 8.5 Checklist Engine

| Method | Path                                                 | Purpose                             |
| ------ | ---------------------------------------------------- | ----------------------------------- |
| GET    | `/checklists`                                        | List (filter by aircraft, phase)    |
| GET    | `/checklists/{id}`                                   | Get checklist definition            |
| POST   | `/checklists/{id}/sessions`                          | Start a checklist execution session |
| POST   | `/checklists/sessions/{sid}/items/{item_id}/call`    | Trainee calls an item (challenge)   |
| POST   | `/checklists/sessions/{sid}/items/{item_id}/respond` | Respond (response)                  |
| POST   | `/checklists/sessions/{sid}/complete`                | End session                         |
| GET    | `/checklists/sessions/{sid}`                         | Session state + results             |

**Modes supported:** `challenge_response`, `read_do`, `do_verify` (per item).

**Scoring (computed by the engine):**

- Items completed / total
- Items out of order
- Items skipped
- Average time per item vs. target
- Critical items missed (weighted heavier)

#### POST /checklists/{id}/sessions

**Request** `{ "mode": "challenge_response", "trainee_id": "uuid" }` (instructor starting for trainee, or self)

**Response 201**

```json
{
  "data": {
    "session_id": "uuid",
    "checklist_id": "uuid",
    "items": [
      {"id": "uuid", "ordinal": 1, "challenge": "Parking brake", "expected_response": "Set", "target_time_seconds": 3}
    ],
    "started_at": "2026-04-21T10:30:00Z"
  }
}
```

---

### 8.6 Procedures (Normal & Emergency)

| Method | Path                                                  | Purpose                                    |
| ------ | ----------------------------------------------------- | ------------------------------------------ |
| GET    | `/procedures`                                         | List (filter by aircraft, type, phase)     |
| GET    | `/procedures/{id}`                                    | Full procedure with steps                  |
| GET    | `/procedures/{id}/flow`                               | Flow with branching (QRH rendering engine) |
| POST   | `/procedures/{id}/sessions`                           | Start procedure execution                  |
| POST   | `/procedures/sessions/{sid}/steps/{step_id}/complete` | Mark step done                             |
| POST   | `/procedures/sessions/{sid}/steps/{step_id}/branch`   | Choose branch (emergency)                  |
| POST   | `/procedures/sessions/{sid}/complete`                 | End session                                |
| GET    | `/procedures/sessions/{sid}/deviations`               | Computed deviations for this session       |

#### GET /procedures/{id}/flow

QRH rendering — returns a DAG for branching procedures.

**Response 200**

```json
{
  "data": {
    "procedure_id": "uuid",
    "name": "Engine Fire — In Flight",
    "root_step_id": "uuid",
    "steps": {
      "<step_id>": {
        "ordinal": 1,
        "action_text": "Thrust lever (affected engine) — IDLE",
        "expected_response": null,
        "mode": "do_verify",
        "is_critical": true,
        "branches": []
      },
      "<step_id_2>": {
        "ordinal": 2,
        "action_text": "Engine master switch — OFF",
        "branches": [
          {"condition": "fire persists", "next_step_id": "<step_id_3>"},
          {"condition": "fire extinguished", "next_step_id": "<step_id_4>"}
        ]
      }
    },
    "citation_key": "B737-QRH-7.1"
  }
}
```

---

### 8.7 High-Risk Scenarios

_V1 cut, windshear, TCAS RA, engine fire — these are pre-defined scenarios with specific trigger logic._

| Method | Path                                | Purpose                                             |
| ------ | ----------------------------------- | --------------------------------------------------- |
| GET    | `/scenarios`                        | List                                                |
| GET    | `/scenarios/{id}`                   | Scenario config                                     |
| POST   | `/scenarios/{id}/sessions`          | Start scenario                                      |
| POST   | `/scenarios/sessions/{sid}/trigger` | Fire the trigger event (e.g., engine failure at V1) |
| POST   | `/scenarios/sessions/{sid}/action`  | Trainee action                                      |
| GET    | `/scenarios/sessions/{sid}/result`  | Scored result                                       |

Scenarios drive the frontend (Harish) and VR (Subhash) — the backend owns the **decision logic and scoring**, not the visuals. Shreyansh's modules call these endpoints.

---

### 8.8 Analytics & Compliance

| Method | Path                                   | Purpose                          |
| ------ | -------------------------------------- | -------------------------------- |
| GET    | `/analytics/sessions/{sid}/deviations` | Step-level + timing deviations   |
| GET    | `/analytics/trainees/{id}/progression` | Competency progression over time |
| GET    | `/analytics/trainees/{id}/summary`     | Aggregated performance           |
| GET    | `/analytics/cohorts/{id}/summary`      | Cohort stats (instructor view)   |
| GET    | `/analytics/compliance/report`         | Procedural compliance report     |

#### GET /analytics/sessions/{sid}/deviations

**Response 200**

```json
{
  "data": {
    "session_id": "uuid",
    "deviations": [
      {
        "id": "uuid",
        "step_id": "uuid",
        "step_name": "Flaps — 5",
        "deviation_type": "timing",
        "severity": "moderate",
        "expected": {"target_time_seconds": 3},
        "actual": {"elapsed_seconds": 8.2},
        "detected_at": "2026-04-21T10:35:12Z"
      }
    ],
    "summary": {
      "total_steps": 24,
      "completed": 23,
      "skipped": 1,
      "out_of_order": 0,
      "timing_violations": 2,
      "critical_misses": 0,
      "overall_compliance_pct": 91.6
    }
  }
}
```

---

### 8.9 Competency & Evaluation

| Method | Path                          | Purpose                                      |
| ------ | ----------------------------- | -------------------------------------------- |
| GET    | `/competencies`               | List competencies                            |
| GET    | `/trainees/{id}/competencies` | Trainee's evidence map                       |
| GET    | `/rubrics`                    | List rubrics                                 |
| POST   | `/rubrics`                    | Create rubric (`rubric:create`)              |
| GET    | `/rubrics/{id}`               | Get rubric                                   |
| POST   | `/sessions/{sid}/evaluations` | Submit evaluation (`evaluation:create`)      |
| GET    | `/evaluations/{id}`           | Get evaluation                               |
| PATCH  | `/evaluations/{id}`           | Update (within 24h, instructor or evaluator) |

#### POST /sessions/{sid}/evaluations

**Request**

```json
{
  "rubric_id": "uuid",
  "scores": {
    "procedural_compliance": 4.5,
    "crm": 4.0,
    "technical_knowledge": 3.5
  },
  "grade": "satisfactory",
  "comments": "Strong checklist discipline. Watch timing on abnormals."
}
```

---

### 8.10 VR Telemetry Ingestion

**Contract owned jointly by Sachin and Subhash. Lock before either side writes code.**

| Method | Path                        | Purpose                           |
| ------ | --------------------------- | --------------------------------- |
| POST   | `/vr/sessions`              | Register a VR session start       |
| POST   | `/vr/sessions/{vid}/events` | Batch ingest events (high volume) |
| POST   | `/vr/sessions/{vid}/end`    | Mark VR session ended             |
| GET    | `/vr/sessions/{vid}`        | Get VR session summary            |

#### POST /vr/sessions

**Request**

```json
{
  "training_session_id": "uuid",
  "device_id": "meta_quest_3_001",
  "device_type": "Meta Quest 3",
  "runtime": "webxr",
  "app_version": "0.3.2"
}
```

**Response 201** `{ "data": { "vr_session_id": "uuid" } }`

#### POST /vr/sessions/{vid}/events

Batched to reduce network churn. Accept 1–500 events per call. If `id` is client-generated (UUIDv7), server dedupes on retry.

**Request**

```json
{
  "events": [
    {
      "id": "client_uuid_v7",
      "event_type": "interaction",
      "timestamp": "2026-04-21T10:35:12.123Z",
      "head_pose": {"position": [0.1, 1.7, -0.3], "rotation": [0, 0.2, 0, 0.98]},
      "controller_left": {"position": [...], "trigger": 0.0, "grip": 1.0},
      "controller_right": {"position": [...], "trigger": 1.0, "grip": 0.0},
      "interaction_target": "switch_engine_start_L",
      "payload": {"action": "press", "result": "engine_start_initiated"}
    }
  ]
}
```

**Response 202** `{ "data": { "accepted": 1, "duplicates": 0 } }`

**Event types (Phase 1 minimum set):**
`session_start`, `session_end`, `interaction`, `gaze`, `locomotion`, `procedure_step_complete`, `error`, `performance_sample` (fps, dropped frames).

**Storage:** events ingested to Kafka-style queue (Redis Streams for Phase 1) then written to `vr_telemetry_events` by a worker. Compliance engine reads from this table.

---

### 8.11 Audit Log

_Permission: `audit:read` (admin-only Phase 1)._

| Method | Path                 | Purpose                                               |
| ------ | -------------------- | ----------------------------------------------------- |
| GET    | `/audit/logs`        | Query (filter by actor, action, resource, time range) |
| GET    | `/audit/logs/{id}`   | Single entry                                          |
| GET    | `/audit/logs/verify` | Verify hash chain integrity                           |

**All actions audited in Phase 1:**

- `auth.login`, `auth.login_failed`, `auth.logout`, `auth.password_changed`
- `user.created`, `user.updated`, `user.deleted`, `user.role_assigned`, `user.role_revoked`
- `content.uploaded`, `content.approved`, `content.archived`
- `ai.query` (every LLM call)
- `data.accessed` (sensitive reads)
- `config.changed` (any admin settings)
- `session.evaluated`

---

### 8.12 Assets

_Permission: `asset:read`._

| Method | Path                                                 | Purpose                                      |
| ------ | ---------------------------------------------------- | -------------------------------------------- |
| GET    | `/assets?aircraft_id=...&type=cockpit&fidelity=high` | List (metadata)                              |
| GET    | `/assets/{id}`                                       | Asset metadata                               |
| GET    | `/assets/{id}/download`                              | Signed URL (15-min expiry) for glTF download |

Actual files live in MinIO; the API returns a presigned URL so the download bypasses the app server. Harish and Subhash both consume this.

---

### 8.13 Health & Ops

_Public endpoints (no auth)._

| Method | Path            | Purpose                            |
| ------ | --------------- | ---------------------------------- |
| GET    | `/health`       | Liveness                           |
| GET    | `/health/ready` | Readiness (DB + Redis reachable)   |
| GET    | `/metrics`      | Prometheus (internal network only) |
| GET    | `/version`      | Build SHA, version, env            |

---

## 9. AI Integration Layer

### 9.1 Provider abstraction

Ira owns the abstract `LLMProvider` interface. Sachin implements the Gemini and OpenAI concrete classes:

```python
# app/modules/ai/providers/base.py (Ira's contract)
class LLMProvider(Protocol):
    name: str
    async def complete(self, req: CompletionRequest) -> CompletionResponse: ...
    async def embed(self, texts: list[str], model: str) -> EmbedResponse: ...
    async def health_check(self) -> ProviderHealth: ...
```

### 9.2 API key management

- Keys stored as env vars: `GEMINI_API_KEY`, `OPENAI_API_KEY`
- In prod, sourced from a secrets manager (Phase 2: Vault). For Phase 1, `.env` file with strict filesystem perms (600).
- Keys encrypted at rest in the database when stored for rotation history (AES-256-GCM with a KMS-wrapped key).
- Rotation: `scripts/rotate_api_keys.py` — no downtime (new key active before old key revoked).
- Keys **never logged**, never included in error messages, never sent to clients.

### 9.3 Rate limiting (LLM)

- Per user: 60 requests/min (trainee), 200/min (instructor), unlimited (admin)
- Global: 2000 requests/min across the provider (protects against runaway costs)
- Redis sliding-window counter
- Exceeded → 429 with `Retry-After` header

### 9.4 Response caching

- Key: SHA-256 of `(provider, model, messages, temperature, context_citations)`
- TTL: 24 hours default, configurable
- Only cache deterministic requests (temperature < 0.3)
- Cache bust on content source version change
- Target: >30% cache hit rate within 4 weeks of launch (cost control target)

### 9.5 Fallback logic

```
On auto:
  try Gemini (timeout 15s)
    on 5xx/timeout/quota → try OpenAI (timeout 15s)
      on 5xx/timeout/quota → 502 ALL_PROVIDERS_DOWN
```

Health checks every 30s mark a provider degraded; degraded provider is skipped as primary but still tried on fallback.

### 9.6 PII filter

Runs **before** any payload leaves the backend. Policy is Ira's:

1. Strip known PII fields from structured context (user profile, session metadata).
2. Regex sweep on free-form user messages for email, phone, obvious name patterns.
3. If high-risk PII detected and can't be redacted safely → 403 with `PII_DETECTED`.
4. Every blocked request logged to audit.

**Never sent to LLM providers under any circumstance:** trainee full name, email, employee ID, DOB, medical info, session-linked identifiers.

---

## 10. Security

- TLS 1.3 everywhere, even intra-cluster (mTLS between services when split in Phase 2)
- HSTS, secure cookies, CSRF tokens on state-changing endpoints (if cookie auth used; Bearer tokens don't need CSRF)
- CORS: explicit allowlist (Harish's frontend origins only)
- Helmet-equivalent headers via `secure` middleware (CSP, X-Frame-Options, etc.)
- SQL injection: SQLAlchemy parameterized queries (never string-build)
- Input validation: Pydantic on every request
- Output encoding: FastAPI handles JSON; no user-controlled HTML rendering
- Dependency scanning: GitHub Dependabot + `pip-audit` in CI
- Container scanning: Trivy in CI
- Secrets: never committed; pre-commit hook with `detect-secrets`
- Audit log: append-only table, hash-chained, periodic integrity check exposed via `/audit/logs/verify`

---

## 11. Deployment & DevOps

### 11.1 Docker

**Dockerfile** (multi-stage, distroless final image):

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry export -f requirements.txt -o requirements.txt
RUN pip install --target=/deps -r requirements.txt

FROM gcr.io/distroless/python3-debian12
WORKDIR /app
COPY --from=builder /deps /usr/lib/python3.11/site-packages
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
EXPOSE 8000
USER nonroot
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "-b", "0.0.0.0:8000", "--workers", "4"]
```

### 11.2 Docker Compose (local dev)

Services: `api`, `postgres`, `redis`, `minio`, `meilisearch`, `celery-worker`, `celery-beat`.

### 11.3 CI/CD (GitHub Actions)

**ci.yml:**

1. `lint` — ruff + mypy
2. `test` — pytest with postgres + redis services, coverage threshold 80%
3. `security` — pip-audit, trivy on built image
4. `build` — docker build, push to GHCR on merge to main

**deploy.yml:**

1. Manual approval for staging/prod
2. `alembic upgrade head` as init container
3. Rolling deploy
4. Post-deploy smoke test

### 11.4 Environment configuration

`.env.example`:

```
ENV=local
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://aegis:aegis@postgres:5432/aegis
REDIS_URL=redis://redis:6379/0
MEILI_URL=http://meilisearch:7700
MEILI_MASTER_KEY=change-me

JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=604800

GEMINI_API_KEY=
OPENAI_API_KEY=

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET_ASSETS=aegis-assets

AI_CACHE_TTL_SECONDS=86400
AI_RATE_LIMIT_TRAINEE=60
AI_RATE_LIMIT_INSTRUCTOR=200

CORS_ALLOWED_ORIGINS=http://localhost:3000
```

---

## 12. Cross-Team Contracts

| Counterparty  | What you give them                                                                 | What they give you                                           | Lock by                               |
| ------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------- |
| **Ira**       | Implementations against her interfaces                                             | ERD, RBAC matrix, `LLMProvider` interface, PII filter policy | Sprint 1                              |
| **Shreyansh** | `GET /content/sources/{id}/tree`, `/ai/complete`, `/ai/embed`, citation resolution | RAG retrieval output shape (citation keys + text chunks)     | Sprint 1                              |
| **Harish**    | Live OpenAPI spec at `/api/v1/openapi.json`, consistent error envelope             | Nothing — he consumes the API                                | Day 1                                 |
| **Subhash**   | `POST /vr/sessions`, `POST /vr/sessions/{vid}/events`                              | Event schema + batching cadence                              | **Sprint 1 — blocker for both sides** |
| **Chinmay**   | `GET /assets/{id}/download`                                                        | glTF file format, fidelity tiers, naming convention          | Sprint 2                              |

---

## 13. Error Codes

| Code                  | HTTP | Meaning                                  |
| --------------------- | ---- | ---------------------------------------- |
| `VALIDATION_FAILED`   | 400  | Pydantic validation error; see `details` |
| `INVALID_CREDENTIALS` | 401  | Wrong email/password                     |
| `TOKEN_EXPIRED`       | 401  | JWT expired                              |
| `TOKEN_INVALID`       | 401  | Signature/structure invalid              |
| `TOKEN_REVOKED`       | 401  | Refresh token revoked                    |
| `FORBIDDEN`           | 403  | Authenticated but lacks permission       |
| `PII_DETECTED`        | 403  | AI gateway blocked request               |
| `NOT_FOUND`           | 404  | Resource missing                         |
| `CONFLICT`            | 409  | Uniqueness/version conflict              |
| `ACCOUNT_LOCKED`      | 423  | Too many failed logins                   |
| `RATE_LIMITED`        | 429  | Per-user or global rate limit            |
| `TOO_MANY_ATTEMPTS`   | 429  | Auth-specific lockout risk               |
| `CITATION_NOT_FOUND`  | 400  | AI call referenced missing citation_key  |
| `ALL_PROVIDERS_DOWN`  | 502  | Gemini + OpenAI both failed              |
| `PROVIDER_TIMEOUT`    | 504  | Single provider timeout (retried)        |
| `INTERNAL_ERROR`      | 500  | Unhandled; request_id in log for tracing |

---

## 14. Open Questions

These need resolution with Ira before or during Sprint 1:

1. **RBAC matrix** — final permissions per role (draft in §6.4).
2. **ERD** — does Ira's design deviate from §5?
3. **PII filter policy** — exact regex patterns and the "can't safely strip" fallback behavior.
4. **SSO / identity provider** — Phase 1 email+password only, or hook to LDAP/OIDC now?
5. **Multi-tenancy** — Phase 1 single-customer; is there a `tenant_id` we should plumb in now to avoid later migration pain?
6. **Audit retention** — how long to keep audit entries? (affects partitioning strategy)
7. **Kafka vs Redis Streams for VR telemetry** — scale target for concurrent VR sessions?

---

**End of document.**

_This is a working spec. Every section is a contract with someone — raise a PR or flag on Slack to change it._
