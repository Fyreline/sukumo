"""The 07:35 morning briefing — docs/COACH.md §3.1, §5, docs/DATA_MODEL.md §4.

The briefing is the **digest of the same proposals the rules emit** (COACH
§3.1: "not a second brain"), plus the ambient summaries — weather, today's
calendar top lines, streak/gap states, occasions in the lead window, the Japan
countdown. ``compose`` returns ``(content_md, push_body)``: the markdown is
stored in the ``briefings`` row and surfaced on the dashboard; the push_body is
the short first-push-of-the-day text (COACH §5: warm, ≤2 sentences, one emoji).

Redaction (ARCHITECTURE §5.2): the push_body and every markdown line carry
categories, not figures — no temperatures-as-health, no balances. The weather
line says "rain likely", never a number that could read as a measurement.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import CalendarEvent, Habit, HabitEvent, Occasion, SiblingSnapshot
from . import config as coach_config
from .proposals import LONDON, NudgeProposal, parse_utc


def _today(now: datetime) -> date:
    return now.astimezone(LONDON).date()


def _latest_ok_snapshot(session: Session, app: str) -> dict | None:
    snap = session.scalars(
        select(SiblingSnapshot)
        .where(SiblingSnapshot.app == app, SiblingSnapshot.ok == 1)
        .order_by(SiblingSnapshot.fetched_at.desc(), SiblingSnapshot.id.desc())
    ).first()
    if snap is None or not snap.payload_json:
        return None
    try:
        return json.loads(snap.payload_json)
    except (ValueError, TypeError):
        return None


def _weather_line(session: Session, now: datetime) -> str | None:
    payload = _latest_ok_snapshot(session, "weather")
    if not payload:
        return None
    # Prefer the office forecast (the commute is what the briefing frames), else home.
    for loc in ("office", "home"):
        daily = (payload.get(loc) or {}).get("daily") or {}
        try:
            precip = daily["precipitation_probability_max"][0]
        except (KeyError, IndexError, TypeError):
            continue
        where = "commute" if loc == "office" else "at home"
        if precip is None:
            return None
        if precip >= 60:
            return f"Rain looks likely {where} — layers and a brolly. \U0001f327️"
        if precip >= 30:
            return f"A chance of showers {where} today."
        return f"Dry {where} today."
    return None


def _calendar_lines(session: Session, now: datetime, limit: int = 3) -> list[str]:
    today = _today(now)
    start = f"{today.isoformat()} 00:00:00"
    end = f"{today.isoformat()} 23:59:59"
    rows = session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.starts_at >= start, CalendarEvent.starts_at <= end)
        .order_by(CalendarEvent.starts_at)
    ).all()
    lines = []
    for e in rows[:limit]:
        title = (e.title or "Untitled").strip()
        if e.all_day:
            lines.append(f"- {title} (all day)")
        else:
            hhmm = parse_utc(e.starts_at).astimezone(LONDON).strftime("%H:%M")
            lines.append(f"- {hhmm} {title}")
    return lines


def _streak_lines(session: Session, now: datetime) -> list[str]:
    today = _today(now)
    lines = []
    habits = session.scalars(select(Habit).where(Habit.active == 1).order_by(Habit.id)).all()
    for habit in habits:
        dates = sorted(
            set(session.scalars(select(HabitEvent.local_date).where(HabitEvent.habit_id == habit.id)).all())
        )
        if not dates:
            continue
        last = date.fromisoformat(dates[-1])
        gap = (today - last).days
        if gap == 0:
            lines.append(f"- {habit.title}: done today ✓")
        elif gap == 1:
            lines.append(f"- {habit.title}: last logged yesterday")
        else:
            lines.append(f"- {habit.title}: {gap} days since the last one")
    return lines


def _occasion_lines(session: Session, now: datetime) -> list[str]:
    today = _today(now)
    lines = []
    for occ in session.scalars(select(Occasion)).all():
        target = _next_occurrence(occ, today)
        if target is None:
            continue
        days = (target - today).days
        if 0 <= days <= occ.lead_days:
            when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
            lines.append(f"- {occ.title} {when}")
    return lines


def _next_occurrence(occ: Occasion, today: date) -> date | None:
    try:
        if occ.recurrence == "once":
            return date.fromisoformat(occ.date) if occ.date else None
        if not occ.month_day:
            return None
        month, day = (int(p) for p in occ.month_day.split("-"))
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                candidate = date(year, 3, 1)
            if candidate >= today:
                return candidate
        return None
    except (ValueError, AttributeError, TypeError):
        return None


def _japan_line(session: Session, now: datetime) -> str | None:
    value = coach_config.get_setting(session, coach_config.KEY_JAPAN_RANGE, None)
    if not isinstance(value, dict) or "start" not in value:
        return None
    try:
        start = date.fromisoformat(value["start"])
    except (ValueError, TypeError):
        return None
    today = _today(now)
    days = (start - today).days
    if days < 0:
        return None
    if days == 0:
        return "Japan starts today. ✈️"
    return f"Japan in {days} days."


def compose(
    session: Session, now: datetime, settings: Settings, proposals: list[NudgeProposal]
) -> tuple[str, str]:
    """Returns (content_md, push_body)."""
    today = _today(now)
    weekday = today.strftime("%A")
    greeting = f"# Good morning — {weekday} {today.strftime('%-d %B')}"

    sections: list[str] = [greeting]

    weather = _weather_line(session, now)
    if weather:
        sections.append(f"\n{weather}")

    cal = _calendar_lines(session, now)
    if cal:
        sections.append("\n**Today**\n" + "\n".join(cal))

    streaks = _streak_lines(session, now)
    if streaks:
        sections.append("\n**Habits**\n" + "\n".join(streaks))

    # The digest of the rules' own proposals (COACH §3.1) — the coach's voice,
    # not a re-derivation. Skip the briefing's own placeholder.
    nudge_lines = [f"- {p.title}" for p in proposals if p.rule_key != "morning-briefing"]
    if nudge_lines:
        sections.append("\n**On the coach's mind**\n" + "\n".join(nudge_lines))

    occ = _occasion_lines(session, now)
    if occ:
        sections.append("\n**Coming up**\n" + "\n".join(occ))

    japan = _japan_line(session, now)
    if japan:
        sections.append(f"\n{japan}")

    content_md = "\n".join(sections).strip() + "\n"

    # push_body: the single most salient thing + a gentle count (COACH §5).
    salient = weather or (nudge_lines[0][2:] if nudge_lines else None) or (cal[0][2:] if cal else None)
    noted = len(nudge_lines)
    if salient and noted:
        push_body = f"{salient} {noted} thing{'s' if noted != 1 else ''} noted for today."
    elif salient:
        push_body = f"{salient} A clear run otherwise."
    else:
        push_body = "Here's your day — a clear run ahead."
    # keep the push comfortably short
    push_body = push_body.strip()
    return content_md, push_body
