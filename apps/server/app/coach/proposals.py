"""Shared coach primitives: the ``NudgeProposal`` a rule emits, the
``RuleResult`` wrapper that also carries a ``not_configured``/``stale`` skip
reason for the tick's per-stage counts, the ``Rule`` registry object, and the
Europe/London timing helpers every rule shares — docs/COACH.md §1, §4.

Design (docs/COACH.md §4, "scheduled_for carries the intended minute"):

- A rule emits a proposal for its *current cycle* whenever the DATA condition
  holds. ``scheduled_for`` is the cycle's intended delivery instant.
- Timing helpers give two shapes:
    * ``today_trigger_if_past`` — today's HH:MM, but only once ``now`` has
      reached it (returns ``None`` before). No look-back: a rule using this
      simply doesn't fire on a day the machine slept through the moment.
    * ``most_recent_trigger`` — the most recent past HH:MM (today's if reached,
      else yesterday's). A rule using this *does* look back one cycle, so the
      engine can turn a slept-through moment into an ``expired`` nudge rather
      than a late push (the COACH.md §4 reading scenario).
- ``expiry`` is the per-rule horizon: once ``now > scheduled_for + expiry`` the
  engine writes the nudge ``expired`` instead of pushing. ``expiry=None`` means
  "never expires" — such a proposal is held through quiet hours to the morning
  window instead (the 23:00→07:30 path).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

LONDON = ZoneInfo("Europe/London")

# Highest kept first when the daily cap bites (docs/COACH.md §2). v1 ships zero
# 'high' rules; the ladder exists so a future urgent rule sorts above routine
# ones and (in notify.send) bypasses the quiet-hours hold.
PRIORITY_RANK = {"high": 2, "default": 1, "low": 0}


# ============================================================================
# Timing helpers — every rule computes local moments in Europe/London
# ============================================================================
def utc_str(dt: datetime) -> str:
    """Aware datetime -> the naive-UTC '%Y-%m-%d %H:%M:%S' string the schema
    stores (DATA_MODEL preamble)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(s: str) -> datetime:
    """Inverse of ``utc_str`` — a stored timestamp back to an aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def local(now: datetime) -> datetime:
    return now.astimezone(LONDON)


def today_local(now: datetime):
    return local(now).date()


def _at(local_date, hh: int, mm: int) -> datetime:
    return datetime.combine(local_date, datetime.min.time(), tzinfo=LONDON).replace(hour=hh, minute=mm).astimezone(
        timezone.utc
    )


def today_trigger_if_past(now: datetime, hh: int, mm: int) -> datetime | None:
    """Today's HH:MM (London) as aware UTC, or ``None`` if ``now`` hasn't
    reached it yet. No look-back — the rule stays silent on a day whose moment
    was slept through."""
    ln = local(now)
    trigger = _at(ln.date(), hh, mm)
    return trigger if now >= trigger else None


def most_recent_trigger(now: datetime, hh: int, mm: int) -> datetime:
    """The most recent past HH:MM (London): today's if reached, else
    yesterday's. Lets the engine expire a slept-through moment (COACH §4)."""
    ln = local(now)
    trigger = _at(ln.date(), hh, mm)
    if now >= trigger:
        return trigger
    return _at(ln.date() - timedelta(days=1), hh, mm)


# ============================================================================
# The proposal + rule types
# ============================================================================
@dataclass
class NudgeProposal:
    rule_key: str
    dedupe_key: str
    title: str
    body: str
    scheduled_for: datetime  # aware; the cycle's intended delivery instant
    priority: str = "default"  # low|default|high
    tags: list[str] = field(default_factory=list)
    expiry: timedelta | None = None  # overdue horizon; None = held through quiet hours
    push: bool = True  # False = inbox-only (ops rules); never consumes the cap
    cap_exempt: bool = False  # the briefing anchor: the cap never demotes it
    context: dict = field(default_factory=dict)


@dataclass
class RuleResult:
    """What a rule's ``evaluate`` returns. ``status`` feeds the tick's
    per-stage counts (COACH §3: "unconfigured -> silent 'not_configured' skip
    recorded in the tick counts, never a crash")."""

    proposals: list[NudgeProposal] = field(default_factory=list)
    status: str = "ok"  # ok | not_configured | stale | disabled | error
    note: str | None = None

    @classmethod
    def not_configured(cls, note: str | None = None) -> "RuleResult":
        return cls(status="not_configured", note=note)

    @classmethod
    def stale(cls, note: str | None = None) -> "RuleResult":
        return cls(status="stale", note=note)


EvaluateFn = Callable[[datetime, Session], "RuleResult | list[NudgeProposal]"]


@dataclass
class Rule:
    key: str
    evaluate: EvaluateFn
    cooldown_hours: float = 24.0

    def run(self, now: datetime, session: Session) -> RuleResult:
        """Wrap a rule so a raised exception degrades to an ``error`` skip
        (COACH §3: 'never a crash'), and a bare list return normalises to a
        RuleResult."""
        try:
            out = self.evaluate(now, session)
        except Exception as exc:  # noqa: BLE001 — one rule must never sink the tick
            return RuleResult(status="error", note=f"{type(exc).__name__}: {exc}")
        if isinstance(out, RuleResult):
            return out
        return RuleResult(proposals=list(out), status="ok")
