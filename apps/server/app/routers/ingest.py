"""POST /api/ingest/* -- token-auth (not JWT) ingest endpoints for phone
health payloads and generic events -- docs/API.md #2-3, docs/AUTH.md #3,
docs/phases/PHASE-2-ingestion.md.

Both routes require an ingest token with scope 'ingest' (or 'ingest+notify')
-- see app.auth.ingest_token_auth. A JWT never satisfies this dependency and
an ingest token never satisfies app.auth.current_user (AUTH.md #3: "two
disjoint doors"). Every call writes one sync_runs row regardless of outcome
(ARCHITECTURE #5.6), so a silent failure is always diagnosable from
/api/status.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import ingest_token_auth
from ..db import get_session
from ..errors import SukumoHTTPException
from ..ingest.events import ingest_event
from ..ingest.health import ingest_health_payload
from ..ingest.location import ingest_location_payload
from ..models import IngestToken, SyncRun

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@router.post("/health")
async def ingest_health_endpoint(
    payload: dict,
    token: IngestToken = Depends(ingest_token_auth("ingest")),
    session: Session = Depends(get_session),
) -> dict:
    started_at = _utcnow_str()
    if token.user_id is None:
        raise SukumoHTTPException(
            status_code=400, detail="Ingest token has no associated user", code="token_unowned"
        )

    try:
        result = ingest_health_payload(session, token.user_id, payload)
    except Exception as exc:  # noqa: BLE001 -- any parse/shape failure becomes a diagnosable sync_run
        session.rollback()
        session.add(
            SyncRun(
                source="ingest:health",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="error",
                items=0,
                error=str(exc),
            )
        )
        session.commit()
        raise SukumoHTTPException(
            status_code=400, detail=f"Invalid health payload: {exc}", code="invalid_payload"
        ) from exc

    session.add(
        SyncRun(
            source="ingest:health",
            started_at=started_at,
            finished_at=_utcnow_str(),
            status="ok",
            items=result["accepted"],
        )
    )
    session.commit()
    return result


@router.post("/location")
async def ingest_location_endpoint(
    payload: dict,
    token: IngestToken = Depends(ingest_token_auth("ingest")),
    session: Session = Depends(get_session),
) -> dict:
    """Overland GPS batches (docs/API.md #3b). The 200 body is ALWAYS the
    literal ``{"result": "ok"}`` Overland requires -- any other body makes the
    app retain and re-send the batch forever -- so accepted/dropped counts go
    to the ``sync_runs`` row ('ingest:location'), not the response. Auth is
    header-only (``Authorization: Bearer <ingest token>``): no ``?token=``
    query fallback, because query strings land verbatim in uvicorn's access
    log (API.md #3b has the full reasoning)."""
    started_at = _utcnow_str()
    if token.user_id is None:
        raise SukumoHTTPException(
            status_code=400, detail="Ingest token has no associated user", code="token_unowned"
        )

    try:
        result = ingest_location_payload(session, token.user_id, payload)
    except Exception as exc:  # noqa: BLE001 -- any parse/shape failure becomes a diagnosable sync_run
        session.rollback()
        session.add(
            SyncRun(
                source="ingest:location",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="error",
                items=0,
                error=str(exc),
            )
        )
        session.commit()
        raise SukumoHTTPException(
            status_code=400, detail=f"Invalid location payload: {exc}", code="invalid_payload"
        ) from exc

    session.add(
        SyncRun(
            source="ingest:location",
            started_at=started_at,
            finished_at=_utcnow_str(),
            status="ok",
            items=result["accepted"],
            # the dropped count rides along so the Ops tile can show it; never
            # coordinates, never token material (ARCHITECTURE #5.5).
            error=f"dropped={result['dropped']}" if result["dropped"] else None,
        )
    )
    session.commit()
    return {"result": "ok"}


@router.post("/event")
async def ingest_event_endpoint(
    payload: dict,
    token: IngestToken = Depends(ingest_token_auth("ingest")),
    session: Session = Depends(get_session),
) -> dict:
    started_at = _utcnow_str()
    try:
        result = ingest_event(session, token.user_id, payload)
    except ValueError as exc:
        session.rollback()
        session.add(
            SyncRun(
                source="ingest:event",
                started_at=started_at,
                finished_at=_utcnow_str(),
                status="error",
                items=0,
                error=str(exc),
            )
        )
        session.commit()
        raise SukumoHTTPException(status_code=400, detail=str(exc), code="invalid_payload") from exc

    session.add(
        SyncRun(
            source="ingest:event", started_at=started_at, finished_at=_utcnow_str(), status="ok", items=1
        )
    )
    session.commit()
    return result
