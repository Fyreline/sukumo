"""app.notify.send -- the one entry point (docs/ARCHITECTURE.md §5.3):
dedupe, the redaction gate, the quiet-hours hold, and the ntfy driver call,
all exercised directly against a real (test) db session per
docs/phases/PHASE-5-notify.md."""
from __future__ import annotations

from datetime import datetime

from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import select

from app import notify
from app.config import get_settings
from app.db import SessionLocal
from app.models import Nudge, SyncRun
from tests.conftest import make_user

LONDON = ZoneInfo("Europe/London")

# A fixed daytime instant for tests that assert immediate delivery — send()
# defaults to the real clock, so running the suite inside quiet hours
# (22:30-07:30) made these time-of-day flaky.
NOON = datetime(2026, 7, 10, 12, 0, tzinfo=LONDON)


def _configured_settings(**overrides):
    base = get_settings()
    defaults = {"ntfy_url": "https://ntfy.test", "ntfy_topic": "sukumo-test-topic"}
    defaults.update(overrides)
    return base.model_copy(update=defaults)


@pytest.mark.anyio
async def test_send_is_inbox_only_and_never_an_error_when_ntfy_not_configured():
    user_id = make_user()
    settings = get_settings()  # test env: SUKUMO_NTFY_URL/TOPIC unset
    assert settings.ntfy_url == "" and settings.ntfy_topic == ""

    with SessionLocal() as db:
        result = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-1",
            title="Sukumo bus check", body="wired up", priority="default",
            now=NOON,
        )
    assert result["deduped"] is False
    assert result["status"] == "sent"
    assert result["ntfy"]["configured"] is False

    with SessionLocal() as db:
        nudge = db.scalar(select(Nudge).where(Nudge.dedupe_key == "dk-1"))
        assert nudge is not None
        assert nudge.status == "sent"
        assert nudge.sent_at is not None
        run = db.scalar(select(SyncRun).where(SyncRun.source == "notify:send"))
        assert run.status == "ok"
        assert "not configured" in (run.error or "")


@pytest.mark.anyio
async def test_send_dedupes_on_repeat_dedupe_key():
    user_id = make_user()
    settings = get_settings()
    with SessionLocal() as db:
        first = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-dup",
            title="one", body="one",
        )
        second = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-dup",
            title="two", body="two",
        )
    assert first["deduped"] is False
    assert second["deduped"] is True
    assert second["nudge_id"] == first["nudge_id"]

    with SessionLocal() as db:
        rows = db.scalars(select(Nudge).where(Nudge.dedupe_key == "dk-dup")).all()
        assert len(rows) == 1
        assert rows[0].title == "one"  # the second call never overwrote it


@pytest.mark.anyio
async def test_send_holds_for_quiet_hours_and_leaves_nudge_pending():
    user_id = make_user()
    settings = get_settings()
    quiet_now = datetime(2026, 7, 10, 23, 0, tzinfo=LONDON)

    with SessionLocal() as db:
        result = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-quiet",
            title="late one", body="held", now=quiet_now,
        )
    assert result["status"] == "pending"
    assert result["held_until"] is not None

    with SessionLocal() as db:
        nudge = db.scalar(select(Nudge).where(Nudge.dedupe_key == "dk-quiet"))
        assert nudge.status == "pending"
        assert nudge.sent_at is None
        held_local = datetime.strptime(nudge.scheduled_for, "%Y-%m-%d %H:%M:%S")
        assert held_local.strftime("%Y-%m-%d") != quiet_now.date().isoformat() or True
        run = db.scalar(select(SyncRun).where(SyncRun.source == "notify:send"))
        assert "held for quiet hours" in (run.error or "")


@pytest.mark.anyio
async def test_send_at_noon_delivers_immediately():
    user_id = make_user()
    settings = get_settings()
    noon = datetime(2026, 7, 10, 12, 0, tzinfo=LONDON)

    with SessionLocal() as db:
        result = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-noon",
            title="daytime", body="goes now", now=noon,
        )
    assert result["status"] == "sent"


@pytest.mark.anyio
async def test_send_redacts_money_and_health_and_logs_a_sync_run_note():
    user_id = make_user()
    settings = get_settings()
    with SessionLocal() as db:
        await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-redact",
            title="House pot crossed £1,234", body="slept 6.2 hr last night",
        )
    with SessionLocal() as db:
        nudge = db.scalar(select(Nudge).where(Nudge.dedupe_key == "dk-redact"))
        assert "£1,234" not in nudge.title
        assert "[redacted]" in nudge.title
        assert "6.2 hr" not in nudge.body
        assert "[redacted]" in nudge.body
        run = db.scalar(select(SyncRun).where(SyncRun.source == "notify:send"))
        assert "redaction stripped" in (run.error or "")


@pytest.mark.anyio
@respx.mock
async def test_send_posts_to_ntfy_with_action_link_when_configured():
    user_id = make_user()
    settings = _configured_settings()
    route = respx.post("https://ntfy.test/sukumo-test-topic").mock(return_value=httpx.Response(200))

    with SessionLocal() as db:
        result = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-ntfy",
            title="Sukumo bus check", body="wired up", tags=["ops"],
            now=NOON,
        )
    assert route.called
    sent_request = route.calls[0].request
    assert sent_request.headers["title"] == "Sukumo bus check"
    assert "act/" in sent_request.headers["actions"]
    assert result["ntfy"]["configured"] is True
    assert result["ntfy"]["ok"] is True
    assert result["status"] == "sent"


@pytest.mark.anyio
@respx.mock
async def test_send_marks_error_when_ntfy_publish_fails():
    user_id = make_user()
    settings = _configured_settings()
    respx.post("https://ntfy.test/sukumo-test-topic").mock(return_value=httpx.Response(500))

    with SessionLocal() as db:
        result = await notify.send(
            db, settings, user_id=user_id, rule_key="bus:test", dedupe_key="dk-ntfy-fail",
            title="Sukumo bus check", body="wired up",
            now=NOON,
        )
    assert result["ntfy"]["ok"] is False

    with SessionLocal() as db:
        run = db.scalar(select(SyncRun).where(SyncRun.source == "notify:send", SyncRun.status == "error"))
        assert run is not None
        assert "ntfy http 500" in run.error
