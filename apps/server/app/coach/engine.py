"""The coach tick — docs/COACH.md §1, docs/ARCHITECTURE.md §2-3, §5.3.

Strict order (COACH §1): **poll → evaluate → gate → deliver → record**.

- **poll**  scripts/poll_sources.run — siblings/weather/calendar/habit-evidence
  refresh, so rules read fresh snapshots (one agent, not two: ARCHITECTURE §2).
- **evaluate**  every registered rule, ``(now, db) -> RuleResult``. A rule that
  is unconfigured/stale/disabled returns a skip status, counted, never a nudge.
- **gate**  per proposal, in order: dedupe_key already present → drop; per-rule
  cooldown after a *dismissed* nudge → drop; moment slept through past its
  expiry horizon → write ``expired``; daily cap reached → keep highest priority,
  demote the rest to inbox-only.
- **deliver**  due push proposals via ``notify.send`` (which owns the redaction
  gate + the quiet-hours hold — a 23:00 proposal lands pending for 07:30);
  inbox-only + expired rows are written directly by the engine. Pending nudges
  whose held/snoozed moment has arrived are pushed too.
- **record**  one ``sync_runs`` row ``coach:tick`` with per-stage counts.

Idempotent by construction (COACH §1): the ``dedupe_key`` UNIQUE constraint is
the backstop, so a re-run against the same DB touches no new rows.

docs/ARCHITECTURE.md §5.3 (hard rule): the coach creates nudges ONLY here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notify
from ..config import Settings, get_settings
from ..db import SessionLocal
from ..models import Nudge, SyncRun
from . import briefing as briefing_module
from . import config as coach_config
from .proposals import PRIORITY_RANK, NudgeProposal, Rule, utc_str
from .rules import load_rules

logger = logging.getLogger(__name__)

BRIEFING_RULE_KEY = "morning-briefing"


def _local_date_str(session_ts: str) -> str:
    from .proposals import LONDON, parse_utc

    return parse_utc(session_ts).astimezone(LONDON).date().isoformat()


def _pushed_today(session: Session, now: datetime) -> int:
    """How many ntfy pushes already went out today (Europe/London) — the daily
    cap counts against this (COACH §2)."""
    from .proposals import LONDON

    today = now.astimezone(LONDON).date().isoformat()
    rows = session.scalars(
        select(Nudge).where(Nudge.channel == "ntfy", Nudge.sent_at.is_not(None))
    ).all()
    return sum(1 for n in rows if n.sent_at and _local_date_str(n.sent_at) == today)


def _cooldown_active(session: Session, rule: Rule, now: datetime) -> bool:
    """A *dismissed* nudge silences that rule's re-fire for its cooldown
    (COACH §2). A delivered ('sent') nudge does not — the next cycle is a
    legitimately new day; an 'actioned' one reset the condition already."""
    from .proposals import parse_utc

    last = session.scalars(
        select(Nudge).where(Nudge.rule_key == rule.key).order_by(Nudge.created_at.desc(), Nudge.id.desc())
    ).first()
    if last is None or last.status != "dismissed":
        return False
    age_h = (now - parse_utc(last.created_at)).total_seconds() / 3600.0
    return age_h < rule.cooldown_hours


def _write_nudge(session: Session, proposal: NudgeProposal, now: datetime, *, status: str, channel: str) -> Nudge:
    """Insert a nudge row directly (the inbox-only / expired paths — never a
    push). Redaction still applies (ARCHITECTURE §5.2)."""
    safe_title, _ = notify.redact(proposal.title)
    safe_body, _ = notify.redact(proposal.body)
    now_str = utc_str(now)
    nudge = Nudge(
        rule_key=proposal.rule_key,
        user_id=proposal.context.get("user_id"),
        dedupe_key=proposal.dedupe_key,
        scheduled_for=utc_str(proposal.scheduled_for),
        sent_at=now_str if status in ("sent", "expired") else None,
        channel=channel,
        title=safe_title,
        body=safe_body,
        status=status,
        context_json=json.dumps({"priority": proposal.priority, "tags": proposal.tags}),
    )
    session.add(nudge)
    session.commit()
    session.refresh(nudge)
    return nudge


async def _push_existing(session: Session, settings: Settings, nudge: Nudge, now: datetime) -> None:
    """Deliver a nudge row that was previously held (quiet hours) or snoozed and
    whose moment has now arrived — mirrors ``notify.send``'s delivery tail."""
    action_url = (
        f"{settings.public_api_base.rstrip('/')}/api/nudges/act/{notify.issue_action_token(nudge.id, settings)}"
    )
    ctx = json.loads(nudge.context_json or "{}")
    result = await notify.NtfyDriver().deliver(
        title=nudge.title,
        body=nudge.body,
        priority=ctx.get("priority", "default"),
        tags=ctx.get("tags", []),
        action_url=action_url,
        settings=settings,
    )
    nudge.status = "sent"
    nudge.sent_at = utc_str(now)
    session.commit()
    logger.info("coach: redelivered held/snoozed nudge id=%s configured=%s", nudge.id, result.get("configured"))


async def _redeliver_due(session: Session, settings: Settings, now: datetime) -> int:
    """Pending (held) or snoozed nudges whose scheduled moment has arrived
    re-enter delivery here (COACH §1.4)."""
    now_str = utc_str(now)
    delivered = 0
    pending = session.scalars(
        select(Nudge).where(Nudge.status == "pending", Nudge.scheduled_for <= now_str)
    ).all()
    snoozed = session.scalars(
        select(Nudge).where(Nudge.status == "snoozed", Nudge.snoozed_until.is_not(None), Nudge.snoozed_until <= now_str)
    ).all()
    for nudge in [*pending, *snoozed]:
        await _push_existing(session, settings, nudge, now)
        delivered += 1
    return delivered


def _cap_keep_order(p: NudgeProposal) -> tuple:
    # Exempt (the briefing anchor) first, then highest priority, then earliest
    # intended minute — a stable, deterministic keep order for the daily cap.
    return (0 if p.cap_exempt else 1, -PRIORITY_RANK.get(p.priority, 1), p.scheduled_for)


async def tick(session: Session, settings: Settings, now: datetime | None = None, *, poll: bool = True) -> dict:
    """One coach cycle. Returns the per-stage counts also written to sync_runs."""
    now = now or datetime.now(timezone.utc)
    started_at = utc_str(now)
    counts: dict[str, int] = {
        "evaluated": 0,
        "proposed": 0,
        "deduped": 0,
        "cooldown": 0,
        "expired": 0,
        "delivered": 0,
        "held": 0,
        "inbox": 0,
        "capped_inbox": 0,
        "not_configured": 0,
        "stale": 0,
        "disabled": 0,
        "error": 0,
        "redelivered": 0,
    }

    # 1. Poll first (COACH §1). Failures degrade to stale, never crash the tick.
    poll_result = None
    if poll:
        try:
            from scripts import poll_sources

            poll_result = await poll_sources.run(session)
        except Exception as exc:  # noqa: BLE001
            logger.error("coach: poll stage failed, continuing with existing snapshots: %s", exc)
            poll_result = {"error": str(exc)}

    primary = coach_config.primary_user(session)
    if primary is None:
        _record(session, started_at, now, counts, status="not_configured", note="no primary user")
        return {"status": "not_configured", "counts": counts}

    effective = settings.model_copy(update={"quiet_hours": coach_config.quiet_hours(session, settings)})

    # 2. Evaluate every rule.
    proposals: list[NudgeProposal] = []
    briefing_stub: NudgeProposal | None = None
    for rule in load_rules():
        counts["evaluated"] += 1
        if not coach_config.rule_enabled(session, rule.key):
            counts["disabled"] += 1
            continue
        result = rule.run(now, session)
        if result.status == "not_configured":
            counts["not_configured"] += 1
        elif result.status == "stale":
            counts["stale"] += 1
        elif result.status == "error":
            counts["error"] += 1
            logger.error("coach: rule %s errored: %s", rule.key, result.note)
        for p in result.proposals:
            p.context.setdefault("user_id", primary.id)
            if p.rule_key == BRIEFING_RULE_KEY:
                briefing_stub = p
            else:
                proposals.append(p)
    counts["proposed"] = len(proposals) + (1 if briefing_stub else 0)

    # 3. Compose the briefing FROM the same proposal stream (COACH §3.1) and
    #    put it at the head so it's the day's first push and cap-exempt.
    if briefing_stub is not None:
        content_md, push_body = briefing_module.compose(session, now, effective, proposals)
        briefing_stub.body = push_body
        briefing_stub.context["content_md"] = content_md
        proposals.insert(0, briefing_stub)

    # 4. Gate: dedupe -> cooldown -> expiry -> cap.
    rules_by_key = {r.key: r for r in load_rules()}
    deliverable: list[NudgeProposal] = []
    for p in proposals:
        if session.scalar(select(Nudge).where(Nudge.dedupe_key == p.dedupe_key)) is not None:
            counts["deduped"] += 1
            continue
        rule = rules_by_key.get(p.rule_key)
        if rule is not None and _cooldown_active(session, rule, now):
            counts["cooldown"] += 1
            continue
        if p.expiry is not None and now > p.scheduled_for + p.expiry:
            _write_nudge(session, p, now, status="expired", channel="inbox")
            counts["expired"] += 1
            continue
        deliverable.append(p)

    # daily cap (COACH §2): keep highest priority, demote the rest to inbox-only.
    budget = coach_config.daily_cap(session) - _pushed_today(session, now)
    for p in sorted(deliverable, key=_cap_keep_order):
        if not p.push:
            _write_nudge(session, p, now, status="sent", channel="inbox")
            counts["inbox"] += 1
            if p.rule_key == BRIEFING_RULE_KEY:
                _persist_briefing(session, now, p)
            continue
        if not p.cap_exempt and budget <= 0:
            _write_nudge(session, p, now, status="sent", channel="inbox")
            counts["capped_inbox"] += 1
            continue
        budget -= 1
        result = await notify.send(
            session,
            effective,
            user_id=p.context["user_id"],
            rule_key=p.rule_key,
            dedupe_key=p.dedupe_key,
            title=p.title,
            body=p.body,
            priority=p.priority,
            tags=p.tags,
            now=now,
        )
        if result.get("held_until"):
            counts["held"] += 1
        else:
            counts["delivered"] += 1
        if p.rule_key == BRIEFING_RULE_KEY:
            _persist_briefing(session, now, p)

    # 5. Redeliver anything held/snoozed whose moment has arrived.
    counts["redelivered"] = await _redeliver_due(session, effective, now)

    _record(session, started_at, now, counts, status="ok")
    return {"status": "ok", "counts": counts, "poll": poll_result}


def _persist_briefing(session: Session, now: datetime, proposal: NudgeProposal) -> None:
    """Upsert the ``briefings`` row from the composed content (DATA_MODEL §4)."""
    from ..models import Briefing
    from .proposals import LONDON

    local_date = now.astimezone(LONDON).date().isoformat()
    content_md = proposal.context.get("content_md", "")
    existing = session.get(Briefing, local_date)
    if existing is None:
        session.add(
            Briefing(local_date=local_date, content_md=content_md, composed_by="rules", sent_at=utc_str(now))
        )
    else:
        existing.content_md = content_md
        existing.composed_by = "rules"
        existing.sent_at = utc_str(now)
    session.commit()


def _record(session: Session, started_at: str, now: datetime, counts: dict, *, status: str, note: str | None = None) -> None:
    error = note
    if counts.get("error"):
        error = (error + "; " if error else "") + f"{counts['error']} rule error(s)"
    session.add(
        SyncRun(
            source="coach:tick",
            started_at=started_at,
            finished_at=utc_str(datetime.now(timezone.utc)),
            status=status,
            items=counts.get("delivered", 0) + counts.get("held", 0) + counts.get("inbox", 0),
            error=(error + f" | {json.dumps(counts)}") if error else json.dumps(counts),
        )
    )
    session.commit()


async def run(session: Session | None = None, now: datetime | None = None, *, poll: bool = True) -> dict:
    settings = get_settings()
    owns = session is None
    session = session or SessionLocal()
    try:
        return await tick(session, settings, now, poll=poll)
    finally:
        if owns:
            session.close()
