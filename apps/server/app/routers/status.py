"""GET /api/status -- sibling/source health: latest sync_runs per source +
snapshot ages + ingest-token liveness -- docs/DATA_MODEL.md #7,
docs/phases/PHASE-2-ingestion.md build item 7. JWT-auth (the Dyehouse status
tile reads this once logged in, docs/DESIGN.md #3.7).

Phase 2 wires the sources it owns (ingest tokens, calendar/weather pollers,
habit auto-evidence via poll_sources' own sync_runs rows); sibling-app rows
('poll:michi' etc.) land in Phase 3 and simply show up here once those
pollers start writing sync_runs -- no change needed in this router then.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import IngestToken, SiblingSnapshot, SyncRun

router = APIRouter(tags=["status"])


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

    return {"sync_runs": sync_runs, "snapshots": snapshots, "ingest_tokens": ingest_tokens}
