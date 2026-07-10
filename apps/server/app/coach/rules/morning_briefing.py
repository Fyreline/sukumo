"""morning-briefing — the 07:35 anchor push (COACH §3.1).

This module only decides *whether the briefing is due today*; the content is
composed by ``coach/briefing.py`` from the same proposal stream the other rules
emit (the engine fills ``body``/``content_md`` before delivery). The proposal
is ``cap_exempt`` — the daily cap never demotes the anchor.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

BRIEFING_HH, BRIEFING_MM = 7, 35


def evaluate(now: datetime, session) -> RuleResult:
    trigger = today_trigger_if_past(now, BRIEFING_HH, BRIEFING_MM)
    if trigger is None:
        return RuleResult()  # before 07:35 — nothing yet
    today = today_local(now).isoformat()
    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="morning-briefing",
                dedupe_key=f"briefing:{today}",
                title="Good morning",
                body="",  # filled by briefing.compose in the engine
                scheduled_for=trigger,
                priority="default",
                tags=["coach", "briefing"],
                expiry=timedelta(hours=4),  # a briefing delivered past ~11:35 is stale
                push=True,
                cap_exempt=True,
            )
        ]
    )


RULE = Rule(key="morning-briefing", evaluate=evaluate, cooldown_hours=0)
