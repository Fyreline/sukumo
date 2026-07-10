"""GET /api/dashboard -- the one aggregate that paints every bridge tile
(docs/API.md §1, docs/phases/PHASE-4-dashboard.md build item 1).

Covers: the exact aggregate shape off a fixtured db (samples, workouts,
habits, snapshots, occasions, memory events, settings), habit gap maths,
null-safe goal, the private_to_user surprise guard, the 45-day occasions
window, and -- load-bearing -- the **server-side partner redaction**: a
role='partner' response carries NO vitals/habits/goal/occasions/memory/
nudges/briefing/weather keys at all (DESIGN §3, HANDOFF Q9).

All fixture data is synthetic (ARCHITECTURE §5.5).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tests.conftest import auth_headers, make_user

LONDON = ZoneInfo("Europe/London")


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(LONDON).date()


def _d(days_ago: int) -> str:
    return (_today() - timedelta(days=days_ago)).isoformat()


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _seed_full(user_id: int, partner_id: int) -> dict:
    """A little of everything, all synthetic. Returns ids for assertions."""
    from app.db import SessionLocal
    from app.models import (
        GiftIdea,
        Habit,
        HabitEvent,
        HealthSample,
        MemoryEvent,
        Occasion,
        Person,
        Setting,
        SiblingSnapshot,
        Workout,
    )

    with SessionLocal() as db:
        # --- vitals: steps today + 3 days ago, sleep (minutes), energy ---
        db.add(HealthSample(user_id=user_id, metric="step_count", ts_start=f"{_d(0)} 00:00:00", value=8123, unit="count", source="shortcut"))
        db.add(HealthSample(user_id=user_id, metric="step_count", ts_start=f"{_d(3)} 00:00:00", value=4000, unit="count", source="shortcut"))
        db.add(HealthSample(user_id=user_id, metric="sleep_asleep", ts_start=f"{_d(0)} 00:00:00", value=450, unit="min", source="shortcut"))
        db.add(HealthSample(user_id=user_id, metric="active_energy", ts_start=f"{_d(0)} 00:00:00", value=310, unit="kcal", source="shortcut"))
        # a sample outside the 14-day window must not appear
        db.add(HealthSample(user_id=user_id, metric="step_count", ts_start=f"{_d(20)} 00:00:00", value=99999, unit="count", source="shortcut"))

        # --- workouts: one today (this week), one 10 days ago ---
        db.add(Workout(user_id=user_id, wtype="strength", ts_start=f"{_d(0)} 12:00:00", duration_s=3120, kcal=310, source="Traditional Strength Training", provider_uid="w-1"))
        db.add(Workout(user_id=user_id, wtype="run", ts_start=f"{_d(10)} 12:00:00", duration_s=1800, kcal=250, source="Running", provider_uid="w-2"))

        # --- habits: gym (auto, done 2 days ago), reading (tap, never) ---
        gym = Habit(user_id=user_id, key="gym", title="Gym", kind="auto", target_json='{"per_week": 3}', evidence="workouts:wtype in cfg", active=1, config_json='{"wtypes": ["strength"]}')
        reading = Habit(user_id=user_id, key="reading", title="Reading", kind="tap", target_json='{"per_day": 1}', evidence="events:reading", active=1)
        inactive = Habit(user_id=user_id, key="walk", title="Walk", kind="auto", active=0)
        db.add_all([gym, reading, inactive])
        db.flush()
        db.add(HabitEvent(habit_id=gym.id, local_date=_d(2), value=1, source="auto"))

        # --- kakeibo + michi snapshots (contract fields only) ---
        db.add(SiblingSnapshot(app="kakeibo", fetched_at=_utcnow_str(), ok=1, latency_ms=15, payload_json=json.dumps({"goal_pence": 2000000, "saved_pence": 500000, "pct": 25.0, "pace_status": "on_pace", "as_of": _d(1)})))
        db.add(SiblingSnapshot(app="michi", fetched_at=_utcnow_str(), ok=1, latency_ms=20, payload_json=json.dumps({"streak_days": 12, "studied_today": True, "due_reviews": 3, "words_known": 210, "last_session_at": f"{_d(0)} 08:00:00"})))

        # --- weather snapshot (Open-Meteo daily shape, home only) ---
        db.add(SiblingSnapshot(app="weather", fetched_at=_utcnow_str(), ok=1, latency_ms=90, payload_json=json.dumps({"home": {"daily": {"time": [_d(0)], "temperature_2m_max": [19.5], "temperature_2m_min": [11.2], "precipitation_probability_max": [40], "weathercode": [61]}}})))

        # --- people/occasions/gifts: one inside window, one private-to-partner,
        #     one far outside the window ---
        person = Person(name="Taro Fixture", relation="friend")
        db.add(person)
        db.flush()
        inside = Occasion(person_id=person.id, title="Taro Fixture's birthday", month_day=(_today() + timedelta(days=10)).isoformat()[5:], recurrence="yearly", kind="birthday", lead_days=21)
        private = Occasion(person_id=None, title="Secret surprise", date=(_today() + timedelta(days=5)).isoformat(), recurrence="once", kind="event", private_to_user=partner_id)
        far = Occasion(person_id=None, title="Distant deadline", date=(_today() + timedelta(days=100)).isoformat(), recurrence="once", kind="deadline")
        db.add_all([inside, private, far])
        db.flush()
        db.add(GiftIdea(person_id=person.id, idea="A synthetic gift", status="idea", occasion_id=inside.id))

        # --- memory events: 2 today, 1 three days ago ---
        db.add(MemoryEvent(user_id=user_id, ts=f"{_d(0)} 10:00:00", kind="manual", title="t1", source="test", provider_uid="m-1"))
        db.add(MemoryEvent(user_id=user_id, ts=f"{_d(0)} 11:00:00", kind="manual", title="t2", source="test", provider_uid="m-2"))
        db.add(MemoryEvent(user_id=user_id, ts=f"{_d(3)} 11:00:00", kind="manual", title="t3", source="test", provider_uid="m-3"))

        # --- japan countdown: 30 days out ---
        db.add(Setting(key="japan_range", value_json=json.dumps({"start": (_today() + timedelta(days=30)).isoformat(), "end": (_today() + timedelta(days=44)).isoformat()})))

        db.commit()
        return {"person_id": person.id, "inside_occ_id": inside.id, "gym_id": gym.id, "reading_id": reading.id}


def test_dashboard_requires_jwt(client):
    assert client.get("/api/dashboard").status_code == 401


def test_dashboard_full_aggregate_shape_for_primary(client):
    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    partner_id = make_user(email="amy@example.com", display_name="Amy", role="partner")
    ids = _seed_full(primary_id, partner_id)

    res = client.get("/api/dashboard", headers=auth_headers(primary_id))
    assert res.status_code == 200
    body = res.json()

    assert set(body) == {
        "generated_at", "date", "role", "siblings", "japan", "away",
        "briefing", "vitals", "habits", "goal", "occasions",
        "memory_strip", "anniversary", "weather", "nudges_pending",
    }
    assert body["anniversary"] == []  # lookback hits need a past-year journal day
    assert body["role"] == "primary"
    assert body["briefing"] is None  # composes in Phase 6

    # vitals: 14-day series, today's aggregates, unit normalisation
    vitals = body["vitals"]
    assert len(vitals["series_days"]) == 14
    assert vitals["series_days"][-1] == _d(0)
    assert vitals["steps"]["today"] == 8123
    assert vitals["steps"]["series"][-4] == 4000
    assert vitals["steps"]["series"][0] is None  # sparse days stay null
    assert 99999 not in [v for v in vitals["steps"]["series"] if v]
    assert vitals["sleep_hours"]["today"] == 7.5  # 450 min -> hours
    assert vitals["active_kcal"]["today"] == 310
    assert vitals["workouts"]["this_week"] >= 1
    assert vitals["workouts"]["series"][-1] == 1

    # habits: gap maths off habit_events, inactive filtered, book slot present
    habits = {h["key"]: h for h in body["habits"]}
    assert set(habits) == {"gym", "reading"}
    assert habits["gym"]["last_date"] == _d(2)
    assert habits["gym"]["gap_days"] == 2
    assert habits["gym"]["done_today"] is False
    assert habits["reading"]["gap_days"] is None
    assert habits["reading"]["state"] == "empty"
    assert habits["reading"]["current_book"] is None

    # goal: the kakeibo snapshot verbatim + age
    goal = body["goal"]
    assert goal["pct"] == 25.0
    assert goal["pace_status"] == "on_pace"
    assert goal["age_seconds"] >= 0

    # occasions: window + surprise guard + gift pill
    occ_titles = [o["title"] for o in body["occasions"]]
    assert "Taro Fixture's birthday" in occ_titles
    assert "Secret surprise" not in occ_titles  # private to the partner
    assert "Distant deadline" not in occ_titles  # outside 45 days
    inside = next(o for o in body["occasions"] if o["id"] == ids["inside_occ_id"])
    assert inside["days_to_go"] == 10
    assert inside["in_lead_window"] is True
    assert inside["gift_status"] == "ideas"
    assert inside["person"]["name"] == "Taro Fixture"

    # memory strip: exactly 7 render-ready day dots
    strip = body["memory_strip"]
    assert len(strip) == 7
    assert strip[-1] == {"date": _d(0), "event_count": 2}
    assert strip[-4]["event_count"] == 1

    # siblings: Phase-3 status logic + latest ok contract payload
    siblings = {s["app"]: s for s in body["siblings"]}
    assert set(siblings) == {"michi", "kakeibo", "mishka"}
    assert siblings["michi"]["ok"] is True
    assert siblings["michi"]["data"]["streak_days"] == 12
    assert siblings["mishka"]["ok"] is None  # no snapshot at all
    assert siblings["mishka"]["data"] is None

    # weather: today's daily figures for the configured location
    assert body["weather"]["home"]["temp_max"] == 19.5
    assert body["weather"]["office"] is None

    # nudges: 0 until the coach exists (table absent -> still 0, not a 500)
    assert body["nudges_pending"] == 0

    # japan chip
    assert body["japan"] == {"days_to_go": 30}


def test_dashboard_null_safe_when_empty(client):
    """A fresh db paints an honest, empty bridge — nothing 500s."""
    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    res = client.get("/api/dashboard", headers=auth_headers(primary_id))
    assert res.status_code == 200
    body = res.json()
    assert body["goal"] is None  # kakeibo not_configured -> no ok rows
    assert body["weather"] is None
    assert body["japan"] is None
    assert body["habits"] == []
    assert body["occasions"] == []
    assert len(body["memory_strip"]) == 7
    assert all(d["event_count"] == 0 for d in body["memory_strip"])
    assert body["vitals"]["steps"]["today"] is None
    assert body["nudges_pending"] == 0


def test_dashboard_partner_gets_slim_redacted_response(client):
    """HANDOFF Q9 / DESIGN §3: server-side redaction, not CSS hiding — the
    partner response must not CONTAIN finance/people/vitals/habit/memory/
    nudge/briefing keys at all, even with a fully seeded db."""
    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    partner_id = make_user(email="amy@example.com", display_name="Amy", role="partner")
    _seed_full(primary_id, partner_id)

    res = client.get("/api/dashboard", headers=auth_headers(partner_id))
    assert res.status_code == 200
    body = res.json()

    assert set(body) == {"generated_at", "date", "role", "siblings", "japan", "away"}
    assert body["role"] == "partner"
    for forbidden in ("goal", "occasions", "vitals", "habits", "memory_strip", "nudges_pending", "briefing", "weather"):
        assert forbidden not in body
    # and nothing occasion/finance-shaped hides in the serialised body —
    # including inside sibling snapshot payloads (kakeibo is dropped wholesale)
    raw = res.text.lower()
    assert "secret surprise" not in raw
    assert "goal_pence" not in raw
    assert "kakeibo" not in raw
    # what the slim bridge DOES get: her Michi streak + Japan countdown
    assert {s["app"] for s in body["siblings"]} == {"michi", "mishka"}
    michi = next(s for s in body["siblings"] if s["app"] == "michi")
    assert michi["data"]["streak_days"] == 12
    assert body["japan"] == {"days_to_go": 30}


def test_dashboard_japan_zero_during_trip_and_null_after(client):
    from app.db import SessionLocal
    from app.models import Setting

    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    headers = auth_headers(primary_id)

    with SessionLocal() as db:
        db.add(Setting(key="japan_range", value_json=json.dumps({"start": _d(2), "end": (_today() + timedelta(days=5)).isoformat()})))
        db.commit()
    assert client.get("/api/dashboard", headers=headers).json()["japan"] == {"days_to_go": 0}

    with SessionLocal() as db:
        row = db.get(Setting, "japan_range")
        row.value_json = json.dumps({"start": _d(20), "end": _d(6)})
        db.commit()
    assert client.get("/api/dashboard", headers=headers).json()["japan"] is None  # sunsets after the trip


def test_dashboard_yearly_occasion_rolls_into_next_year(client):
    """A month_day that already passed this year resolves to next year —
    and lands outside the 45-day window unless genuinely close."""
    from app.db import SessionLocal
    from app.models import Occasion

    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    yesterday = _today() - timedelta(days=1)
    with SessionLocal() as db:
        db.add(Occasion(title="Rolled over", month_day=yesterday.isoformat()[5:], recurrence="yearly", kind="event"))
        db.commit()

    body = client.get("/api/dashboard", headers=auth_headers(primary_id)).json()
    assert "Rolled over" not in [o["title"] for o in body["occasions"]]  # ~364 days away


def test_dashboard_reading_habit_carries_current_book(client):
    from app.db import SessionLocal
    from app.models import Book, Habit

    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    with SessionLocal() as db:
        db.add(Habit(user_id=primary_id, key="reading", title="Reading", kind="tap", target_json='{"per_day": 1}'))
        db.add(Book(title="A Synthetic Book", author="N. O. Body", status="reading", started_on=_d(3)))
        db.add(Book(title="Already Done", status="finished", started_on=_d(30), finished_on=_d(9)))
        db.commit()

    body = client.get("/api/dashboard", headers=auth_headers(primary_id)).json()
    reading = next(h for h in body["habits"] if h["key"] == "reading")
    assert reading["current_book"]["title"] == "A Synthetic Book"
    assert reading["current_book"]["author"] == "N. O. Body"


def test_dashboard_away_field_for_both_roles(client):
    """COACH.md §6: the away chip data is household-level — null when home,
    {"title", "until"} for BOTH roles when a qualifying all-day event covers
    today. Uses real 'today' because the dashboard reads the live clock."""
    from tests.coach_helpers import add_all_day_event

    primary_id = make_user(email="mack@example.com", display_name="Mack", role="primary")
    partner_id = make_user(email="amy@example.com", display_name="Amy", role="partner")

    # home: away is null for both
    assert client.get("/api/dashboard", headers=auth_headers(primary_id)).json()["away"] is None
    assert client.get("/api/dashboard", headers=auth_headers(partner_id)).json()["away"] is None

    # a 5-day synthetic trip covering today (DTEND exclusive)
    start = (_today() - timedelta(days=1)).isoformat()
    end_exclusive = (_today() + timedelta(days=4)).isoformat()
    add_all_day_event(title="Somewhere with friends", start=start, end_exclusive=end_exclusive)

    expected = {"title": "Somewhere with friends", "until": (_today() + timedelta(days=3)).isoformat()}
    assert client.get("/api/dashboard", headers=auth_headers(primary_id)).json()["away"] == expected
    assert client.get("/api/dashboard", headers=auth_headers(partner_id)).json()["away"] == expected
