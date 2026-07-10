"""occasion-reminder — non-birthday occasions (COACH §3.7).

Anniversaries/events/deadlines fire at ``lead_days`` out and again at 2 days.
dedupe ``occ:<id>:<offset>`` so each of the two reminders lands once.
Birthdays are the ``birthday-gift`` rule's job, not this one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from ...models import Occasion
from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

PROMPT_HH, PROMPT_MM = 10, 0
SECOND_OFFSET = 2


def _next_occurrence(occ: Occasion, today: date) -> date | None:
    try:
        if occ.recurrence == "once":
            return date.fromisoformat(occ.date) if occ.date else None
        if not occ.month_day:
            return None
        month, day = (int(p) for p in occ.month_day.split("-"))
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                candidate = date(year, 3, 1)
            if candidate >= today:
                return candidate
        return None
    except (ValueError, AttributeError, TypeError):
        return None


def evaluate(now: datetime, session) -> RuleResult:
    trigger = today_trigger_if_past(now, PROMPT_HH, PROMPT_MM)
    if trigger is None:
        return RuleResult()
    today = today_local(now)
    proposals: list[NudgeProposal] = []
    for occ in session.scalars(select(Occasion).where(Occasion.kind != "birthday")).all():
        target = _next_occurrence(occ, today)
        if target is None:
            continue
        days = (target - today).days
        offset = None
        if days == occ.lead_days:
            offset = occ.lead_days
        elif days == SECOND_OFFSET:
            offset = SECOND_OFFSET
        if offset is None:
            continue
        when = "in 2 days" if days == SECOND_OFFSET else f"in {days} days"
        proposals.append(
            NudgeProposal(
                rule_key="occasion-reminder",
                dedupe_key=f"occ:{occ.id}:{offset}",
                title=occ.title,
                body=f"{occ.title} is {when} — worth a moment to plan for it.",
                scheduled_for=trigger,
                tags=["coach", "occasion"],
                expiry=timedelta(hours=6),
            )
        )
    return RuleResult(proposals=proposals)


RULE = Rule(key="occasion-reminder", evaluate=evaluate, cooldown_hours=0)
