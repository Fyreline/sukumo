"""GET/PATCH /api/settings — the coach's household knobs (COACH §2,
docs/phases/PHASE-6-coach.md build item 6).

    GET   /api/settings   (JWT, primary-only)
    PATCH /api/settings   (JWT, primary-only)

Quiet hours, the daily push cap, and per-rule enable/disable — all stored in
the ``settings`` table (DATA_MODEL §7), read-through the same accessors the
coach engine uses (coach/config.py) so the UI and the tick never disagree.
Primary-only, mirroring routers/nudges.py (the coach nudges only the primary
at v1).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..coach import config as coach_config
from ..coach.rules import load_rules
from ..config import get_settings
from ..db import get_session
from ..errors import SukumoHTTPException
from .nudges import primary_only

router = APIRouter(tags=["settings"])

_QUIET_RE = re.compile(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$")


def _state(session: Session) -> dict:
    settings = get_settings()
    disabled = coach_config.disabled_rules(session)
    return {
        "quiet_hours": coach_config.quiet_hours(session, settings),
        "daily_cap": coach_config.daily_cap(session),
        "rules": [{"key": r.key, "enabled": r.key not in disabled} for r in load_rules()],
    }


@router.get("/settings")
async def get_settings_endpoint(
    user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    return _state(session)


class SettingsPatch(BaseModel):
    quiet_hours: str | None = None
    daily_cap: int | None = None
    # {"reading": false, "gym-day": true} — partial, only the keys sent change.
    rules: dict[str, bool] | None = None


@router.patch("/settings")
async def patch_settings_endpoint(
    body: SettingsPatch,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    if body.quiet_hours is not None:
        if not _QUIET_RE.match(body.quiet_hours):
            raise SukumoHTTPException(
                status_code=422, detail="quiet_hours must be 'HH:MM-HH:MM'", code="validation_error"
            )
        coach_config.set_setting(session, coach_config.KEY_QUIET_HOURS, body.quiet_hours)

    if body.daily_cap is not None:
        if body.daily_cap < 1:
            raise SukumoHTTPException(status_code=422, detail="daily_cap must be >= 1", code="validation_error")
        coach_config.set_setting(session, coach_config.KEY_DAILY_CAP, body.daily_cap)

    if body.rules is not None:
        known = {r.key for r in load_rules()}
        disabled = coach_config.disabled_rules(session)
        for key, enabled in body.rules.items():
            if key not in known:
                raise SukumoHTTPException(status_code=422, detail=f"unknown rule {key!r}", code="validation_error")
            if enabled:
                disabled.discard(key)
            else:
                disabled.add(key)
        coach_config.set_setting(session, coach_config.KEY_DISABLED_RULES, sorted(disabled))

    session.commit()
    return _state(session)
