# Content Lifecycle Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add lifecycle tracking columns + 3 endpoints + service methods to content module per the design at [`docs/superpowers/specs/2026-04-29-content-lifecycle-design.md`](../specs/2026-04-29-content-lifecycle-design.md).

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · Postgres · Alembic.

---

## Reference

### File map

```
Modify:
  app/modules/content/models.py        (+ 4 columns on ContentSource)
  app/modules/content/schemas.py       (+ 4 fields on ContentSourceOut, + MarkReviewedRequest)
  app/modules/content/service.py       (+ mark_reviewed + list_needs_review + list_expiring_soon; tweak approve_source)
  app/modules/content/router.py        (+ 3 endpoints)
  app/config.py                        (+ 7 settings: 6 cadence + 1 window)

Create:
  migrations/versions/<auto>_add_content_lifecycle_columns.py
  tests/unit/test_content_lifecycle.py
  tests/integration/test_content_lifecycle_endpoints.py
```

### Naming used throughout

```python
def _cadence_for(source_type: str) -> int:
    """Returns review cadence in days for a given source_type."""

# In ContentService:
async def mark_reviewed(self, source_id, reviewer_id, override_days=None) -> ContentSource: ...
async def list_needs_review(self, source_type=None, aircraft_id=None, limit=100, offset=0) -> list[ContentSource]: ...
async def list_expiring_soon(self, within_days=14, source_type=None, aircraft_id=None, limit=100, offset=0) -> list[ContentSource]: ...
```

---

# Phase A — Plumbing

## Task A1: Add lifecycle columns to ContentSource model

**Files:** Modify `app/modules/content/models.py`

- [ ] **Step 1: Find the `ContentSource` class and append 4 new columns AFTER `updated_at`**

```python
    # Lifecycle tracking (R73)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    next_review_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deprecation_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
```

Make sure `from datetime import date` is added to the top of the file if not present (it already imports `datetime` and `Date` from sqlalchemy).

- [ ] **Step 2: Verify import**

Run: `.venv/Scripts/python.exe -c "from app.modules.content.models import ContentSource; print(ContentSource.next_review_due)"`
Expected: prints something like `ContentSource.next_review_due`

- [ ] **Step 3: Commit**

```bash
git add app/modules/content/models.py
git commit -m "feat(content): add lifecycle columns to ContentSource (R73)"
```

---

## Task A2: Alembic migration to add columns + indexes

**Files:** Create `migrations/versions/<auto>_add_content_lifecycle_columns.py`

- [ ] **Step 1: Generate empty migration**

Run: `.venv/Scripts/python.exe -m alembic revision -m "add_content_lifecycle_columns"`

- [ ] **Step 2: Edit `upgrade()` and `downgrade()`**

```python
def upgrade() -> None:
    op.add_column("content_sources", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_sources", sa.Column("last_reviewed_by", sa.UUID(), nullable=True))
    op.add_column("content_sources", sa.Column("next_review_due", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_sources", sa.Column("deprecation_date", sa.Date(), nullable=True))
    op.create_foreign_key(
        "content_sources_last_reviewed_by_fkey",
        "content_sources", "users",
        ["last_reviewed_by"], ["id"],
    )
    op.create_index("ix_content_sources_next_review_due", "content_sources", ["next_review_due"])
    op.create_index("ix_content_sources_deprecation_date", "content_sources", ["deprecation_date"])


def downgrade() -> None:
    op.drop_index("ix_content_sources_deprecation_date", table_name="content_sources")
    op.drop_index("ix_content_sources_next_review_due", table_name="content_sources")
    op.drop_constraint("content_sources_last_reviewed_by_fkey", "content_sources", type_="foreignkey")
    op.drop_column("content_sources", "deprecation_date")
    op.drop_column("content_sources", "next_review_due")
    op.drop_column("content_sources", "last_reviewed_by")
    op.drop_column("content_sources", "last_reviewed_at")
```

- [ ] **Step 3: Run migration**

Run: `.venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade ... -> <new_rev>, add_content_lifecycle_columns`

- [ ] **Step 4: Verify columns**

Run:
```
.venv/Scripts/python.exe -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings
async def chk():
    e = create_async_engine(get_settings().DATABASE_URL)
    async with e.connect() as c:
        cols = list(await c.execute(text(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='content_sources' AND column_name IN ('last_reviewed_at','last_reviewed_by','next_review_due','deprecation_date') ORDER BY column_name\")))
        print('cols:', cols)
    await e.dispose()
asyncio.run(chk())
"
```
Expected: 4 rows.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_add_content_lifecycle_columns.py
git commit -m "feat(content): alembic migration for lifecycle columns"
```

---

## Task A3: Add 7 settings to `app/config.py`

**Files:** Modify `app/config.py`

- [ ] **Step 1: Append to the `Settings` class** (after the `MODERATION_*` block from F1):

```python
    # ─── Content lifecycle (R73) ────────────────────────────────────────────
    CONTENT_REVIEW_CADENCE_DAYS_DEFAULT: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_FCOM: int = 180
    CONTENT_REVIEW_CADENCE_DAYS_QRH: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_AMM: int = 180
    CONTENT_REVIEW_CADENCE_DAYS_SOP: int = 90
    CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS: int = 60
    CONTENT_EXPIRING_SOON_WINDOW_DAYS: int = 14
```

- [ ] **Step 2: Verify**

Run: `.venv/Scripts/python.exe -c "from app.config import get_settings; s = get_settings(); print(s.CONTENT_REVIEW_CADENCE_DAYS_DEFAULT, s.CONTENT_EXPIRING_SOON_WINDOW_DAYS)"`
Expected: `90 14`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat(config): add CONTENT_REVIEW_CADENCE + EXPIRING_SOON_WINDOW settings"
```

---

## Task A4: Add fields to `ContentSourceOut` schema + create `MarkReviewedRequest`

**Files:** Modify `app/modules/content/schemas.py`

- [ ] **Step 1: Find `ContentSourceOut` and add 4 fields**

Locate the existing `ContentSourceOut` class. Add after the existing fields:

```python
    # Lifecycle tracking (R73)
    last_reviewed_at: datetime | None = None
    last_reviewed_by: UUID | None = None
    next_review_due: datetime | None = None
    deprecation_date: date | None = None
```

Make sure the file imports include `date` from `datetime`. If only `datetime` is imported, change `from datetime import datetime` → `from datetime import date, datetime`.

- [ ] **Step 2: Add `MarkReviewedRequest` at the end of the file**

```python
class MarkReviewedRequest(BaseModel):
    next_review_in_days: int | None = Field(default=None, ge=1, le=3650)
```

- [ ] **Step 3: Verify**

Run: `.venv/Scripts/python.exe -c "from app.modules.content.schemas import ContentSourceOut, MarkReviewedRequest; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/modules/content/schemas.py
git commit -m "feat(content): add lifecycle fields to ContentSourceOut + MarkReviewedRequest"
```

---

# Phase B — Service methods

## Task B1: Add `_cadence_for` helper + tweak `approve_source` + add 3 service methods

**Files:** Modify `app/modules/content/service.py`

- [ ] **Step 1: Add `_cadence_for` helper near the top of the file** (after imports, before `class ContentService`):

```python
from app.config import get_settings as _get_settings_for_cadence


def _cadence_for(source_type: str) -> int:
    """Returns review cadence in days based on source type."""
    s = _get_settings_for_cadence()
    return {
        "fcom": s.CONTENT_REVIEW_CADENCE_DAYS_FCOM,
        "qrh": s.CONTENT_REVIEW_CADENCE_DAYS_QRH,
        "amm": s.CONTENT_REVIEW_CADENCE_DAYS_AMM,
        "sop": s.CONTENT_REVIEW_CADENCE_DAYS_SOP,
        "syllabus": s.CONTENT_REVIEW_CADENCE_DAYS_SYLLABUS,
    }.get(source_type, s.CONTENT_REVIEW_CADENCE_DAYS_DEFAULT)
```

(If `get_settings` is already imported, you can reuse it; the alias avoids name conflicts.)

- [ ] **Step 2: Update `approve_source` method** to set `next_review_due` on first approval

Find the existing `approve_source` method. After the existing `source.status = "approved"` line, add:

```python
        if source.next_review_due is None:
            from datetime import UTC, datetime, timedelta
            source.next_review_due = datetime.now(UTC) + timedelta(days=_cadence_for(source.source_type))
```

- [ ] **Step 3: Add `mark_reviewed`, `list_needs_review`, `list_expiring_soon` methods to `ContentService`**

Add these three methods at the end of the class:

```python
    async def mark_reviewed(self, source_id: str, reviewer_id, override_days: int | None = None) -> ContentSource:
        from datetime import UTC, datetime, timedelta
        source = await self.get_source(source_id)
        cadence = override_days if override_days is not None else _cadence_for(source.source_type)
        source.last_reviewed_at = datetime.now(UTC)
        source.last_reviewed_by = reviewer_id
        source.next_review_due = datetime.now(UTC) + timedelta(days=cadence)
        await self.db.flush()
        return source

    async def list_needs_review(
        self,
        source_type: str | None = None,
        aircraft_id=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentSource]:
        from datetime import UTC, datetime
        q = select(ContentSource).where(
            ContentSource.status == "approved",
            ContentSource.next_review_due.isnot(None),
            ContentSource.next_review_due <= datetime.now(UTC),
        )
        if source_type:
            q = q.where(ContentSource.source_type == source_type)
        if aircraft_id:
            q = q.where(ContentSource.aircraft_id == aircraft_id)
        q = q.order_by(ContentSource.next_review_due.asc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def list_expiring_soon(
        self,
        within_days: int = 14,
        source_type: str | None = None,
        aircraft_id=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentSource]:
        from datetime import UTC, datetime, timedelta
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=within_days)
        q = select(ContentSource).where(
            ContentSource.status == "approved",
            ContentSource.next_review_due.isnot(None),
            ContentSource.next_review_due > now,
            ContentSource.next_review_due <= cutoff,
        )
        if source_type:
            q = q.where(ContentSource.source_type == source_type)
        if aircraft_id:
            q = q.where(ContentSource.aircraft_id == aircraft_id)
        q = q.order_by(ContentSource.next_review_due.asc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())
```

- [ ] **Step 4: Verify import + service instantiates**

Run: `.venv/Scripts/python.exe -c "from app.modules.content.service import ContentService, _cadence_for; print(_cadence_for('fcom'), _cadence_for('unknown'))"`
Expected: `180 90`

- [ ] **Step 5: Commit**

```bash
git add app/modules/content/service.py
git commit -m "feat(content): _cadence_for + mark_reviewed/list_needs_review/list_expiring_soon"
```

---

# Phase C — Router endpoints

## Task C1: Add 3 endpoints to `app/modules/content/router.py`

**Files:** Modify `app/modules/content/router.py`

- [ ] **Step 1: Append the 3 endpoints to the file**

Add after the existing endpoints (e.g., after `approve_source`):

```python
@router.post(
    "/sources/{source_id}/mark-reviewed",
    response_model=dict,
    summary="Mark a content source as reviewed (admin/instructor)",
    description=(
        "Bumps `last_reviewed_at` to now and advances `next_review_due` by the cadence "
        "for the source's type (or by the override if provided in the body)."
    ),
    operation_id="content_sources_mark_reviewed",
)
async def mark_reviewed_endpoint(
    source_id: str,
    body: dict | None,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not (set(current_user.roles) & {"admin", "instructor"}):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    from app.modules.content.schemas import MarkReviewedRequest
    payload = MarkReviewedRequest.model_validate(body or {})
    svc = ContentService(db)
    src = await svc.mark_reviewed(source_id, current_user.id, payload.next_review_in_days)
    await db.commit()
    return {"data": ContentSourceOut.model_validate(src).model_dump(mode="json")}


@router.get(
    "/sources/needs-review",
    response_model=dict,
    summary="List sources whose next_review_due is in the past (admin/instructor)",
    operation_id="content_sources_needs_review",
)
async def needs_review_endpoint(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source_type: str | None = None,
    aircraft_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    if not (set(current_user.roles) & {"admin", "instructor"}):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    svc = ContentService(db)
    rows = await svc.list_needs_review(
        source_type=source_type, aircraft_id=aircraft_id, limit=limit, offset=offset
    )
    return {"data": [ContentSourceOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.get(
    "/sources/expiring-soon",
    response_model=dict,
    summary="List sources whose next_review_due falls within `within_days` (admin/instructor)",
    operation_id="content_sources_expiring_soon",
)
async def expiring_soon_endpoint(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    within_days: int | None = None,
    source_type: str | None = None,
    aircraft_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    if not (set(current_user.roles) & {"admin", "instructor"}):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    from app.config import get_settings
    s = get_settings()
    window = within_days if within_days is not None else s.CONTENT_EXPIRING_SOON_WINDOW_DAYS
    svc = ContentService(db)
    rows = await svc.list_expiring_soon(
        within_days=window, source_type=source_type, aircraft_id=aircraft_id, limit=limit, offset=offset
    )
    return {"data": [ContentSourceOut.model_validate(r).model_dump(mode="json") for r in rows]}
```

Make sure `ContentSourceOut` is imported at the top of the file. If not, add: `from app.modules.content.schemas import ContentSourceOut`.

- [ ] **Step 2: Verify app starts + endpoints registered**

```bash
.venv/Scripts/python.exe -c "
from app.main import app
ops = set()
for path, methods in app.openapi()['paths'].items():
    for m in methods.values():
        if isinstance(m, dict) and 'operationId' in m:
            ops.add(m['operationId'])
expected = {'content_sources_mark_reviewed','content_sources_needs_review','content_sources_expiring_soon'}
print('all 3 registered:', expected.issubset(ops))
"
```
Expected: `True`

- [ ] **Step 3: Run unit tests + ruff**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/ --no-cov -q 2>&1 | tail -3`
Expected: 60+ passed (no regressions).

Run: `.venv/Scripts/python.exe -m ruff check . | tail -3`
Expected: `All checks passed!` (auto-fix any sorting issues with `--fix` if needed before committing).

- [ ] **Step 4: Commit**

```bash
git add app/modules/content/router.py
git commit -m "feat(content): mark-reviewed + needs-review + expiring-soon endpoints"
```

---

# Phase D — Tests + push + PR

## Task D1: Unit test for `_cadence_for`

**Files:** Create `tests/unit/test_content_lifecycle.py`

- [ ] **Step 1: Write the test**

```python
from app.modules.content.service import _cadence_for


def test_cadence_for_known_source_types():
    assert _cadence_for("fcom") == 180
    assert _cadence_for("qrh") == 90
    assert _cadence_for("amm") == 180
    assert _cadence_for("sop") == 90
    assert _cadence_for("syllabus") == 60


def test_cadence_for_unknown_source_type_falls_back_to_default():
    assert _cadence_for("manual") == 90  # default
    assert _cadence_for("") == 90
```

- [ ] **Step 2: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_content_lifecycle.py -v --no-cov`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_content_lifecycle.py
git commit -m "test(content): unit tests for _cadence_for cadence resolution"
```

---

## Task D2: Integration tests for endpoints

**Files:** Create `tests/integration/test_content_lifecycle_endpoints.py`

- [ ] **Step 1: Write the test file**

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.content.models import ContentSource


async def _make_user(db_session, role="instructor"):
    u = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Test",
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def _make_source(db_session, source_type="fcom", days_until_review=None, status="approved"):
    src = ContentSource(
        id=uuid.uuid4(),
        source_type=source_type,
        title=f"Test-{uuid.uuid4().hex[:6]}",
        version="Rev 1",
        status=status,
    )
    if days_until_review is not None:
        src.next_review_due = datetime.now(UTC) + timedelta(days=days_until_review)
    db_session.add(src)
    await db_session.commit()
    return src


def _override_user(real_user, role="instructor"):
    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    fake = CurrentUser(id=str(real_user.id), roles=[role], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake


def _clear_user_override():
    from app.main import app
    from app.modules.auth.deps import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


async def test_mark_reviewed_advances_next_review_due(client, db_session):
    user = await _make_user(db_session)
    src = await _make_source(db_session, source_type="fcom")
    _override_user(user)
    try:
        before = datetime.now(UTC)
        resp = await client.post(f"/api/v1/content/sources/{src.id}/mark-reviewed", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["last_reviewed_at"] is not None
        assert data["last_reviewed_by"] == str(user.id)
        # next_review_due should be ~180 days out (FCOM cadence)
        new_due = datetime.fromisoformat(data["next_review_due"].replace("Z", "+00:00"))
        assert (new_due - before).days >= 175
        assert (new_due - before).days <= 185
    finally:
        _clear_user_override()


async def test_mark_reviewed_with_override_days(client, db_session):
    user = await _make_user(db_session)
    src = await _make_source(db_session, source_type="fcom")
    _override_user(user)
    try:
        before = datetime.now(UTC)
        resp = await client.post(
            f"/api/v1/content/sources/{src.id}/mark-reviewed",
            json={"next_review_in_days": 30},
        )
        assert resp.status_code == 200, resp.text
        new_due = datetime.fromisoformat(resp.json()["data"]["next_review_due"].replace("Z", "+00:00"))
        assert (new_due - before).days >= 28
        assert (new_due - before).days <= 32
    finally:
        _clear_user_override()


async def test_needs_review_returns_overdue_only(client, db_session):
    user = await _make_user(db_session)
    overdue = await _make_source(db_session, days_until_review=-5)  # 5 days overdue
    not_yet = await _make_source(db_session, days_until_review=30)
    _override_user(user)
    try:
        resp = await client.get("/api/v1/content/sources/needs-review")
        assert resp.status_code == 200, resp.text
        ids = {row["id"] for row in resp.json()["data"]}
        assert str(overdue.id) in ids
        assert str(not_yet.id) not in ids
    finally:
        _clear_user_override()


async def test_expiring_soon_respects_window(client, db_session):
    user = await _make_user(db_session)
    soon = await _make_source(db_session, days_until_review=7)
    later = await _make_source(db_session, days_until_review=30)
    _override_user(user)
    try:
        resp = await client.get("/api/v1/content/sources/expiring-soon?within_days=14")
        assert resp.status_code == 200, resp.text
        ids = {row["id"] for row in resp.json()["data"]}
        assert str(soon.id) in ids
        assert str(later.id) not in ids
    finally:
        _clear_user_override()


async def test_endpoints_require_role(client, db_session):
    user = await _make_user(db_session)
    _override_user(user, role="trainee")
    try:
        for url in [
            "/api/v1/content/sources/needs-review",
            "/api/v1/content/sources/expiring-soon",
        ]:
            resp = await client.get(url)
            assert resp.status_code == 403, f"{url}: {resp.text}"
    finally:
        _clear_user_override()
```

- [ ] **Step 2: Verify collection**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_content_lifecycle_endpoints.py --collect-only --no-cov 2>&1 | tail -5`
Expected: 5 tests collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_content_lifecycle_endpoints.py
git commit -m "test(content): integration tests for lifecycle endpoints"
```

---

## Task D3: Final ruff + push + PR

**Files:** none new

- [ ] **Step 1: Final gates**

Run:
- `.venv/Scripts/python.exe -m ruff check . --fix | tail -3` — `All checks passed!`
- `.venv/Scripts/python.exe -m pytest tests/unit/ --no-cov -q | tail -3` — 62+ passed (60 from before + 2 new lifecycle unit)
- `.venv/Scripts/python.exe -c "from app.main import app; print('ok')"` — `ok`

- [ ] **Step 2: Push**

```bash
git push -u origin feat/content-lifecycle-shreyansh
```

- [ ] **Step 3: Open PR (NOT draft)**

```bash
gh pr create --title "Content Lifecycle Tracking--shreyansh" --body "$(cat <<'EOF'
## Summary

Adds lifecycle tracking to `ContentSource` per Excel R73 (P1). Tracks when each
source was last reviewed, when it's next due, and when it should be deprecated.

Spec: docs/superpowers/specs/2026-04-29-content-lifecycle-design.md

### What's included
- 4 new columns on `content_sources`: `last_reviewed_at`, `last_reviewed_by`,
  `next_review_due`, `deprecation_date`. All nullable. Indexes on the two
  date columns for the new endpoints.
- 3 new endpoints under `/api/v1/content/sources/`:
  - `POST /{id}/mark-reviewed` — bumps last-reviewed + advances next-review
  - `GET /needs-review` — overdue sources (status=approved, next_review_due <= now)
  - `GET /expiring-soon?within_days=14` — coming due in the window
- `ContentService.approve_source()` now sets `next_review_due` on first approval
  using a per-source-type cadence (FCOM 180d, QRH 90d, AMM 180d, SOP 90d,
  syllabus 60d, default 90d). Configurable via 7 new settings.
- ContentSourceOut schema gains the 4 lifecycle fields.

### Coordination
- This branch is stacked on \`feat/rag-foundation\` (PR #1) — RAG models are
  hard deps. Will rebase onto main when PR #1 merges.
- @sachinglimmora — touches your \`content/\` module surgically: 4 column
  adds (additive migration), tweak to \`approve_source\` (sets next_review_due
  on first approval; doesn't touch existing rows). Existing approved sources
  have NULL next_review_due — admin can backfill via mark-reviewed.

## Test plan
- [x] 2 unit tests for cadence resolution
- [x] 5 integration tests for endpoints + role gate
- [x] Ruff clean, 62 unit tests pass, app starts
- [x] OpenAPI shows 3 new operationIds
- [ ] CI green (verify after push)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Wait + verify CI**

Wait ~110s, then `gh pr view <PR_NUMBER> --json statusCheckRollup,mergeable | head -10`. If green, done. If red, follow the iterate pattern (get failure logs, fix, push, repeat — max 2 fix cycles).
