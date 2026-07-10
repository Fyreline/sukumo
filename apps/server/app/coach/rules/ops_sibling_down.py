"""ops:sibling-down — a household app stopped answering (COACH §3.9).

A sibling snapshot failing 3 consecutive polls → an inbox row + morning mention
(``push=False``). When it recovers, a single auto-resolving note. dedupe
``ops-<app>:<date>`` (down) and ``ops-<app>-recovered:<date>`` (recovery).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import Nudge, SiblingSnapshot
from ...routers.status import SIBLING_APPS, _consecutive_failures
from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

MORNING_HH, MORNING_MM = 7, 35
DOWN_THRESHOLD = 3


def _latest_snapshot(session, app: str) -> SiblingSnapshot | None:
    return session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == app)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
    ).first()


def _recent_down_nudge(session, app: str) -> bool:
    return (
        session.scalar(
            select(Nudge).where(Nudge.rule_key == "ops:sibling-down", Nudge.dedupe_key.like(f"ops-{app}:%"))
        )
        is not None
    )


def _recovery_already_noted(session, app: str) -> bool:
    return (
        session.scalar(select(Nudge).where(Nudge.dedupe_key.like(f"ops-{app}-recovered:%"))) is not None
    )


def evaluate(now: datetime, session) -> RuleResult:
    trigger = today_trigger_if_past(now, MORNING_HH, MORNING_MM)
    if trigger is None:
        return RuleResult()
    today = today_local(now).isoformat()

    proposals: list[NudgeProposal] = []
    for app in SIBLING_APPS:
        latest = _latest_snapshot(session, app)
        if latest is None:
            continue
        fails = _consecutive_failures(session, app)
        if fails >= DOWN_THRESHOLD:
            proposals.append(
                NudgeProposal(
                    rule_key="ops:sibling-down",
                    dedupe_key=f"ops-{app}:{today}",
                    title=f"{app.title()} isn't answering",
                    body=f"{app.title()} has failed its last few checks — its tile is showing stale until it's back.",
                    scheduled_for=trigger,
                    tags=["coach", "ops"],
                    expiry=timedelta(hours=6),
                    push=False,
                )
            )
        elif fails == 0 and _recent_down_nudge(session, app) and not _recovery_already_noted(session, app):
            proposals.append(
                NudgeProposal(
                    rule_key="ops:sibling-down",
                    dedupe_key=f"ops-{app}-recovered:{today}",
                    title=f"{app.title()} is back",
                    body=f"{app.title()} is answering again — its tile is live once more.",
                    scheduled_for=trigger,
                    tags=["coach", "ops"],
                    expiry=timedelta(hours=6),
                    push=False,
                )
            )
    return RuleResult(proposals=proposals)


RULE = Rule(key="ops:sibling-down", evaluate=evaluate, cooldown_hours=0)
