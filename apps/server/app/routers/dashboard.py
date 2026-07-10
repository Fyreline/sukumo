"""GET /api/dashboard — THE aggregate: one response paints every bridge tile
(docs/API.md §1, docs/DESIGN.md §3, docs/phases/PHASE-4-dashboard.md).

Server-composed from tables + latest snapshots; the SPA does NO cross-source
assembly (docs/ARCHITECTURE.md §5.4). Sections:

- ``vitals``    daily aggregates + a 14-day series per metric from
                health_samples/workouts (steps, sleep hours, active kcal,
                workouts) — neutral display, no medical interpretation
                (docs/COACH.md §0).
- ``habits``    per-habit gap maths computed off habit_events at read time
                (DATA_MODEL §2 — no stored counter to corrupt), plus the
                current book on the reading card (HANDOFF Q1).
- ``goal``      the latest ok Kakeibo snapshot (API.md §4 contract fields
                only) with its age; null while Kakeibo is not_configured.
- ``occasions`` the next 45 days, honouring the ``private_to_user``
                surprise guard (DATA_MODEL §3).
- ``memory_strip`` last-7-day memory_events counts (sparse until Phase 7 —
                render the thread anyway).
- ``siblings``  the Phase-3 status logic (latest snapshot age/latency +
                consecutive failures) plus each app's latest OK contract
                payload, so the tiles/partner portal read snapshot data
                without a second call.
- ``weather``   today's daily figures for home/office from the latest ok
                weather snapshot (the Today tile's glyph strip, DESIGN §3.1).
- ``nudges_pending`` count of pending/snoozed nudges — the table arrives
                with the coach (Phase 5/6), so the count is read defensively
                and is 0 until then.
- ``japan``     days_to_go from the ``japan_range`` settings key when set.
- ``away``      away mode (COACH.md §6): null when home, else the detected
                trip's title + last away day. Household-level, so both roles
                get it.

**Partner portal redaction is enforced HERE, server-side** (DESIGN §3,
HANDOFF Q9): a ``role='partner'`` requester receives ONLY
generated_at/date/role/siblings/japan/away — no vitals, habits, goal, occasions,
memory strip, briefing, weather or nudge sections AT ALL, not CSS-hidden.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select, text as sql_text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import (
    Book,
    Briefing,
    GiftIdea,
    Habit,
    HabitEvent,
    HealthSample,
    MemoryEvent,
    Occasion,
    Person,
    Setting,
    SiblingSnapshot,
    User,
    Workout,
)
from .status import SIBLING_APPS, _age_seconds, _consecutive_failures

router = APIRouter(tags=["dashboard"])

LONDON = ZoneInfo("Europe/London")

VITALS_SERIES_DAYS = 14
OCCASIONS_WINDOW_DAYS = 45
MEMORY_STRIP_DAYS = 7


def _today_local() -> date:
    return datetime.now(timezone.utc).astimezone(LONDON).date()


def _local_date_of(ts_utc: str) -> str:
    """Naive-UTC '%Y-%m-%d %H:%M:%S' (or bare date) -> Europe/London date."""
    ts = ts_utc if " " in ts_utc else f"{ts_utc} 00:00:00"
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def _series_dates(today: date, days: int) -> list[str]:
    return [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]


# ------------------------------------------------------------------ vitals --
def _sleep_hours(value: float, unit: str | None) -> float:
    """health_samples stores sleep verbatim in whatever unit the phone sent
    (min for Shortcuts/HAE typically) — normalise to hours for display."""
    u = (unit or "").lower()
    if u.startswith("min"):
        return value / 60.0
    if u in ("s", "sec", "secs", "second", "seconds"):
        return value / 3600.0
    return value  # already hours (or unknown — display verbatim)


def _vitals(session: Session, user_id: int, today: date) -> dict:
    dates = _series_dates(today, VITALS_SERIES_DAYS)
    window_start = dates[0]

    sums: dict[str, dict[str, float]] = {"step_count": {}, "sleep_asleep": {}, "active_energy": {}}
    samples = session.scalars(
        select(HealthSample).where(
            HealthSample.user_id == user_id,
            HealthSample.metric.in_(tuple(sums)),
            # ts_start >= the day before the window start (UTC->London can
            # shift a late-evening sample forward a day) — cheap over-fetch,
            # exact grouping below.
            HealthSample.ts_start >= f"{(date.fromisoformat(window_start) - timedelta(days=1)).isoformat()} 00:00:00",
        )
    ).all()
    for s in samples:
        local = _local_date_of(s.ts_start)
        if local < window_start or local > dates[-1]:
            continue
        value = _sleep_hours(s.value, s.unit) if s.metric == "sleep_asleep" else s.value
        sums[s.metric][local] = sums[s.metric].get(local, 0.0) + value

    workout_counts: dict[str, int] = {}
    workouts = session.scalars(
        select(Workout).where(
            Workout.user_id == user_id,
            Workout.ts_start >= f"{(date.fromisoformat(window_start) - timedelta(days=1)).isoformat()} 00:00:00",
        )
    ).all()
    week_start = (today - timedelta(days=today.weekday())).isoformat()  # ISO Monday
    workouts_this_week = 0
    for w in workouts:
        local = _local_date_of(w.ts_start)
        if week_start <= local <= today.isoformat():
            workouts_this_week += 1
        if window_start <= local <= dates[-1]:
            workout_counts[local] = workout_counts.get(local, 0) + 1

    def metric_block(per_day: dict[str, float], round_to: int | None) -> dict:
        series = [
            (round(per_day[d], round_to) if round_to is not None else per_day[d]) if d in per_day else None
            for d in dates
        ]
        return {"today": series[-1], "series": series}

    return {
        "series_days": dates,
        "steps": metric_block({d: v for d, v in sums["step_count"].items()}, 0),
        "sleep_hours": metric_block(sums["sleep_asleep"], 1),
        "active_kcal": metric_block(sums["active_energy"], 0),
        "workouts": {
            "this_week": workouts_this_week,
            "series": [workout_counts.get(d, 0) for d in dates],
        },
    }


# ------------------------------------------------------------------ habits --
def _allowed_gap_days(target: dict) -> int:
    """How many days may pass before a habit reads as 'due': a per-day habit
    allows 1, a per-week n habit allows ceil(7/n) — pure display heuristic,
    the coach's real rules (COACH.md §3) own their own thresholds."""
    if target.get("per_day"):
        return 1
    per_week = target.get("per_week")
    if per_week:
        return max(1, math.ceil(7 / float(per_week)))
    return 2


def _habits(session: Session, user_id: int, today: date) -> list[dict]:
    habits = session.scalars(
        select(Habit).where(Habit.user_id == user_id, Habit.active == 1).order_by(Habit.id)
    ).all()

    current_book = session.scalars(
        select(Book).where(Book.status == "reading").order_by(Book.started_on.desc(), Book.id.desc())
    ).first()

    week_start = (today - timedelta(days=today.weekday())).isoformat()
    out = []
    for habit in habits:
        target = json.loads(habit.target_json or "{}")
        event_dates = sorted(
            set(
                session.scalars(
                    select(HabitEvent.local_date).where(HabitEvent.habit_id == habit.id)
                ).all()
            )
        )
        last_date = event_dates[-1] if event_dates else None
        gap_days = (today - date.fromisoformat(last_date)).days if last_date else None
        done_today = last_date == today.isoformat()
        week_count = sum(1 for d in event_dates if week_start <= d <= today.isoformat())
        if done_today:
            state = "done_today"
        elif gap_days is None:
            state = "empty"
        elif gap_days <= _allowed_gap_days(target):
            state = "ok"
        else:
            state = "due"
        entry = {
            "id": habit.id,
            "key": habit.key,
            "title": habit.title,
            "kind": habit.kind,
            "evidence": habit.evidence,
            "target": target,
            "last_date": last_date,
            "gap_days": gap_days,
            "done_today": done_today,
            "week_count": week_count,
            "state": state,
        }
        if habit.key == "reading":
            entry["current_book"] = (
                {"id": current_book.id, "title": current_book.title, "author": current_book.author}
                if current_book
                else None
            )
        out.append(entry)
    return out


# ------------------------------------------- snapshots (goal/siblings/weather)
def _latest_snapshot(session: Session, app: str, ok_only: bool = False) -> SiblingSnapshot | None:
    q = select(SiblingSnapshot).where(SiblingSnapshot.app == app)
    if ok_only:
        q = q.where(SiblingSnapshot.ok == 1)
    return session.scalars(q.order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())).first()


def _goal(session: Session) -> dict | None:
    """Latest ok Kakeibo snapshot -> the goal ring. Null-safe by design:
    while Kakeibo is not_configured there simply are no ok rows."""
    snap = _latest_snapshot(session, "kakeibo", ok_only=True)
    if snap is None or not snap.payload_json:
        return None
    payload = json.loads(snap.payload_json)
    return {
        "goal_pence": payload.get("goal_pence"),
        "saved_pence": payload.get("saved_pence"),
        "pct": payload.get("pct"),
        "pace_status": payload.get("pace_status"),
        "as_of": payload.get("as_of"),
        "age_seconds": _age_seconds(snap.fetched_at),
    }


def _siblings(session: Session) -> list[dict]:
    """The Phase-3 status logic (routers/status.py), plus each app's latest
    OK contract payload so tiles (and the partner portal's Michi streak /
    Mishka recents) read snapshot data without a second request."""
    out = []
    for app in SIBLING_APPS:
        latest = _latest_snapshot(session, app)
        latest_ok = _latest_snapshot(session, app, ok_only=True)
        out.append(
            {
                "app": app,
                "ok": bool(latest.ok) if latest else None,
                "age_seconds": _age_seconds(latest.fetched_at) if latest else None,
                "latency_ms": latest.latency_ms if latest else None,
                "consecutive_failures": _consecutive_failures(session, app),
                "data": json.loads(latest_ok.payload_json) if latest_ok and latest_ok.payload_json else None,
                "data_age_seconds": _age_seconds(latest_ok.fetched_at) if latest_ok else None,
            }
        )
    return out


def _weather(session: Session) -> dict | None:
    """Today's daily figures per configured location from the latest ok
    weather snapshot (Open-Meteo daily arrays, index 0 = today in
    Europe/London — clients/weather.py requests timezone=Europe/London)."""
    snap = _latest_snapshot(session, "weather", ok_only=True)
    if snap is None or not snap.payload_json:
        return None
    payload = json.loads(snap.payload_json)
    out: dict = {"age_seconds": _age_seconds(snap.fetched_at)}
    for location in ("home", "office"):
        forecast = payload.get(location)
        daily = (forecast or {}).get("daily") or {}
        try:
            out[location] = {
                "temp_max": daily["temperature_2m_max"][0],
                "temp_min": daily["temperature_2m_min"][0],
                "precip_prob": daily["precipitation_probability_max"][0],
                "weathercode": daily["weathercode"][0],
            }
        except (KeyError, IndexError, TypeError):
            out[location] = None
    return out


# --------------------------------------------------------------- occasions --
def _next_occurrence(occ: Occasion, today: date) -> date | None:
    """Resolve an occasion's next concrete date: 'once' rows carry it
    verbatim; 'yearly' rows roll month_day forward to this year or next.
    29 Feb birthdays observe on 1 Mar in non-leap years."""
    try:
        if occ.recurrence == "once":
            return date.fromisoformat(occ.date) if occ.date else None
        if not occ.month_day:
            return None
        month, day = (int(p) for p in occ.month_day.split("-"))
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:  # 29 Feb in a non-leap year
                candidate = date(year, 3, 1)
            if candidate >= today:
                return candidate
        return None
    except (ValueError, AttributeError):
        return None


def _gift_status(session: Session, occ: Occasion) -> str:
    """'none' | 'ideas' | 'bought' for the People-tile pill (DESIGN §3.5) —
    gifts linked to the occasion directly, or to its person."""
    clauses = [GiftIdea.occasion_id == occ.id]
    if occ.person_id is not None:
        clauses.append(GiftIdea.person_id == occ.person_id)
    gifts = session.scalars(select(GiftIdea).where(or_(*clauses))).all()
    if any(g.status in ("bought", "given") for g in gifts):
        return "bought"
    if gifts:
        return "ideas"
    return "none"


def _occasions(session: Session, user_id: int, today: date) -> list[dict]:
    rows = session.scalars(select(Occasion)).all()
    out = []
    for occ in rows:
        # Surprise guard (DATA_MODEL §3): a private occasion is visible ONLY
        # to the user it's private to.
        if occ.private_to_user is not None and occ.private_to_user != user_id:
            continue
        next_date = _next_occurrence(occ, today)
        if next_date is None:
            continue
        days_to_go = (next_date - today).days
        if days_to_go < 0 or days_to_go > OCCASIONS_WINDOW_DAYS:
            continue
        person = None
        if occ.person_id is not None:
            p = session.get(Person, occ.person_id)
            if p is not None:
                person = {"id": p.id, "name": p.name}
        out.append(
            {
                "id": occ.id,
                "title": occ.title,
                "kind": occ.kind,
                "date": next_date.isoformat(),
                "days_to_go": days_to_go,
                "lead_days": occ.lead_days,
                "in_lead_window": days_to_go <= occ.lead_days,
                "person": person,
                "gift_status": _gift_status(session, occ),
            }
        )
    out.sort(key=lambda o: (o["days_to_go"], o["id"]))
    return out


# ------------------------------------------------------------ memory strip --
def _anniversary(session: Session, today: date) -> list[dict]:
    """Today's "on this day" hits for the memory strip's fig line (MEMORY §4)
    — date + years_ago only; the journal owns the full summary."""
    from ..memory.assemble import anniversary

    return [
        {"local_date": h["local_date"], "years_ago": h["years_ago"]}
        for h in anniversary(session, today.isoformat())
    ]


def _memory_strip(session: Session, today: date) -> list[dict]:
    dates = _series_dates(today, MEMORY_STRIP_DAYS)
    counts = {d: 0 for d in dates}
    events = session.scalars(
        select(MemoryEvent).where(
            MemoryEvent.ts >= f"{(date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat()} 00:00:00"
        )
    ).all()
    for e in events:
        local = _local_date_of(e.ts)
        if local in counts:
            counts[local] += 1
    return [{"date": d, "event_count": counts[d]} for d in dates]


# ------------------------------------------------------------------- misc --
def _nudges_pending(session: Session) -> int:
    """Pending/snoozed nudge count. The nudges table is Phase 5/6 work
    (DATA_MODEL §4) — read it defensively so this is 0, not a 500, while the
    table doesn't exist yet."""
    try:
        n = session.execute(
            sql_text("SELECT COUNT(*) FROM nudges WHERE status IN ('pending', 'snoozed')")
        ).scalar()
        return int(n or 0)
    except OperationalError:
        return 0


def _briefing(session: Session, today: date) -> dict | None:
    """Today's morning briefing (DATA_MODEL §4), composed by the coach's
    briefing.py (COACH §3.1). Null until the coach has run today."""
    row = session.get(Briefing, today.isoformat())
    if row is None:
        return None
    return {"date": row.local_date, "content_md": row.content_md, "composed_by": row.composed_by}


def _away(session: Session) -> dict | None:
    """Away mode (COACH.md §6) — null when home, else the event title (may be
    null) and the last away day. Household-level and harmless, so BOTH roles
    receive it; the title is the same class of data as the calendar the
    household already shares."""
    from ..coach.away import away_status

    status = away_status(session, datetime.now(timezone.utc))
    if not status.away:
        return None
    return {"title": status.title, "until": status.until.isoformat() if status.until else None}


def _japan(session: Session, today: date) -> dict | None:
    """Days to go from the ``japan_range`` settings key
    ({"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}). 0 while the trip is on;
    null (no chip) when unset, malformed, or after the trip — the countdown
    sunsets and the memory engine takes over (COACH.md §3.11)."""
    row = session.get(Setting, "japan_range")
    if row is None:
        return None
    try:
        value = json.loads(row.value_json)
        start = date.fromisoformat(value["start"])
        end = date.fromisoformat(value.get("end", value["start"]))
    except (ValueError, KeyError, TypeError):
        return None
    if today < start:
        return {"days_to_go": (start - today).days}
    if start <= today <= end:
        return {"days_to_go": 0}
    return None


@router.get("/dashboard")
async def dashboard(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    user = session.get(User, user_id)
    role = user.role if user is not None else "partner"
    today = _today_local()

    if role != "primary":
        # Partner portal (DESIGN §3, HANDOFF Q9): the slim bridge — her Michi
        # streak, Mishka recents, Japan countdown. No finance, people,
        # occasion, vitals, habit, memory or nudge data leaves the server for
        # this role at v1 — including Kakeibo's snapshot payload, so its
        # sibling entry is dropped wholesale (goal_pence must never appear
        # in a partner response body).
        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "date": today.isoformat(),
            "role": role,
            "siblings": [s for s in _siblings(session) if s["app"] != "kakeibo"],
            "japan": _japan(session, today),
            "away": _away(session),
        }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "date": today.isoformat(),
        "role": role,
        "siblings": _siblings(session),
        "japan": _japan(session, today),
        "away": _away(session),
        "briefing": _briefing(session, today),  # composed by the coach (Phase 6)
        "vitals": _vitals(session, user_id, today),
        "habits": _habits(session, user_id, today),
        "goal": _goal(session),
        "occasions": _occasions(session, user_id, today),
        "memory_strip": _memory_strip(session, today),
        "anniversary": _anniversary(session, today),
        "weather": _weather(session),
        "nudges_pending": _nudges_pending(session),
    }
