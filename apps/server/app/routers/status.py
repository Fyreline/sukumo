"""GET /api/status -- sibling/source health: latest sync_runs per source +
snapshot ages + ingest-token liveness -- docs/DATA_MODEL.md #7,
docs/phases/PHASE-2-ingestion.md build item 7. JWT-auth (the Dyehouse status
tile reads this once logged in, docs/DESIGN.md #3.7).

Phase 2 wired the sources it owns (ingest tokens, calendar/weather pollers,
habit auto-evidence via poll_sources' own sync_runs rows). Phase 3
(docs/phases/PHASE-3-siblings.md build item 5) adds the ``siblings`` section
below: one row per household sibling app (michi/kakeibo/mishka -- NOT
weather/calendar, which are ambient sources, not siblings) carrying its
latest snapshot's ok/age/latency plus a ``consecutive_failures`` count. The
generic ``snapshots`` list below is unchanged and still covers every
sibling_snapshots app, siblings included.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import IngestToken, SiblingSnapshot, SyncRun

router = APIRouter(tags=["status"])

# The three household sibling apps (docs/API.md §4) -- deliberately excludes
# 'weather'/'calendar', which are ambient sources with their own sync_runs
# but no "is this household app up" question to answer.
SIBLING_APPS = ("michi", "kakeibo", "mishka")


def _age_seconds(fetched_at: str) -> int:
    """fetched_at is a naive UTC '%Y-%m-%d %H:%M:%S' string (the siblings'
    timestamp convention, DATA_MODEL preamble) -- age is just now minus that,
    in whole seconds."""
    fetched_dt = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - fetched_dt).total_seconds())


def _consecutive_failures(session: Session, app: str, limit: int = 50) -> int:
    """Consecutive ok=0 sibling_snapshots rows for `app`, most-recent-first,
    stopping at the first ok=1 row (or after `limit` rows -- DATA_MODEL §6
    prunes each app to N=50 rows on insert, so that's the natural ceiling
    anyway). Pure query over existing history -- no new state, per the phase
    doc's build item 5.
    """
    rows = session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == app)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
        .limit(limit)
    ).all()
    count = 0
    for row in rows:
        if row.ok:
            break
        count += 1
    return count


@router.get("/status")
async def status(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    # latest sync_runs row per source (started_at is a zero-padded ISO
    # string, so lexicographic ordering matches chronological order).
    latest_by_source: dict[str, SyncRun] = {}
    for row in session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())):
        latest_by_source.setdefault(row.source, row)
    sync_runs = [
        {
            "source": r.source,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "items": r.items,
            "error": r.error,
        }
        for r in latest_by_source.values()
    ]

    # latest sibling_snapshots row per app (snapshot "age" is the dashboard's
    # job to compute against fetched_at -- this just serves the freshest row).
    latest_snapshot: dict[str, SiblingSnapshot] = {}
    for row in session.scalars(select(SiblingSnapshot).order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())):
        latest_snapshot.setdefault(row.app, row)
    snapshots = [
        {
            "app": s.app,
            "ok": bool(s.ok),
            "fetched_at": s.fetched_at,
            "latency_ms": s.latency_ms,
            "error": s.error,
        }
        for s in latest_snapshot.values()
    ]

    ingest_tokens = [
        {
            "id": t.id,
            "name": t.name,
            "scope": t.scope,
            "last_seen_at": t.last_seen_at,
            "revoked": t.revoked_at is not None,
        }
        for t in session.scalars(select(IngestToken).order_by(IngestToken.id))
    ]

    siblings = [
        {
            "app": app,
            "ok": bool(latest_snapshot[app].ok) if app in latest_snapshot else None,
            "age_seconds": _age_seconds(latest_snapshot[app].fetched_at) if app in latest_snapshot else None,
            "latency_ms": latest_snapshot[app].latency_ms if app in latest_snapshot else None,
            "consecutive_failures": _consecutive_failures(session, app),
        }
        for app in SIBLING_APPS
    ]

    return {
        "sync_runs": sync_runs,
        "snapshots": snapshots,
        "ingest_tokens": ingest_tokens,
        "siblings": siblings,
    }
