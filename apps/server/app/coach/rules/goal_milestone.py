"""goal-milestone — celebrate the house pot crossing a 5% boundary (COACH §3.10).

The redaction gate applies in full: label only, never a figure — "House pot
just crossed another 5% 🎉" (ARCHITECTURE §5.2, and 5% passes the gate as a
percentage-label). dedupe ``goal:<pct5>`` announces each boundary once, ever.
No Kakeibo snapshot → ``not_configured`` (its endpoint may not be live yet).
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from ...models import SiblingSnapshot
from ..proposals import NudgeProposal, Rule, RuleResult


def evaluate(now: datetime, session) -> RuleResult:
    snap = session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == "kakeibo", SiblingSnapshot.ok == 1)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
    ).first()
    if snap is None or not snap.payload_json:
        return RuleResult.not_configured("no kakeibo snapshot")
    try:
        payload = json.loads(snap.payload_json)
    except (ValueError, TypeError):
        return RuleResult.not_configured("unparseable kakeibo snapshot")

    pct = payload.get("pct")
    if pct is None:
        return RuleResult()
    pct5 = int(pct // 5) * 5
    if pct5 < 5:
        return RuleResult()

    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="goal-milestone",
                dedupe_key=f"goal:{pct5}",
                title="A milestone on the house pot",
                body=f"The house pot just crossed another 5% \U0001f389 — steady progress adds up.",
                scheduled_for=now,
                tags=["coach", "goal"],
                expiry=None,  # a celebration can wait for the morning window if it's quiet hours
            )
        ]
    )


RULE = Rule(key="goal-milestone", evaluate=evaluate, cooldown_hours=0)
