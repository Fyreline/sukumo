"""Nudge history, snooze/dismiss/action + the one-click action link —
docs/API.md §1, docs/AUTH.md §4, docs/COACH.md §2, docs/phases/PHASE-5-notify.md.

    GET  /api/nudges?status=…                        (JWT, primary-only)
    POST /api/nudges/{id}/snooze|dismiss|action       (JWT, primary-only)
    GET  /api/nudges/act/{token}                      (open — AUTH.md §4)

Nudges are primary-only at v1 (COACH.md §1: "the coach only nudges
primary") — the door mirrors routers/people.py's ``primary_only``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notify as notify_module
from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..errors import SukumoHTTPException
from ..models import Nudge, User

router = APIRouter(tags=["nudges"])

LONDON = ZoneInfo("Europe/London")
NUDGE_STATUSES = ("pending", "sent", "snoozed", "dismissed", "actioned", "expired")
SNOOZE_OPTIONS = ("3h", "tomorrow", "next-week")  # COACH.md §2


def primary_only(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> int:
    user = session.get(User, user_id)
    if user is None or user.role != "primary":
        raise SukumoHTTPException(status_code=403, detail="Nudges are primary-only at v1", code="forbidden")
    return user_id


def _serialize(n: Nudge) -> dict:
    return {
        "id": n.id,
        "rule_key": n.rule_key,
        "dedupe_key": n.dedupe_key,
        "scheduled_for": n.scheduled_for,
        "sent_at": n.sent_at,
        "channel": n.channel,
        "title": n.title,
        "body": n.body,
        "status": n.status,
        "snoozed_until": n.snoozed_until,
        "context": json.loads(n.context_json or "{}"),
        "created_at": n.created_at,
    }


def _get_owned_nudge(session: Session, user_id: int, nudge_id: int) -> Nudge:
    nudge = session.get(Nudge, nudge_id)
    if nudge is None or nudge.user_id != user_id:
        raise SukumoHTTPException(status_code=404, detail="nudge not found", code="not_found")
    return nudge


@router.get("/nudges")
async def list_nudges(
    status: str | None = None,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> list[dict]:
    q = select(Nudge).where(Nudge.user_id == user_id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        for s in statuses:
            if s not in NUDGE_STATUSES:
                raise SukumoHTTPException(status_code=400, detail=f"unknown status {s!r}", code="invalid_payload")
        q = q.where(Nudge.status.in_(statuses))
    rows = session.scalars(q.order_by(Nudge.created_at.desc(), Nudge.id.desc())).all()
    return [_serialize(n) for n in rows]


class SnoozeIn(BaseModel):
    option: str = "3h"


@router.post("/nudges/{nudge_id}/snooze")
async def snooze_nudge(
    nudge_id: int,
    payload: SnoozeIn,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    if payload.option not in SNOOZE_OPTIONS:
        raise SukumoHTTPException(
            status_code=400, detail=f"option must be one of {SNOOZE_OPTIONS}", code="invalid_payload"
        )
    nudge = _get_owned_nudge(session, user_id, nudge_id)

    now_london = datetime.now(timezone.utc).astimezone(LONDON)
    if payload.option == "3h":
        until_local = now_london + timedelta(hours=3)
    elif payload.option == "tomorrow":
        until_local = (now_london + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    else:  # "next-week"
        until_local = (now_london + timedelta(days=7)).replace(hour=8, minute=0, second=0, microsecond=0)
    until_utc = until_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    nudge.status = "snoozed"
    nudge.snoozed_until = until_utc
    nudge.scheduled_for = until_utc
    session.commit()
    return _serialize(nudge)


@router.post("/nudges/{nudge_id}/dismiss")
async def dismiss_nudge(
    nudge_id: int, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    nudge = _get_owned_nudge(session, user_id, nudge_id)
    nudge.status = "dismissed"
    session.commit()
    return _serialize(nudge)


@router.post("/nudges/{nudge_id}/action")
async def action_nudge(
    nudge_id: int, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    nudge = _get_owned_nudge(session, user_id, nudge_id)
    if nudge.status != "actioned":
        callback = notify_module.get_action_callback(nudge.rule_key)
        if callback is not None:
            callback(session, nudge)
        nudge.status = "actioned"
        session.commit()
    return _serialize(nudge)


# ============================================================================
# GET /api/nudges/act/{token} — open, signed, single-use (AUTH.md §4)
# ============================================================================
_PAGE_STYLE = """<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f6f1e7; color: #2b2620; display: flex; min-height: 100vh;
    align-items: center; justify-content: center; margin: 0; padding: 24px; }
  .card { max-width: 360px; text-align: center; background: #fffdf8;
    border: 1px solid #e4dcc8; border-radius: 14px; padding: 32px 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  h1 { font-size: 1.1rem; margin: 0 0 8px; color: #2b2620; }
  p { font-size: 0.92rem; color: #6b6153; margin: 0; line-height: 1.4; }
  .glyph { font-size: 2rem; margin-bottom: 12px; }
</style>"""


def _act_page(glyph: str, title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Sukumo</title>{_PAGE_STYLE}</head>"
        f'<body><div class="card"><div class="glyph">{glyph}</div>'
        f"<h1>{title}</h1><p>{body}</p></div></body></html>"
    )


@router.get("/nudges/act/{token}")
async def act_on_token(token: str, session: Session = Depends(get_session)) -> HTMLResponse:
    """Opens straight from a phone notification's action button (no auth) —
    AUTH.md §4: ``HMAC(JWT_SECRET, nudge_id + expiry)``. "Single-use" is
    enforced by the NUDGE's own status, not a separate consumption ledger:
    once terminal (``actioned``/``dismissed``/``expired``), a repeat hit is
    an idempotent no-op — the signature/expiry check is only the door."""
    settings = get_settings()
    try:
        nudge_id, expired = notify_module.verify_action_token(token, settings)
    except notify_module.ActionTokenError:
        return HTMLResponse(
            _act_page("🔒", "Link not recognised", "This link doesn’t check out — it may have been altered."),
            status_code=401,
        )

    nudge = session.get(Nudge, nudge_id)
    if nudge is None:
        return HTMLResponse(
            _act_page("🔒", "Nudge not found", "This nudge no longer exists."), status_code=410
        )

    if expired or nudge.status == "expired":
        if nudge.status != "expired":
            nudge.status = "expired"
            session.commit()
        return HTMLResponse(
            _act_page("⏳", "This one’s expired", "The link on this nudge has expired — check the inbox for anything current."),
            status_code=410,
        )

    if nudge.status in ("actioned", "dismissed"):
        return HTMLResponse(
            _act_page("✓", "Already sorted", "This one was already taken care of."), status_code=200
        )

    callback = notify_module.get_action_callback(nudge.rule_key)
    if callback is not None:
        callback(session, nudge)
    nudge.status = "actioned"
    session.commit()

    return HTMLResponse(
        _act_page("✓", "Done", f"“{nudge.title}” — marked done. Nicely handled."), status_code=200
    )
