"""ops:health-sync-stale — the phone stopped syncing (COACH §3.8).

No successful ``ingest:health`` sync_run in 36h → an inbox row + a morning
mention (``push=False``: never an evening buzz, it can wait till the briefing).
dedupe ``ops-health:<date>``. If the phone has *never* synced (no ingest:health
runs at all), this stays quiet — there's nothing to have gone stale yet.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ...models import SyncRun
from ..proposals import NudgeProposal, Rule, RuleResult, parse_utc, today_local, today_trigger_if_past

MORNING_HH, MORNING_MM = 7, 35
STALE_SECONDS = 36 * 3600


def evaluate(now: datetime, session) -> RuleResult:
    runs = session.scalars(select(SyncRun).where(SyncRun.source == "ingest:health")).all()
    if not runs:
        return RuleResult()  # never synced — nothing to call stale yet

    trigger = today_trigger_if_past(now, MORNING_HH, MORNING_MM)
    if trigger is None:
        return RuleResult()

    ok_times = [parse_utc(r.started_at) for r in runs if r.status == "ok"]
    fresh = any((now - t).total_seconds() <= STALE_SECONDS for t in ok_times)
    if fresh:
        return RuleResult()

    today = today_local(now).isoformat()
    return RuleResult(
        proposals=[
            NudgeProposal(
                rule_key="ops:health-sync-stale",
                dedupe_key=f"ops-health:{today}",
                title="Health sync has gone quiet",
                body="No health data has come through in over a day — worth checking the phone shortcut when you can.",
                scheduled_for=trigger,
                tags=["coach", "ops"],
                expiry=timedelta(hours=6),
                push=False,  # morning mention only, never an evening push
            )
        ]
    )


RULE = Rule(key="ops:health-sync-stale", evaluate=evaluate, cooldown_hours=24)
