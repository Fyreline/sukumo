"""japan-countdown — the trip runs down (COACH §3.11).

Milestones at 60/30/14/7/1 days. A push at 30 and 7; the others are briefing
lines only (``push=False`` → inbox row + digest, no phone buzz). dedupe
``japan:<days>``. Sunsets after the trip — the memory engine takes over. Reads
the ``japan_range`` setting the dashboard already uses; unset → ``not_configured``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .. import config as coach_config
from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

MILESTONES = {60, 30, 14, 7, 1}
PUSH_MILESTONES = {30, 7}
BRIEFING_HH, BRIEFING_MM = 7, 35


def evaluate(now: datetime, session) -> RuleResult:
    value = coach_config.get_setting(session, coach_config.KEY_JAPAN_RANGE, None)
    if not isinstance(value, dict) or "start" not in value:
        return RuleResult.not_configured("no japan_range")
    try:
        start = date.fromisoformat(value["start"])
    except (ValueError, TypeError):
        return RuleResult.not_configured("bad japan_range.start")

    trigger = today_trigger_if_past(now, BRIEFING_HH, BRIEFING_MM)
    if trigger is None:
        return RuleResult()

    days = (start - today_local(now)).days
    if days not in MILESTONES:
        return RuleResult()

    push = days in PUSH_MILESTONES
    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="japan-countdown",
                dedupe_key=f"japan:{days}",
                title="Japan countdown",
                body=f"Japan is {days} days away — the good kind of not-long-now. ✈️",
                scheduled_for=trigger,
                tags=["coach", "japan"],
                expiry=timedelta(hours=6),
                push=push,
            )
        ]
    )


RULE = Rule(key="japan-countdown", evaluate=evaluate, cooldown_hours=0)
