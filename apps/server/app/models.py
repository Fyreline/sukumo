"""SQLAlchemy 2.x ORM models — mirrors docs/DATA_MODEL.md. Credentials live
in Mishka Hub (docs/AUTH.md); Sukumo only mirrors the household identity
plus its own session tokens. Timestamps are UTC ``"%Y-%m-%d %H:%M:%S"``
strings (the siblings' convention); all *local* semantics (habit
``local_date``, quiet hours, …) are computed in Europe/London at use time,
never baked into storage (DATA_MODEL preamble).

Phase 1 (scaffold) defined the identity tables auth needs. Phase 2
(docs/phases/PHASE-2-ingestion.md) adds DATA_MODEL §1's ``ingest_tokens``,
§2's health/habit tables, §5's ``memory_events``, §6's calendar/sibling
tables, and §7's ops tables. Phase 4 (docs/phases/PHASE-4-dashboard.md)
adds §2's ``books`` and §3's people/occasions/gift_ideas; coach (§4) is
its own later phase.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# datetime('now') default, shared by every *_at/created_at column that uses it.
NOW = text("datetime('now')")


# ============ users — one household identity, mirrored from Mishka Hub ============
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(nullable=False, unique=True)  # lower()
    display_name: Mapped[str] = mapped_column(nullable=False)  # refreshed at every login
    # 'primary' | 'partner' — set once, on first successful proxied login
    # (docs/AUTH.md §1: primary = email matches SUKUMO_PRIMARY_EMAIL).
    role: Mapped[str] = mapped_column(nullable=False, server_default=text("'partner'"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ refresh_tokens — line-for-line port of Michi's/Mishka's ============
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(nullable=False)
    revoked: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (Index("idx_refresh_user", "user_id", "revoked"),)


# ============ ingest_tokens — bearer auth for machines (DATA_MODEL §1) =====
class IngestToken(Base):
    __tablename__ = "ingest_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)  # e.g. 'health-mack-iphone'
    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True)  # sha256 of the raw token
    # 'ingest' | 'notify' | 'ingest+notify' — checked by app.auth.ingest_token_auth.
    scope: Mapped[str] = mapped_column(nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ health_samples / workouts — DATA_MODEL §2 =====================
class HealthSample(Base):
    __tablename__ = "health_samples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # canonical snake_case ('step_count', 'sleep_asleep', 'active_energy', …)
    # or, for anything not in app.ingest.health's mapping dict, the raw
    # (slugified) name verbatim — unknown metrics are stored, never dropped.
    metric: Mapped[str] = mapped_column(nullable=False)
    ts_start: Mapped[str] = mapped_column(nullable=False)
    ts_end: Mapped[str | None] = mapped_column(nullable=True)
    value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(nullable=False)  # 'shortcut' | 'hae'
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("user_id", "metric", "ts_start", "source", name="uq_health_sample"),
    )


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    wtype: Mapped[str] = mapped_column(nullable=False)  # mapped slug, e.g. 'strength'
    ts_start: Mapped[str] = mapped_column(nullable=False)
    ts_end: Mapped[str | None] = mapped_column(nullable=True)
    duration_s: Mapped[int | None] = mapped_column(nullable=True)
    kcal: Mapped[float | None] = mapped_column(nullable=True)
    distance_m: Mapped[float | None] = mapped_column(nullable=True)
    # raw workout name as sent by the phone (API.md §2c: "workouts map by
    # name -> wtype slug with the raw name kept in source").
    source: Mapped[str] = mapped_column(nullable=False)
    # real id from the payload (HAE) or, for Path A which can't provide a
    # stable uid, 'derived:{wtype}:{ts_start}' so re-posts stay idempotent.
    provider_uid: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("user_id", "provider_uid", "source", name="uq_workout"),
    )


# ============ habits / habit_events — DATA_MODEL §2 =========================
class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(nullable=False, unique=True)  # 'gym' | 'reading' | 'japanese' | 'walk'
    title: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # 'auto' | 'tap' | 'hybrid'
    target_json: Mapped[str] = mapped_column(nullable=False, server_default=text("'{}'"))
    # 'workouts:wtype in cfg' | 'events:reading' | 'michi:session' — the
    # literal string is the evidence TYPE; thresholds (e.g. which wtypes
    # count) live in config_json, not encoded in this column (DATA_MODEL §2).
    evidence: Mapped[str | None] = mapped_column(nullable=True)
    active: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    config_json: Mapped[str] = mapped_column(nullable=False, server_default=text("'{}'"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class HabitEvent(Base):
    __tablename__ = "habit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id"), nullable=False)
    local_date: Mapped[str] = mapped_column(nullable=False)  # 'YYYY-MM-DD', Europe/London
    value: Mapped[float] = mapped_column(nullable=False, server_default=text("1"))
    # 'auto' rows are re-derived (delete+rebuild per day) from evidence by
    # app.habits.derive_auto_habit_events; 'tap'/'coach_confirm' rows are
    # human signals and are never rebuilt over (DATA_MODEL §2).
    source: Mapped[str] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("habit_id", "local_date", "source", name="uq_habit_event"),
    )


# ============ books — DATA_MODEL §2 (the reading habit's companion) ========
class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(nullable=False)
    author: Mapped[str | None] = mapped_column(nullable=True)
    # 'reading' | 'finished' | 'abandoned' — the current read (shown on the
    # reading streak card, HANDOFF Q1) is the newest 'reading' row; finishing
    # one writes a memory_events milestone (routers/habits.py, DATA_MODEL §2).
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'reading'"))
    started_on: Mapped[str | None] = mapped_column(nullable=True)  # 'YYYY-MM-DD'
    finished_on: Mapped[str | None] = mapped_column(nullable=True)  # 'YYYY-MM-DD'
    notes: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ people / occasions / gift_ideas — DATA_MODEL §3 ===============
# The deliberate-manual corner: real names/birthdays are DATA, entered
# through the UI into the DB — they never appear in the repo
# (ARCHITECTURE §5.5). Calendar import only ever SUGGESTS (routers/people.py);
# nothing auto-creates a person.
class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)
    relation: Mapped[str | None] = mapped_column(nullable=True)
    birthday: Mapped[str | None] = mapped_column(nullable=True)  # 'YYYY-MM-DD'
    notes: Mapped[str | None] = mapped_column(nullable=True)
    archived: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class Occasion(Base):
    __tablename__ = "occasions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    title: Mapped[str] = mapped_column(nullable=False)
    # Exactly ONE of month_day ('09-22', for recurrence='yearly') or date
    # ('YYYY-MM-DD', for recurrence='once') is set — enforced in the router.
    month_day: Mapped[str | None] = mapped_column(nullable=True)
    date: Mapped[str | None] = mapped_column(nullable=True)
    recurrence: Mapped[str] = mapped_column(nullable=False)  # 'yearly' | 'once'
    lead_days: Mapped[int] = mapped_column(nullable=False, server_default=text("21"))
    kind: Mapped[str] = mapped_column(nullable=False, server_default=text("'event'"))  # birthday|anniversary|event|deadline
    # Surprise guard (DATA_MODEL §3, PRIVATE §2 ⚠️): when set, ONLY this user
    # ever sees the occasion. Required before the partner portal may ever
    # render occasion data (it doesn't at v1 regardless — dashboard.py).
    private_to_user: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class GiftIdea(Base):
    __tablename__ = "gift_ideas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    idea: Mapped[str] = mapped_column(nullable=False)
    url: Mapped[str | None] = mapped_column(nullable=True)
    price_pence: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'idea'"))  # 'idea'|'bought'|'given'
    occasion_id: Mapped[int | None] = mapped_column(ForeignKey("occasions.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ memory_events — DATA_MODEL §5 =================================
class MemoryEvent(Base):
    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # household events (e.g. a shared calendar item) are allowed a NULL owner.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ts: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # photo|film|study|place|calendar|finance|workout|manual|milestone
    title: Mapped[str | None] = mapped_column(nullable=True)
    detail_json: Mapped[str] = mapped_column(nullable=False, server_default=text("'{}'"))
    source: Mapped[str] = mapped_column(nullable=False)
    provider_uid: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("source", "provider_uid", name="uq_memory_event"),
    )


# ============ calendar_events / sibling_snapshots — DATA_MODEL §6 ==========
class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ics_uid: Mapped[str] = mapped_column(nullable=False)
    starts_at: Mapped[str] = mapped_column(nullable=False)
    ends_at: Mapped[str | None] = mapped_column(nullable=True)
    all_day: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    title: Mapped[str | None] = mapped_column(nullable=True)
    location: Mapped[str | None] = mapped_column(nullable=True)
    # per-feed label used as the "full-window replace" key (app.clients.calendar
    # derives it from the feed's X-WR-CALNAME, falling back to 'feed-{i}').
    calendar_name: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("ics_uid", "starts_at", name="uq_calendar_event"),
        Index("idx_calendar_events_window", "calendar_name", "starts_at"),
    )


class SiblingSnapshot(Base):
    __tablename__ = "sibling_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app: Mapped[str] = mapped_column(nullable=False)  # 'michi'|'kakeibo'|'mishka'|'weather'|'calendar'
    fetched_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)
    ok: Mapped[int] = mapped_column(nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    payload_json: Mapped[str | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (Index("idx_sibling_snapshots_app", "app", "fetched_at"),)


# ============ sync_runs / settings — DATA_MODEL §7 (operations) ============
class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(nullable=False)  # 'ingest:health'|'poll:calendar'|…
    started_at: Mapped[str] = mapped_column(nullable=False)
    finished_at: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)  # 'ok'|'error'|'not_configured'
    items: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (Index("idx_sync_runs_source", "source", "started_at"),)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value_json: Mapped[str] = mapped_column(nullable=False)
    updated_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)
