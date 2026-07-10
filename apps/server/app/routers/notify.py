"""POST /api/notify — the notification bus entry point (token-auth) —
docs/API.md §5, docs/ARCHITECTURE.md §5.3, docs/phases/PHASE-5-notify.md.

Any household app/script, one pipe (ingest-token, scope 'notify'): writes an
inbox nudge (``rule_key='bus:<source>'``) and forwards through
``notify.send()``. Siblings adopt this opportunistically — it's never a
blocking dependency for them (API.md §5).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notify as notify_module
from ..auth import ingest_token_auth
from ..config import get_settings
from ..db import get_session
from ..errors import SukumoHTTPException
from ..models import IngestToken, User

router = APIRouter(tags=["notify"])

VALID_PRIORITIES = {"low", "default", "high"}


class NotifyIn(BaseModel):
    title: str
    body: str
    priority: str = "default"
    tags: list[str] = Field(default_factory=list)
    source: str


def _resolve_user_id(session: Session, token_user_id: int | None) -> int:
    """Mirrors ``app.ingest.events._resolve_user_id``: a household-bus token
    (no ``user_id``) falls back to the primary user — the coach (and thus
    the bus, its first customer) only nudges 'primary' at v1 (AUTH.md §1)."""
    if token_user_id is not None:
        return token_user_id
    primary = session.scalar(select(User).where(User.role == "primary"))
    if primary is None:
        raise SukumoHTTPException(
            status_code=400,
            detail="no owning user: ingest token has no user_id and no primary user exists",
            code="token_unowned",
        )
    return primary.id


@router.post("/notify")
async def notify_bus(
    payload: NotifyIn,
    token: IngestToken = Depends(ingest_token_auth("notify")),
    session: Session = Depends(get_session),
) -> dict:
    if payload.priority not in VALID_PRIORITIES:
        raise SukumoHTTPException(
            status_code=400,
            detail=f"priority must be one of {sorted(VALID_PRIORITIES)}",
            code="invalid_payload",
        )

    settings = get_settings()
    user_id = _resolve_user_id(session, token.user_id)
    # Every bus POST is its own event — not deduped against prior ones — so
    # the dedupe_key just needs to be unique, not meaningfully derived
    # (unlike a recurring coach rule's dedupe_key, COACH.md §1).
    dedupe_key = f"bus:{payload.source}:{uuid.uuid4().hex}"

    result = await notify_module.send(
        session,
        settings,
        user_id=user_id,
        rule_key=f"bus:{payload.source}",
        dedupe_key=dedupe_key,
        title=payload.title,
        body=payload.body,
        priority=payload.priority,
        tags=payload.tags,
    )
    return result
