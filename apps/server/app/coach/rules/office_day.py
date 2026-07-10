"""office-day — the evening-before verdict for tomorrow (COACH §3.6, HANDOFF Q2).

At 18:30 the day before, an encouraging nudge on the *aspirational* office days
Mack historically skips; it stays quiet about the habitual ones and skips bank
holidays (an all-day event from the holiday feed tomorrow). Weather shifts the
*framing* of the walk-commute, never the verdict (COACH §3.6). Honestly a
heuristic v1 — ship dumb, observe, sharpen.

Config (``office_pattern`` setting): ``{"habitual": ["Tue","Wed","Thu"],
"aspirational": ["Mon"], "holiday_calendar": "UK Holidays"}``. Unset →
``not_configured``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import CalendarEvent, SiblingSnapshot
from .. import config as coach_config
from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

OFFICE_HH, OFFICE_MM = 18, 30


def _is_bank_holiday(session, day_str: str, holiday_calendar: str | None) -> bool:
    start = f"{day_str} 00:00:00"
    end = f"{day_str} 23:59:59"
    rows = session.scalars(
        select(CalendarEvent).where(
            CalendarEvent.all_day == 1,
            CalendarEvent.starts_at >= start,
            CalendarEvent.starts_at <= end,
        )
    ).all()
    for e in rows:
        if holiday_calendar and e.calendar_name == holiday_calendar:
            return True
        if not holiday_calendar and e.title and "holiday" in e.title.lower():
            return True
    return False


def _rain_tomorrow(session) -> bool:
    snap = session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == "weather", SiblingSnapshot.ok == 1)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
    ).first()
    if snap is None or not snap.payload_json:
        return False
    try:
        payload = json.loads(snap.payload_json)
    except (ValueError, TypeError):
        return False
    for loc in ("office", "home"):
        daily = (payload.get(loc) or {}).get("daily") or {}
        try:
            return (daily["precipitation_probability_max"][1] or 0) >= 50
        except (KeyError, IndexError, TypeError):
            continue
    return False


def evaluate(now: datetime, session) -> RuleResult:
    pattern = coach_config.get_setting(session, coach_config.KEY_OFFICE_PATTERN, None)
    if not isinstance(pattern, dict) or not pattern.get("aspirational"):
        return RuleResult.not_configured("no office_pattern.aspirational")

    trigger = today_trigger_if_past(now, OFFICE_HH, OFFICE_MM)
    if trigger is None:
        return RuleResult()

    tomorrow = today_local(now) + timedelta(days=1)
    tomorrow_str = tomorrow.isoformat()
    weekday = tomorrow.strftime("%a")

    aspirational = set(pattern.get("aspirational", []))
    if weekday not in aspirational:
        return RuleResult()  # quiet about habitual days; only nudge aspirational ones

    if _is_bank_holiday(session, tomorrow_str, pattern.get("holiday_calendar")):
        return RuleResult()  # bank holiday — no office nudge

    frame = (
        "Wrap up — rain's likely on the walk. \U0001f327️"
        if _rain_tomorrow(session)
        else "The walk should be a pleasant one."
    )
    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="office-day",
                dedupe_key=f"office:{tomorrow_str}",
                title="Tomorrow's a good office day",
                body=f"Worth heading in tomorrow if you can. {frame}",
                scheduled_for=trigger,
                tags=["coach", "office"],
                expiry=timedelta(hours=4),
            )
        ]
    )


RULE = Rule(key="office-day", evaluate=evaluate, cooldown_hours=24)
