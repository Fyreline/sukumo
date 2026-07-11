"""Source mappers — fill ``memory_events`` from the domain tables the rest of
Sukumo already keeps (docs/MEMORY.md §2, docs/phases/PHASE-7-memory.md item 1).

Every mapper is idempotent on ``(source, provider_uid)`` — the same
UNIQUE the ingesters use (DATA_MODEL §5) — so assembly can re-run any day
forever without double-writing. They ride *existing* data:

* ``map_workouts``  — ``workouts`` table          → kind ``workout``
* ``map_study``     — michi ``sibling_snapshots`` → kind ``study``
* ``map_films``     — mishka ``sibling_snapshots``→ kind ``film``
* ``map_calendar``  — past ``calendar_events``    → kind ``calendar``
* ``map_finance``   — goal-milestone ``nudges``   → kind ``finance``

The ``place`` / ``manual`` / ``milestone`` sources already land in
``memory_events`` directly (app/ingest/events.py) and the books→milestone
mapper already writes at finish time (app/routers/habits.py) — assembly just
reads those; they are NOT re-mapped here. Photos live in app/memory/photos.py
(metadata only, opt-in).

Copy that ends up in ``title`` is the household voice (COACH §5): warm, brief,
neutral — no figures that read as measurements (ARCHITECTURE §5.2). Personal
strings (film/calendar titles) are DATA that pass through verbatim; they never
appear in this module's code or in fixtures.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CalendarEvent, MemoryEvent, Nudge, SiblingSnapshot, User, Workout

LONDON = ZoneInfo("Europe/London")


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_date_of(ts_utc: str) -> str:
    """Europe/London calendar date of a stored UTC timestamp (DATA_MODEL
    preamble: local semantics computed at use time)."""
    dt = datetime.strptime(ts_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).date().isoformat()


def _upsert(
    session: Session,
    *,
    source: str,
    provider_uid: str,
    kind: str,
    ts: str,
    title: str | None,
    detail: dict,
    user_id: int | None = None,
) -> bool:
    """Insert a memory_event if ``(source, provider_uid)`` is new; otherwise
    refresh its mutable fields (title/detail/ts can change as a snapshot is
    re-polled). Returns True when a NEW row was created."""
    existing = session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.source == source, MemoryEvent.provider_uid == provider_uid
        )
    )
    detail_json = json.dumps(detail, sort_keys=True)
    if existing is None:
        session.add(
            MemoryEvent(
                user_id=user_id,
                ts=ts,
                kind=kind,
                title=title,
                detail_json=detail_json,
                source=source,
                provider_uid=provider_uid,
            )
        )
        # SessionLocal is autoflush=False, so flush now: a later upsert in the
        # SAME mapper run (e.g. two michi snapshots on one day) must see this
        # pending row via its SELECT, or it would re-insert and trip the
        # (source, provider_uid) UNIQUE.
        session.flush()
        return True
    # keep the well fresh but never move the identity
    existing.ts = ts
    existing.kind = kind
    existing.title = title
    existing.detail_json = detail_json
    return False


# --------------------------------------------------------------- workouts --
_WTYPE_LABEL = {
    "strength": "Strength",
    "traditional_strength_training": "Strength",
    "functional_strength_training": "Strength",
    "running": "Run",
    "walking": "Walk",
    "cycling": "Cycle",
    "hiit": "HIIT",
    "yoga": "Yoga",
    "swimming": "Swim",
}


def _workout_title(wtype: str, duration_s: int | None) -> str:
    label = _WTYPE_LABEL.get(wtype, wtype.replace("_", " ").title() if wtype else "Workout")
    if duration_s:
        mins = round(duration_s / 60)
        if mins > 0:
            return f"{label}, {mins} min"
    return label


def map_workouts(session: Session) -> int:
    """``workouts`` → memory_events(kind='workout'). provider_uid rides the
    workout's own (idempotent) provider_uid so a re-posted HAE workout maps
    once (MEMORY §2)."""
    created = 0
    for w in session.scalars(select(Workout)).all():
        made = _upsert(
            session,
            source="workouts",
            provider_uid=f"workout:{w.provider_uid}",
            kind="workout",
            ts=w.ts_start,
            title=_workout_title(w.wtype, w.duration_s),
            detail={"wtype": w.wtype, "duration_s": w.duration_s, "kcal": w.kcal},
            user_id=w.user_id,
        )
        created += int(made)
    return created


# ------------------------------------------------------------------ study --
def _snapshots(session: Session, app: str) -> list[SiblingSnapshot]:
    return list(
        session.scalars(
            select(SiblingSnapshot)
            .where(SiblingSnapshot.app == app, SiblingSnapshot.ok == 1)
            .order_by(SiblingSnapshot.fetched_at.asc(), SiblingSnapshot.id.asc())
        ).all()
    )


def _payload(snap: SiblingSnapshot) -> dict | None:
    if not snap.payload_json:
        return None
    try:
        data = json.loads(snap.payload_json)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def map_study(session: Session) -> int:
    """Michi snapshots → memory_events(kind='study'), one per local day a
    session happened (``studied_today`` truthy). provider_uid ``michi:<date>``
    (MEMORY §2) keeps it idempotent per day; the latest snapshot of a day wins
    on re-map (streak/word counts are refreshed in place)."""
    created = 0
    for snap in _snapshots(session, "michi"):
        payload = _payload(snap)
        if not payload or not payload.get("studied_today"):
            continue
        local_date = _local_date_of(snap.fetched_at)
        streak = payload.get("streak_days")
        words = payload.get("words_known")
        title = "Japanese study"
        if isinstance(streak, int) and streak > 1:
            title = f"Japanese study — {streak}-day streak"
        made = _upsert(
            session,
            source="michi",
            provider_uid=f"michi:{local_date}",
            kind="study",
            ts=snap.fetched_at,
            title=title,
            detail={"streak_days": streak, "words_known": words},
        )
        created += int(made)
    return created


def _primary_email(session: Session) -> str | None:
    """The household's primary user's email (User.role == 'primary'),
    looked up fresh each call rather than hardcoded — see docs/AUTH.md §1
    (role is set once, at first proxied login, from SUKUMO_PRIMARY_EMAIL).
    Returns None if no primary user exists yet (e.g. before first login)."""
    user = session.scalar(select(User).where(User.role == "primary"))
    return user.email if user else None


# ------------------------------------------------------------------ films --
def map_films(session: Session) -> int:
    """Mishka snapshots' ``recent`` watches → memory_events(kind='film').

    Mishka's household feed carries every watch by either housemate
    (API.md §4: ``recent[].user_email``). Sukumo's journal is Mack's — only
    watches whose ``user_email`` matches the primary user (looked up from the
    users table, never hardcoded) are mapped; the partner's watches are
    skipped entirely (not stored as memory_events at all, not just hidden in
    the UI). If there's no primary user yet, nothing is attributable, so
    nothing is mapped.

    The read-contract carries no stable watch id, so provider_uid is derived
    from ``watched_at`` + a short hash of the title — stable across re-polls
    (same watch → same uid) without embedding the raw title in the key. The
    title itself is DATA and passes through to the row verbatim."""
    primary_email = _primary_email(session)
    if not primary_email:
        return 0
    created = 0
    seen: set[str] = set()
    for snap in _snapshots(session, "mishka"):
        payload = _payload(snap)
        if not payload:
            continue
        for item in payload.get("recent") or []:
            if not isinstance(item, dict):
                continue
            watched_at = item.get("watched_at")
            title = item.get("title")
            if not watched_at or not title:
                continue
            item_email = item.get("user_email")
            if not isinstance(item_email, str) or item_email.lower() != primary_email.lower():
                continue
            title_hash = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
            provider_uid = f"mishka:{watched_at}:{title_hash}"
            if provider_uid in seen:
                continue
            seen.add(provider_uid)
            ts = _watched_ts(watched_at)
            made = _upsert(
                session,
                source="mishka",
                provider_uid=provider_uid,
                kind="film",
                ts=ts,
                title=title,
                detail={"rating": item.get("rating"), "poster_url": item.get("poster_url")},
            )
            created += int(made)
    return created


def _watched_ts(watched_at: str) -> str:
    """Normalise a watched_at (bare date or datetime, possibly ISO-'T' /
    tz-aware) to the stored UTC ``%Y-%m-%d %H:%M:%S`` shape. A bare date
    becomes local-midnight-as-UTC; unparseable input keeps its date half."""
    raw = str(watched_at).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[: 19 if " " in raw else 10], fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return f"{raw[:10]} 00:00:00" if len(raw) >= 10 else _utcnow_str()


# --------------------------------------------------------------- calendar --
def map_calendar(session: Session, now: datetime | None = None) -> int:
    """Past (attended) calendar_events → memory_events(kind='calendar').

    Only events whose start is in the past are mapped (MEMORY §2: "*attended*
    (past) events") — a future meeting isn't a memory yet. provider_uid pairs
    the ics_uid with the start so a recurring series' instances stay distinct
    (mirrors the calendar_events UNIQUE, DATA_MODEL §6)."""
    now = now or datetime.now(timezone.utc)
    now_str = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    created = 0
    rows = session.scalars(
        select(CalendarEvent).where(CalendarEvent.starts_at < now_str)
    ).all()
    for e in rows:
        title = (e.title or "").strip() or None
        made = _upsert(
            session,
            source="calendar",
            provider_uid=f"{e.ics_uid}:{e.starts_at}",
            kind="calendar",
            ts=e.starts_at,
            title=title,
            detail={
                "location": e.location,
                "all_day": bool(e.all_day),
                "calendar_name": e.calendar_name,
            },
        )
        created += int(made)
    return created


# ---------------------------------------------------------------- finance --
def map_finance(session: Session) -> int:
    """House-pot milestone nudges → memory_events(kind='finance'). Labels
    only, never a figure (MEMORY §2, ARCHITECTURE §5.2): the nudge already
    passed the redaction gate as a percentage label. provider_uid rides the
    nudge dedupe_key (``goal:<pct5>``) so each boundary maps once, ever."""
    created = 0
    rows = session.scalars(
        select(Nudge).where(Nudge.rule_key == "goal-milestone")
    ).all()
    for n in rows:
        pct = n.dedupe_key.split(":", 1)[1] if ":" in n.dedupe_key else None
        title = f"House pot crossed {pct}%" if pct else "A house-pot milestone"
        made = _upsert(
            session,
            source="finance",
            provider_uid=n.dedupe_key,
            kind="finance",
            ts=n.scheduled_for,
            title=title,
            detail={"label": pct},
            user_id=n.user_id,
        )
        created += int(made)
    return created


# ------------------------------------------------------------------- all ---
def run_mappers(session: Session, now: datetime | None = None) -> dict[str, int]:
    """Run every ride-along mapper once, commit, return per-source new-row
    counts. Called at the head of assembly (so late-arriving snapshots/workouts
    land before the day is composed) and safe to call from the poll tick."""
    counts = {
        "workouts": map_workouts(session),
        "study": map_study(session),
        "films": map_films(session),
        "calendar": map_calendar(session, now),
        "finance": map_finance(session),
    }
    session.commit()
    return counts
