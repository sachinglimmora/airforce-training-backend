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
