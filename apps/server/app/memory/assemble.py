"""Day assembly from ``memory_events`` — docs/MEMORY.md §3,
docs/phases/PHASE-7-memory.md item 2.

The zero-effort journal: a day assembles itself from the events the mappers
(app/memory/mappers.py) have already deposited in ``memory_events``, plus that
day's ``health_samples`` aggregates. ``summary_md`` is a deterministic,
slotted, rules-based template (no LLM): movement / study / events / films /
photos / milestone lines, empty slots skipped so a thin day reads honestly
short (MEMORY §1). ``stats_json`` carries the numbers the UI charts.

Determinism law (PHASE-7 acceptance): ``summary_md`` + ``stats_json`` +
``event_count`` are a pure function of the day's data. ``assembled_at`` is only
bumped when that content changes, so re-assembling an unchanged day leaves the
``journal_days`` row byte-identical. When late data (an HAE lag) does change a
day, the content updates and ``assembled_at`` moves — which is why the nightly
agent re-runs yesterday-1 as well as yesterday.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import HealthSample, JournalDay, MemoryEvent
from . import mappers
from . import movement as movement_mod

LONDON = ZoneInfo("Europe/London")

# Fixed slot order — the shape of every day, empty slots skipped (MEMORY §3).
_KIND_ORDER = ["workout", "study", "calendar", "place", "film", "photo", "finance", "milestone", "manual"]


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_date_of(ts_utc: str) -> str:
    dt = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def _utc_window(local_date: str) -> tuple[str, str]:
    """UTC string bounds that safely bracket a Europe/London calendar day
    (±1 day of slack absorbs the offset; callers re-filter by _local_date_of)."""
    d = date.fromisoformat(local_date)
    start = (d - timedelta(days=1)).isoformat()
    end = (d + timedelta(days=1)).isoformat()
    return f"{start} 00:00:00", f"{end} 23:59:59"


def _events_for(session: Session, local_date: str) -> list[MemoryEvent]:
    lo, hi = _utc_window(local_date)
    rows = session.scalars(
        select(MemoryEvent).where(MemoryEvent.ts >= lo, MemoryEvent.ts <= hi)
    ).all()
    same_day = [e for e in rows if _local_date_of(e.ts) == local_date]
    # Deterministic order: kind slot, then ts, then provider_uid (stable
    # tiebreak independent of insertion order / autoincrement id).
    same_day.sort(
        key=lambda e: (
            _KIND_ORDER.index(e.kind) if e.kind in _KIND_ORDER else len(_KIND_ORDER),
            e.ts,
            e.provider_uid,
        )
    )
    return same_day


def _steps_for(session: Session, local_date: str) -> int:
    lo, hi = _utc_window(local_date)
    rows = session.scalars(
        select(HealthSample).where(
            HealthSample.metric == "step_count",
            HealthSample.ts_start >= lo,
            HealthSample.ts_start <= hi,
        )
    ).all()
    total = 0.0
    for s in rows:
        if _local_date_of(s.ts_start) == local_date:
            total += s.value or 0.0
    return int(round(total))


def _detail(e: MemoryEvent) -> dict:
    try:
        d = json.loads(e.detail_json or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _stars(rating) -> str:
    try:
        n = int(round(float(rating)))
    except (ValueError, TypeError):
        return ""
    n = max(0, min(5, n))
    return "★" * n if n else ""


def _oxford(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])} and {items[-1]}"


# --------------------------------------------------------------- composing --
def compose_summary(
    local_date: str,
    events: list[MemoryEvent],
    steps: int,
    movement: dict | None = None,
) -> tuple[str, dict]:
    """Pure function: (summary_md, stats_json) from a day's events + steps +
    the optional movement block (movement.day_movement — trace/distance/away).

    No timestamps of *assembly* leak in — only the day's own data — so the
    output is byte-stable across re-runs (the determinism law)."""
    by_kind: dict[str, list[MemoryEvent]] = {}
    for e in events:
        by_kind.setdefault(e.kind, []).append(e)

    workouts = by_kind.get("workout", [])
    studies = by_kind.get("study", [])
    calendars = by_kind.get("calendar", [])
    places = by_kind.get("place", [])
    films = by_kind.get("film", [])
    photos = by_kind.get("photo", [])
    finances = by_kind.get("finance", [])
    milestones = by_kind.get("milestone", [])
    manuals = by_kind.get("manual", [])

    d = date.fromisoformat(local_date)
    weekday = d.strftime("%A")

    lines: list[str] = []

    # 1. Movement — steps as its own clause, then each workout on its own line
    # (the mapper already phrases them, e.g. "Strength, 52 min").
    if steps > 0:
        lines.append(_sentence(f"{steps:,} steps"))
    # The movement-trace line (MEMORY §2-3): figures are fine here — the
    # journal is the authed, primary-only app. The redaction gate applies to
    # pushes, and nothing push-shaped (coach/notify/briefing) ever reads
    # summary_md or stats_json (test_architecture_rules pins that).
    if movement is not None:
        km = movement.get("distance_m", 0) / 1000
        lines.append(_sentence(f"Out and about — {km:.1f} km on foot"))
    for w in workouts:
        lines.append(_sentence(w.title or "A workout"))

    # 2. Study
    if studies:
        title = studies[0].title or "Japanese study"
        lines.append(_sentence(title))

    # 3. Events (calendar + place)
    event_titles = [e.title for e in calendars if e.title] + [p.title for p in places if p.title]
    if event_titles:
        shown = event_titles[:3]
        extra = len(event_titles) - len(shown)
        joined = _oxford(shown)
        tail = f", and {extra} more" if extra > 0 else ""
        lines.append(_sentence(f"On the calendar: {joined}{tail}"))

    # 4. Films
    if films:
        rendered = []
        for f in films:
            title = f.title or "a film"
            stars = _stars(_detail(f).get("rating"))
            rendered.append(f"*{title}* {stars}".strip())
        verb = "Watched" if len(rendered) == 1 else "Watched"
        lines.append(_sentence(f"{verb} {_oxford(rendered)}"))

    # 5. Photos
    if photos:
        det = _detail(photos[0])
        count = det.get("count", 0)
        placelist = det.get("places") or []
        where = f" around {placelist[0]}" if placelist else ""
        lines.append(_sentence(f"{count} photo{'s' if count != 1 else ''} taken{where}"))

    # 6. Milestones + finance (celebrations)
    for m in milestones:
        if m.title:
            lines.append(_sentence(m.title))
    for f in finances:
        if f.title:
            lines.append(_sentence(f.title))
    for mn in manuals:
        if mn.title:
            lines.append(_sentence(mn.title))

    # A day with no logged events reads honestly short (MEMORY §1) — steps
    # alone is a "quiet Tuesday", not a full slotted entry. A movement trace
    # counts as something happening, so a walk-only day keeps its lines.
    if (not events and movement is None) or not lines:
        if steps > 0:
            body = f"A quiet {weekday} — {steps:,} steps, nothing else logged.\n"
        else:
            body = f"A quiet {weekday}, nothing logged.\n"
        summary_md = f"## {_pretty_date(d)}\n\n{body}"
    else:
        summary_md = f"## {_pretty_date(d)}\n\n" + "\n".join(lines) + "\n"

    stats = {
        "steps": steps,
        "workouts": len(workouts),
        "study": bool(studies),
        "study_streak": (_detail(studies[0]).get("streak_days") if studies else None),
        "films": len(films),
        "photos": sum(_detail(p).get("count", 0) for p in photos),
        "calendar": len(calendars),
        "places": len(places),
        "milestones": len(milestones) + len(finances),
        "events": len(events),
    }
    # Movement keys ride along only when a trace exists — absent keys keep
    # every pre-location day's stats_json byte-identical (determinism law),
    # and the UI degrades to nothing (MEMORY §5).
    if movement is not None:
        stats["trace"] = movement["trace"]
        stats["distance_m"] = movement["distance_m"]
        stats["away_min"] = movement["away_min"]
    return summary_md, stats


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] not in ".!?":
        text += "."
    return text


def _pretty_date(d: date) -> str:
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


# --------------------------------------------------------------- assembly ---
def _home_coords() -> tuple[float, float] | None:
    """SUKUMO_HOME_LAT/LON via the Settings object (the same pair weather
    already uses; docs/ARCHITECTURE.md §5.5 — .env only, never committed).
    None when either is unset: away_min degrades to null, never a crash."""
    s = get_settings()
    if s.home_lat is None or s.home_lon is None:
        return None
    return (s.home_lat, s.home_lon)


def assemble_day(
    session: Session,
    local_date: str,
    *,
    now: datetime | None = None,
    run_maps: bool = True,
) -> JournalDay:
    """Assemble (or re-assemble) one Europe/London day into ``journal_days``.

    Idempotent and deterministic: the row's ``assembled_at`` only moves when
    the composed content actually changes. Runs the ride-along mappers first
    (``run_maps``) so late snapshots/workouts land before composing — pass
    ``run_maps=False`` when a caller has already mapped (backfill loops)."""
    now = now or datetime.now(timezone.utc)
    if run_maps:
        mappers.run_mappers(session, now)

    events = _events_for(session, local_date)
    steps = _steps_for(session, local_date)
    movement = movement_mod.day_movement(session, local_date, home=_home_coords())
    summary_md, stats = compose_summary(local_date, events, steps, movement)
    stats_json = json.dumps(stats, sort_keys=True)
    event_count = len(events)

    row = session.get(JournalDay, local_date)
    if row is None:
        row = JournalDay(
            local_date=local_date,
            assembled_at=_utcnow_str(),
            summary_md=summary_md,
            stats_json=stats_json,
            event_count=event_count,
            mood=None,
        )
        session.add(row)
    else:
        changed = (
            row.summary_md != summary_md
            or row.stats_json != stats_json
            or row.event_count != event_count
        )
        if changed:
            row.summary_md = summary_md
            row.stats_json = stats_json
            row.event_count = event_count
            row.assembled_at = _utcnow_str()
        # mood is a human field — never touched by assembly.
    session.commit()
    return row


def assemble_range(
    session: Session, start: str, end: str, *, now: datetime | None = None
) -> dict:
    """Assemble every local day in ``[start, end]`` inclusive (backfill). Maps
    once up front, then composes each day with ``run_maps=False``."""
    now = now or datetime.now(timezone.utc)
    map_counts = mappers.run_mappers(session, now)
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    # Backfill only materialises days that HAVE something — a sparse archive
    # (e.g. years of photo history) must not manufacture thousands of "nothing
    # logged" rows for the gaps. The nightly job still writes honest quiet
    # days for yesterday (assemble_yesterday), which is where they belong.
    event_dates = {_local_date_of(t) for t in session.scalars(select(MemoryEvent.ts)).all()}
    sample_dates = {
        _local_date_of(t)
        for t in session.scalars(select(HealthSample.ts_start)).all()
    }
    populated = event_dates | sample_dates
    days = 0
    skipped = 0
    cur = d0
    while cur <= d1:
        iso = cur.isoformat()
        if iso in populated:
            assemble_day(session, iso, now=now, run_maps=False)
            days += 1
        else:
            skipped += 1
        cur += timedelta(days=1)
    return {"days": days, "skipped_empty": skipped, "mapped": map_counts}


def assemble_yesterday(session: Session, *, now: datetime | None = None) -> dict:
    """The nightly job (02:30): assemble yesterday AND re-run yesterday-1, so a
    late HAE sync that arrived after last night's run still lands (MEMORY §3)."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(LONDON).date()
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    mappers.run_mappers(session, now)
    assemble_day(session, day_before.isoformat(), now=now, run_maps=False)
    assemble_day(session, yesterday.isoformat(), now=now, run_maps=False)
    # Location retention rides the nightly (DATA_MODEL §8): raw points older
    # than 90 days go once their day's aggregate exists in journal_days.
    pruned = movement_mod.prune_location_points(session, now=now)
    return {
        "assembled": [day_before.isoformat(), yesterday.isoformat()],
        "pruned_location_points": pruned,
    }


def data_date_bounds(session: Session) -> tuple[str, str] | None:
    """Earliest→latest local date that has ANY memory_event or step sample —
    the span a full backfill should cover. None when the well is empty."""
    ev = session.scalars(select(MemoryEvent.ts)).all()
    hs = session.scalars(
        select(HealthSample.ts_start).where(HealthSample.metric == "step_count")
    ).all()
    all_ts = list(ev) + list(hs)
    if not all_ts:
        return None
    locals_ = sorted(_local_date_of(t) for t in all_ts)
    return locals_[0], locals_[-1]


# ----------------------------------------------------------- anniversary ---
def anniversary(session: Session, local_date: str) -> list[dict]:
    """"On this date in past years" (MEMORY §4): journal_days sharing the
    month-day of ``local_date`` but in an earlier year. Feeds the briefing's
    memory line — compounding payoff of starting now."""
    d = date.fromisoformat(local_date)
    md = f"-{d.month:02d}-{d.day:02d}"
    rows = session.scalars(
        select(JournalDay)
        .where(JournalDay.local_date.like(f"%{md}"), JournalDay.local_date < local_date)
        .order_by(JournalDay.local_date.desc())
    ).all()
    out = []
    for r in rows:
        ry = date.fromisoformat(r.local_date)
        if ry.month == d.month and ry.day == d.day:
            out.append(
                {
                    "local_date": r.local_date,
                    "years_ago": d.year - ry.year,
                    "summary_md": r.summary_md,
                    "stats": json.loads(r.stats_json or "{}"),
                }
            )
    return out
