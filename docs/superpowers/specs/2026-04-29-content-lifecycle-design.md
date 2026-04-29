# Content Lifecycle Tracking — Design Spec

**Owner:** Shreyansh Mishra
**Status:** Approved (autonomous), pending implementation
**Module:** `app/modules/content/` (extends Sachin's existing module surgically)
**Branch:** `feat/content-lifecycle-shreyansh` (off `feat/rag-foundation`)
**Excel ref:** R73, P1, "Content lifecycle tracking"

---

## 1. Goal

Track when each `ContentSource` was last reviewed, when it's next due for review, and when it should be deprecated. Surface "needs review" + "expiring soon" + "deprecated" lists via API so admins (and a future Celery beat job / email digest) know what to do.

Production-grade from day one: real columns + real endpoints + per-source-type defaults + audit-friendly. Frontend / scheduled jobs are out of scope for this PR but the API is consumable as soon as it lands.

## 2. Non-goals

- Email/Slack notifications on items needing review (Phase 2 — needs notification infra)
- Scheduled auto-archive on `deprecation_date` passing (Phase 2 — Celery beat task)
- Frontend dashboard (Harish's lane, eventually)
- Approval-cycle workflow (multi-stage signoff) — Sachin's content governance scope; we just track *when*, not *who-approves-what*
- Versioning of review records — single row per source, history derivable from `last_reviewed_at` + audit_log

## 3. Architectural seam

Adds 4 columns to `content_sources` (Sachin's table — minimal surgical addition):
- `last_reviewed_at` (timestamptz nullable)
- `last_reviewed_by` (uuid nullable, FK users.id)
- `next_review_due` (timestamptz nullable, defaults to approved_at + cadence)
- `deprecation_date` (date nullable, admin-set)

Plus 3 endpoints (mounted on the existing content router):
- `POST /content/sources/{id}/mark-reviewed` — bumps `last_reviewed_at` + sets next_review_due forward
- `GET /content/sources/needs-review` — sources where `next_review_due <= now()` (with limit/offset)
- `GET /content/sources/expiring-soon` — sources where `next_review_due <= now() + N days` (configurable window)

`approve_source` (in `ContentService`) is updated to set `next_review_due = now() + CONTENT_REVIEW_CADENCE_DAYS` on first approval.

## 4. Data model — additive only

### `content_sources` columns added

| Column | Type | Notes |
|---|---|---|
| `last_reviewed_at` | `TIMESTAMPTZ NULL` | bumped by mark-reviewed endpoint |
| `last_reviewed_by` | `UUID NULL` | FK users.id, who reviewed it |
| `next_review_due` | `TIMESTAMPTZ NULL` | when the source needs re-review; null = no review schedule |
| `deprecation_date` | `DATE NULL` | when the source should be archived; null = no deprecation planned |

Indexes:
- `ix_content_sources_next_review_due` (for the needs-review query)
- `ix_content_sources_deprecation_date` (for expiring-soon and future cleanup jobs)

### Per-source-type review cadence

Default cadence in days, overridable per source via the API:

```python
CONTENT_REVIEW_CADENCE_DAYS_DEFAULT: int = 90    # generic
CONTENT_REVIEW_CADENCE_DAYS_FCOM: int = 180      # manuals change less often
CONTENT_REVIEW_CADENCE_DAYS_QRH: int = 90
CONTENT_REVIEW_CADENCE_DAYS_AMM: int = 180
CONTENT_REVIEW_CADENCE_DAYS_SOP: int = 90
CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS: int = 60   # syllabi change with each cohort

CONTENT_EXPIRING_SOON_WINDOW_DAYS: int = 14  # default for expiring-soon endpoint
```

Resolution: lookup function `_cadence_for(source_type)` returns the right config setting.

## 5. Endpoints

### 5.1 `POST /api/v1/content/sources/{source_id}/mark-reviewed`

Body: optional `{"next_review_in_days": int}` to override the default cadence for this review cycle. Defaults to `_cadence_for(source.source_type)`.

Auth: instructor or admin.

Behavior:
- Sets `last_reviewed_at = now()`
- Sets `last_reviewed_by = current_user.id`
- Sets `next_review_due = now() + cadence_days`
- Returns updated `ContentSourceOut`

### 5.2 `GET /api/v1/content/sources/needs-review`

Query params: `limit` (default 100), `offset` (default 0), `source_type` (optional filter), `aircraft_id` (optional filter).

Returns sources where `status = 'approved'` AND `next_review_due IS NOT NULL` AND `next_review_due <= now()`. Ordered by `next_review_due ASC` (oldest-overdue first).

Auth: instructor or admin.

### 5.3 `GET /api/v1/content/sources/expiring-soon`

Query params: `within_days` (default `CONTENT_EXPIRING_SOON_WINDOW_DAYS=14`), `limit`, `offset`, `source_type`, `aircraft_id`.

Returns sources where `status = 'approved'` AND `next_review_due IS NOT NULL` AND `next_review_due > now()` AND `next_review_due <= now() + within_days`. Ordered by `next_review_due ASC`.

Auth: instructor or admin.

### 5.4 (Optional, Phase 2) `POST /content/sources/{id}/set-deprecation`

Body: `{"deprecation_date": "YYYY-MM-DD" | null}`. Admin only. Defer to Phase 2 (no Celery beat to act on it yet — exposing it now adds API surface without value).

## 6. ContentSourceOut schema additions

The existing `ContentSourceOut` Pydantic schema gains the 4 new fields (all optional, default `None`):

```python
class ContentSourceOut(BaseModel):
    # ... existing fields ...
    last_reviewed_at: datetime | None = None
    last_reviewed_by: UUID | None = None
    next_review_due: datetime | None = None
    deprecation_date: date | None = None
```

## 7. ContentService changes

`ContentService.approve_source(source_id, approver_id)` is updated to ALSO set `next_review_due = now() + cadence_for(source.source_type)` on first approval. If `next_review_due` is already set (e.g. re-approval), leave it alone.

Plus add 3 new service methods:
- `mark_reviewed(source_id, reviewer_id, override_days=None) -> ContentSource`
- `list_needs_review(source_type=None, aircraft_id=None, limit=100, offset=0) -> list[ContentSource]`
- `list_expiring_soon(within_days=14, source_type=None, aircraft_id=None, limit=100, offset=0) -> list[ContentSource]`

## 8. Failure modes

| Failure | Behavior |
|---|---|
| `next_review_due` is null on a source | Excluded from both endpoints — null means "no schedule" |
| `now()` clock skew vs DB | Trivial in practice; both endpoints use DB `now()` to be self-consistent |
| Re-approving an already-approved source | `next_review_due` not reset (admin must mark-reviewed explicitly to bump) |
| Source was deprecated then re-approved | `deprecation_date` retained until admin clears it (audit-friendly) |
| Mark-reviewed on a non-approved source | Allowed — sets last_reviewed_at + next_review_due regardless of status |

## 9. Tests

**Unit:**
- `_cadence_for(source_type)` returns the right config value per type, default for unknown
- ContentSource model accepts the 4 new fields cleanly

**Integration:**
- Create + approve a source → `next_review_due` populated (default cadence applied)
- POST `/mark-reviewed` → `last_reviewed_at` + `last_reviewed_by` set, `next_review_due` advanced
- POST `/mark-reviewed` with `next_review_in_days=30` → cadence overridden
- GET `/needs-review` with overdue source → returned in list
- GET `/needs-review` with not-yet-due source → not returned
- GET `/expiring-soon` with source due in 7 days, window=14 → returned
- GET `/expiring-soon` with source due in 30 days, window=14 → not returned
- All 3 endpoints role-gated to instructor/admin (trainee → 403)

## 10. Configuration (in `app/config.py`)

```python
CONTENT_REVIEW_CADENCE_DAYS_DEFAULT: int = 90
CONTENT_REVIEW_CADENCE_DAYS_FCOM: int = 180
CONTENT_REVIEW_CADENCE_DAYS_QRH: int = 90
CONTENT_REVIEW_CADENCE_DAYS_AMM: int = 180
CONTENT_REVIEW_CADENCE_DAYS_SOP: int = 90
CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS: int = 60
CONTENT_EXPIRING_SOON_WINDOW_DAYS: int = 14
```

## 11. Coordination

- Sachin: 4 column additions to `content_sources` (his table) + tweak to `approve_source` (his service). Additive migration, no destructive change. `next_review_due` is set on FIRST approval going forward; existing approved rows have it as NULL (admin can backfill via mark-reviewed). PR description will flag this clearly.
- Ira / Harish: independent — no overlap.

## 12. Out of scope

- Celery beat job to email/Slack about needs-review items
- Auto-archive on `deprecation_date <= today()`
- Frontend dashboard for the lists
- Per-source override of the cadence outside of `mark-reviewed` (e.g., "this FCOM gets 30-day cadence forever") — would need an extra column; defer until needed
