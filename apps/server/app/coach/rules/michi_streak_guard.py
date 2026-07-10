"""michi-streak-guard — protect the Japanese streak (COACH §3.4).

From 20:00, if Michi's snapshot shows ``streak_days > 0 && !studied_today`` →
one push linking to Michi. **Stale in, silent out** (COACH §3.4): if the
snapshot is missing or older than the freshness window it skips silently — the
coach never nags off dead data. No cooldown (it's inherently once/day via the
dedupe key).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ...models import SiblingSnapshot
from ..proposals import LONDON, NudgeProposal, Rule, RuleResult, parse_utc, today_local, today_trigger_if_past

STREAK_HH, STREAK_MM = 20, 0
FRESHNESS_SECONDS = 3 * 3600  # a poll runs every 15 min; 3h stale is generous


def evaluate(now: datetime, session) -> RuleResult:
    snap = session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == "michi", SiblingSnapshot.ok == 1)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
    ).first()
    if snap is None or not snap.payload_json:
        return RuleResult.stale("no fresh michi snapshot")

    age = (now - parse_utc(snap.fetched_at)).total_seconds()
    if age > FRESHNESS_SECONDS:
        return RuleResult.stale(f"michi snapshot {int(age)}s old")

    try:
        payload = json.loads(snap.payload_json)
    except (ValueError, TypeError):
        return RuleResult.stale("unparseable michi snapshot")

    streak = payload.get("streak_days") or 0
    studied = bool(payload.get("studied_today"))
    if streak <= 0 or studied:
        return RuleResult()

    trigger = today_trigger_if_past(now, STREAK_HH, STREAK_MM)
    if trigger is None:
        return RuleResult()

    today = today_local(now).isoformat()
    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="michi-streak-guard",
                dedupe_key=f"michi:{today}",
                title="Streak's still alive",
                body="Today's Japanese review isn't done yet — a few cards before bed keeps it going. \U0001f525",
                scheduled_for=trigger,
                tags=["coach", "michi"],
                expiry=timedelta(hours=2),
            )
        ]
    )


RULE = Rule(key="michi-streak-guard", evaluate=evaluate, cooldown_hours=0)
