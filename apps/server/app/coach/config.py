"""Coach configuration accessors — docs/COACH.md §2-3, docs/DATA_MODEL.md §7.

Everything the coach can be tuned by lives in the DB, never in code
(DATA_MODEL §2/§7): per-rule thresholds in a habit's ``config_json``, and the
household-wide knobs (quiet hours, daily cap, per-rule enable/disable, the
office pattern) in the ``settings`` table. The ONLY values invented here are
the three the docs explicitly bless as defaults (COACH §2-3): the 4-day gym
gap floor, the daily cap of 5, and the 22:30-07:30 quiet-hours window. Every
other missing value makes its rule report ``not_configured`` — never a guessed
nudge (COACH §3).
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Habit, Setting, User

# --- settings-table keys the coach reads/writes -----------------------------
KEY_QUIET_HOURS = "coach_quiet_hours"
KEY_DAILY_CAP = "coach_daily_cap"
KEY_DISABLED_RULES = "coach_disabled_rules"
KEY_OFFICE_PATTERN = "office_pattern"
KEY_JAPAN_RANGE = "japan_range"
KEY_LOW_MOVEMENT = "low_movement"  # {"step_threshold": N}
KEY_AWAY_DETECTION = "away_detection"  # {"min_days": N, "exclude_titles": [..]}
KEY_AWAY_OVERRIDE = "away_override"  # {"away_until": "YYYY-MM-DD", "title": "…"}
KEY_AWAY_SUPPRESSED_RULES = "away_suppressed_rules"  # ["rule-key", ...]

# --- the doc-blessed defaults (COACH §2-3, §6) — the only invented values ----
DEFAULT_DAILY_CAP = 5
DEFAULT_GYM_GAP_FLOOR_DAYS = 4
DEFAULT_AWAY_MIN_DAYS = 3  # a multi-day trip = two nights or more (COACH §6)
DEFAULT_AWAY_SUPPRESSED_RULES = ("gym-day", "office-day", "low-movement", "reading")


def get_setting(session: Session, key: str, default=None):
    row = session.get(Setting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value_json)
    except (ValueError, TypeError):
        return default


def set_setting(session: Session, key: str, value) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value_json=json.dumps(value)))
    else:
        row.value_json = json.dumps(value)


def get_habit(session: Session, key: str) -> Habit | None:
    return session.scalar(select(Habit).where(Habit.key == key, Habit.active == 1))


def habit_config(habit: Habit | None) -> dict:
    if habit is None:
        return {}
    try:
        return json.loads(habit.config_json or "{}")
    except (ValueError, TypeError):
        return {}


def primary_user(session: Session) -> User | None:
    return session.scalar(select(User).where(User.role == "primary"))


def daily_cap(session: Session) -> int:
    raw = get_setting(session, KEY_DAILY_CAP, DEFAULT_DAILY_CAP)
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return DEFAULT_DAILY_CAP


def quiet_hours(session: Session, settings: Settings) -> str:
    """Settings-table override wins; otherwise the env/config default (which is
    itself the doc's 22:30-07:30)."""
    override = get_setting(session, KEY_QUIET_HOURS, None)
    if isinstance(override, str) and "-" in override:
        return override
    return settings.quiet_hours


def disabled_rules(session: Session) -> set[str]:
    raw = get_setting(session, KEY_DISABLED_RULES, [])
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set()


def rule_enabled(session: Session, rule_key: str) -> bool:
    return rule_key not in disabled_rules(session)


def away_suppressed_rules(session: Session) -> set[str]:
    """The rule keys away mode silences (COACH §6) — the local-routine rules
    by default; settings-overridable like every other knob."""
    raw = get_setting(session, KEY_AWAY_SUPPRESSED_RULES, None)
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set(DEFAULT_AWAY_SUPPRESSED_RULES)
