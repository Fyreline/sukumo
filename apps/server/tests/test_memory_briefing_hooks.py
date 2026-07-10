"""The memory engine's two briefing hooks (MEMORY §3-4): the Sunday
week-in-review and the anniversary "on this day" line. SYNTHETIC data only."""
from __future__ import annotations

import json

from app import notify
from app.coach import briefing as briefing_module
from app.config import get_settings
from app.db import SessionLocal
from app.models import JournalDay

from tests.coach_helpers import london
from tests.conftest import make_user


def _journal_day(db, local_date, *, steps=0, films=0, events=0):
    db.add(
        JournalDay(
            local_date=local_date,
            assembled_at=f"{local_date} 02:30:00",
            summary_md=f"## {local_date}\n\nA synthetic day.\n",
            stats_json=json.dumps({"steps": steps, "films": films, "workouts": 0, "study": False, "photos": 0}),
            event_count=events,
            mood=None,
        )
    )


def test_weekly_digest_injected_on_sunday():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        # 12 Jul 2026 is a Sunday; the week ends Saturday 11th
        for dstr in ("2026-07-06", "2026-07-08", "2026-07-11"):
            _journal_day(db, dstr, steps=6000, events=1)
        db.commit()
        content_md, push_body = briefing_module.compose(db, london(2026, 7, 12, 7, 40), get_settings(), [])
    assert "Week in review" in content_md
    # redaction still holds line-by-line
    for line in content_md.splitlines():
        notify.check_redaction(line)


def test_weekly_digest_absent_on_a_weekday():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        _journal_day(db, "2026-07-08", steps=6000, events=1)
        db.commit()
        content_md, _ = briefing_module.compose(db, london(2026, 7, 8, 7, 40), get_settings(), [])
    assert "Week in review" not in content_md


def test_anniversary_line_appears_on_lookback_hit():
    make_user(email="mack@example.com", role="primary")
    with SessionLocal() as db:
        _journal_day(db, "2025-07-08", steps=5000, events=2)  # one year prior
        db.commit()
        content_md, _ = briefing_module.compose(db, london(2026, 7, 8, 7, 40), get_settings(), [])
    assert "On this day" in content_md
    assert "a year ago today" in content_md
