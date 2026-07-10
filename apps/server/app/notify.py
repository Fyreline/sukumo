"""The notification bus core — docs/API.md §5, docs/phases/PHASE-5-notify.md.

Owns the channel drivers (ntfy v1, webpush later) and the redaction gate:
notification text carries categories, not values (docs/ARCHITECTURE.md §5.2).
Coach rules and ``routers/notify.py`` are the only callers of ``send()``
(docs/ARCHITECTURE.md §5.3).

Layout of this module:

- **Redaction gate** — ``check_redaction`` (test-time: raises) and
  ``redact`` (runtime: strips + reports, never raises).
- **Quiet hours** — ``quiet_hours_hold`` (COACH.md §2): a pure function of
  ``now``, so it's unit-testable with an explicit frozen instant instead of
  a clock-mocking library.
- **Channel drivers** — ``InboxDriver`` (always satisfied by the nudges row
  itself) and ``NtfyDriver`` (httpx POST to ``{NTFY_URL}/{NTFY_TOPIC}``).
- **Action tokens** — ``issue_action_token``/``verify_action_token``
  (AUTH.md §4) + a rule_key-keyed callback registry (the Phase 6 hook: a
  rule like 'reading' can register extra work — e.g. writing the
  habit_event — that runs when its nudge's action link is tapped).
- **send()** — the single entry point that ties all of the above together.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Nudge, SyncRun

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")


# ============================================================================
# Redaction gate (docs/ARCHITECTURE.md §5.2 — a HARD rule)
# ============================================================================
class RedactionError(ValueError):
    """Raised by ``check_redaction`` when text contains a money/health-shaped
    value. This is the test-time half of the gate (docs/phases/PHASE-5-notify.md
    acceptance: "a test template containing '£1,234' or '6.2 hr' fails CI") —
    coach rule authors (Phase 6) write one pytest per template asserting this
    raises. ``send()`` below never raises it; see ``redact()``."""


# Money: currency symbols, comma-grouped 4+ digit numbers, and the word
# 'pence' (Kakeibo's own unit). Health: decimal-hour figures ('6.2 hr'),
# weight (kg), heart rate (bpm), energy (kcal). Day counts ('4 days'), small
# integers, plain ISO dates ('2026-07-10') and percentages-as-labels ('25%')
# match none of these and always pass — the allowlist is everything NOT
# shaped like money or a health measurement.
_MONEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("money:currency-symbol", re.compile(r"[£$]\s?\d")),
    ("money:comma-grouped", re.compile(r"\b\d{1,3}(?:,\d{3})+\b")),
    ("money:pence", re.compile(r"\bpence\b", re.IGNORECASE)),
]
_HEALTH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("health:decimal-hours", re.compile(r"\b\d+\.\d+\s?(?:hrs?|hours?)\b", re.IGNORECASE)),
    ("health:kg", re.compile(r"\b\d+(?:\.\d+)?\s?kg\b", re.IGNORECASE)),
    ("health:bpm", re.compile(r"\b\d+(?:\.\d+)?\s?bpm\b", re.IGNORECASE)),
    ("health:kcal", re.compile(r"\b\d+(?:\.\d+)?\s?kcal\b", re.IGNORECASE)),
]
_ALL_PATTERNS: list[tuple[str, re.Pattern[str]]] = _MONEY_PATTERNS + _HEALTH_PATTERNS


def redaction_violations(text: str) -> list[str]:
    """Every gate pattern name that matches ``text`` — empty means clean."""
    return [name for name, pattern in _ALL_PATTERNS if pattern.search(text)]


def check_redaction(text: str) -> None:
    """Test-time gate: raises ``RedactionError`` if ``text`` contains a
    money/health-shaped value. Never called from the delivery path — that's
    ``redact()`` below, which strips instead of raising."""
    violations = redaction_violations(text)
    if violations:
        raise RedactionError(f"redaction gate rejected {violations} in {text!r}")


def redact(text: str) -> tuple[str, list[str]]:
    """Runtime gate: never raises. Returns ``(safe_text, violations)`` with
    every matched span replaced by ``'[redacted]'`` — ``send()`` logs an
    error and writes a ``sync_runs`` note for a non-empty violations list
    rather than blocking delivery (docs/phases/PHASE-5-notify.md: "stripped
    at runtime with an error log")."""
    violations = redaction_violations(text)
    safe = text
    for _name, pattern in _ALL_PATTERNS:
        safe = pattern.sub("[redacted]", safe)
    return safe, violations


# ============================================================================
# Quiet hours (docs/COACH.md §2 — the delivery-layer hold)
# ============================================================================
def _parse_quiet_hours(spec: str) -> tuple[dt_time, dt_time]:
    start_s, end_s = spec.split("-")

    def _parse(t: str) -> dt_time:
        h, m = t.strip().split(":")
        return dt_time(int(h), int(m))

    return _parse(start_s), _parse(end_s)


def quiet_hours_hold(now: datetime, quiet_hours: str) -> datetime | None:
    """``None`` if ``now`` (any tz-aware datetime) falls outside the
    quiet-hours window in Europe/London; otherwise the aware UTC datetime at
    which the window ends — i.e. when delivery may proceed. A pure function
    of ``now``, so tests pass an explicit frozen instant instead of needing a
    clock-mocking library (docs/phases/PHASE-5-notify.md: "unit-test with
    frozen clock")."""
    start, end = _parse_quiet_hours(quiet_hours)
    local_now = now.astimezone(LONDON)
    t = local_now.time()
    wraps = start > end  # e.g. the default 22:30-07:30 crosses midnight
    inside = (t >= start or t < end) if wraps else (start <= t < end)
    if not inside:
        return None

    end_local = datetime.combine(local_now.date(), end, tzinfo=LONDON)
    if end_local <= local_now:
        end_local += timedelta(days=1)
    return end_local.astimezone(timezone.utc)


# ============================================================================
# Channel drivers (docs/API.md §5)
# ============================================================================
_NTFY_PRIORITY = {"low": "low", "default": "default", "high": "high"}


class NtfyDriver:
    """Channel v1: httpx POST to ``{SUKUMO_NTFY_URL}/{SUKUMO_NTFY_TOPIC}``
    with title/body/priority/tags headers and an ntfy action button hitting
    the ``act/{token}`` URL. Missing config → ``configured: False``, never an
    exception — ``send()`` turns that into "inbox-only, never an error"
    (docs/phases/PHASE-5-notify.md build item 1)."""

    name = "ntfy"

    async def deliver(
        self,
        *,
        title: str,
        body: str,
        priority: str,
        tags: list[str],
        action_url: str | None,
        settings: Settings,
    ) -> dict:
        if not settings.ntfy_url or not settings.ntfy_topic:
            return {
                "configured": False,
                "ok": False,
                "detail": "SUKUMO_NTFY_URL/SUKUMO_NTFY_TOPIC not set",
            }

        url = f"{settings.ntfy_url.rstrip('/')}/{settings.ntfy_topic}"
        # Header values must be bytes if they might contain non-ASCII (a
        # template's one allowed emoji, docs/COACH.md §5) — httpx raises
        # UnicodeEncodeError encoding a non-ASCII str header otherwise.
        headers: dict[str, bytes] = {
            "Title": title.encode("utf-8"),
            "Priority": _NTFY_PRIORITY.get(priority, "default").encode("ascii"),
        }
        if tags:
            headers["Tags"] = ",".join(tags).encode("utf-8")
        if action_url:
            # ntfy's header shorthand for one action button: "view" opens
            # the URL in the phone's browser on tap — exactly the act/{token}
            # link (AUTH.md §4).
            headers["Actions"] = f"view, Open, {action_url}".encode("utf-8")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, content=body.encode("utf-8"), headers=headers)
        return {"configured": True, "ok": response.status_code < 300, "status_code": response.status_code}


class InboxDriver:
    """The inbox channel is always satisfied by the nudges row itself
    (routers/nudges.py reads it directly) — this class only completes the
    driver interface described in ARCHITECTURE.md §1."""

    name = "inbox"

    async def deliver(self, **_kwargs: object) -> dict:
        return {"configured": True, "ok": True}


# ============================================================================
# Action tokens (docs/AUTH.md §4) + the Phase-6 callback hook
# ============================================================================
class ActionTokenError(ValueError):
    """Raised by ``verify_action_token`` for a malformed or tampered token —
    routers/nudges.py turns this into a 401."""


def _token_key(settings: Settings) -> bytes:
    return settings.jwt_secret.encode("utf-8")


def issue_action_token(nudge_id: int, settings: Settings, ttl_hours: int = 24 * 7) -> str:
    """``HMAC(JWT_SECRET, nudge_id + expiry)`` (AUTH.md §4). The 7-day TTL is
    generous — a nudge realistically goes stale long before then — because
    the nudge's own ``status`` column, not the token's expiry, is what
    actually blocks re-use (see ``verify_action_token``'s ``expired`` return
    and routers/nudges.py's idempotent-second-hit handling)."""
    expiry = int((datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp())
    payload = f"{nudge_id}.{expiry}".encode("utf-8")
    sig = hmac.new(_token_key(settings), payload, hashlib.sha256).hexdigest()
    raw = f"{nudge_id}.{expiry}.{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_action_token(token: str, settings: Settings) -> tuple[int, bool]:
    """Returns ``(nudge_id, expired)``. Raises ``ActionTokenError`` for a
    malformed or tampered token (any HMAC mismatch or unparsable shape)."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        nudge_id_s, expiry_s, sig = raw.split(".")
        int(nudge_id_s)
        int(expiry_s)
    except Exception as exc:  # noqa: BLE001 -- any malformed shape is the same 401
        raise ActionTokenError("malformed action token") from exc

    expected = hmac.new(
        _token_key(settings), f"{nudge_id_s}.{expiry_s}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ActionTokenError("bad action token signature")

    expired = datetime.now(timezone.utc).timestamp() > int(expiry_s)
    return int(nudge_id_s), expired


ActionCallback = Callable[[Session, Nudge], None]
_action_callbacks: dict[str, ActionCallback] = {}


def register_action_callback(rule_key: str, callback: ActionCallback) -> None:
    """The Phase 6 hook: a rule (e.g. 'reading') registers extra work that
    runs the moment its nudge's action link is tapped — COACH.md §3.3's "the
    ntfy action button hits act/{token} which both marks actioned AND writes
    the habit_event". The default (no registration) is exactly what
    routers/nudges.py already does regardless: mark the nudge 'actioned'."""
    _action_callbacks[rule_key] = callback


def get_action_callback(rule_key: str) -> ActionCallback | None:
    return _action_callbacks.get(rule_key)


# ============================================================================
# send() — the one entry point (docs/ARCHITECTURE.md §5.3)
# ============================================================================
async def send(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    rule_key: str,
    dedupe_key: str,
    title: str,
    body: str,
    priority: str = "default",
    tags: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    """Writes one ``nudges`` row (the inbox delivery — DATA_MODEL §4) and
    forwards to the ntfy driver, applying the redaction gate and the
    quiet-hours hold first. ``dedupe_key`` is UNIQUE — a repeat is a no-op
    that returns the existing row untouched (idempotent by construction,
    matching COACH.md §1's "a crashed tick re-run cannot double-send").

    Only two callers are allowed to reach this (ARCHITECTURE §5.3):
    ``routers/notify.py``'s bus endpoint, and — from Phase 6 —
    ``coach/engine.py``.
    """
    now = now or datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    tags = tags or []

    existing = session.scalar(select(Nudge).where(Nudge.dedupe_key == dedupe_key))
    if existing is not None:
        return {"nudge_id": existing.id, "status": existing.status, "deduped": True}

    safe_title, title_violations = redact(title)
    safe_body, body_violations = redact(body)
    violations = title_violations + body_violations
    if violations:
        logger.error(
            "notify.send: redaction gate stripped content for rule_key=%s dedupe_key=%s violations=%s",
            rule_key,
            dedupe_key,
            violations,
        )

    hold_until = quiet_hours_hold(now, settings.quiet_hours)
    scheduled_for = hold_until.strftime("%Y-%m-%d %H:%M:%S") if hold_until else now_str

    nudge = Nudge(
        rule_key=rule_key,
        user_id=user_id,
        dedupe_key=dedupe_key,
        scheduled_for=scheduled_for,
        channel="ntfy",
        title=safe_title,
        body=safe_body,
        status="pending",
        context_json=json.dumps({"priority": priority, "tags": tags}),
    )
    session.add(nudge)
    session.commit()
    session.refresh(nudge)

    redaction_note = f"redaction stripped {len(violations)} value(s): {violations}" if violations else None

    if hold_until is not None:
        # Quiet hours (COACH.md §2): the inbox row above already exists; the
        # phone push waits for scheduled_for — a later coach tick (Phase 6)
        # or a retried send() delivers it then. Never silent about the hold:
        session.add(
            SyncRun(
                source="notify:send",
                started_at=now_str,
                finished_at=now_str,
                status="ok",
                items=0,
                error=(
                    f"held for quiet hours until {scheduled_for}"
                    + (f"; {redaction_note}" if redaction_note else "")
                ),
            )
        )
        session.commit()
        return {"nudge_id": nudge.id, "status": "pending", "held_until": scheduled_for, "deduped": False}

    action_url = f"{settings.public_api_base.rstrip('/')}/api/nudges/act/{issue_action_token(nudge.id, settings)}"
    driver_result = await NtfyDriver().deliver(
        title=safe_title, body=safe_body, priority=priority, tags=tags, action_url=action_url, settings=settings
    )

    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    nudge.status = "sent"
    nudge.sent_at = finished_at
    if driver_result["configured"]:
        run_status = "ok" if driver_result["ok"] else "error"
        run_error = None if driver_result["ok"] else f"ntfy http {driver_result.get('status_code')}"
    else:
        # Missing ntfy config -> inbox-only, sync-noted, never an error
        # (docs/phases/PHASE-5-notify.md build item 1).
        run_status = "ok"
        run_error = "ntfy not configured -- inbox-only"
    if redaction_note:
        run_error = f"{run_error}; {redaction_note}" if run_error else redaction_note

    session.add(
        SyncRun(
            source="notify:send",
            started_at=now_str,
            finished_at=finished_at,
            status=run_status,
            items=1,
            error=run_error,
        )
    )
    session.commit()

    return {"nudge_id": nudge.id, "status": nudge.status, "ntfy": driver_result, "deduped": False}
