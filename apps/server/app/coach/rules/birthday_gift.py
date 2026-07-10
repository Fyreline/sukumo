"""birthday-gift — the vault-aware gift prompt (COACH §3.5).

A birthday occasion inside its lead window with no ``bought``/``given`` gift
linked → a weekly prompt (Sunday) plus one midweek push (Wednesday), escalating
copy at ≤7 days. If unbought ideas exist, the push lists their *titles* — names
of people are fine in pushes; prices and URLs stay in-app (COACH §3.5,
ARCHITECTURE §5.2).

dedupe ``gift:<occasion_id>:<year>:<week>:<slot>`` — two slots a week at most.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import or_, select

from ...models import GiftIdea, Occasion, Person
from ..proposals import NudgeProposal, Rule, RuleResult, today_local, today_trigger_if_past

PROMPT_HH, PROMPT_MM = 10, 0
SUNDAY, WEDNESDAY = 7, 3  # isoweekday


def _next_birthday(occ: Occasion, today: date) -> date | None:
    if occ.month_day:
        try:
            month, day = (int(p) for p in occ.month_day.split("-"))
        except (ValueError, TypeError):
            return None
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                candidate = date(year, 3, 1)
            if candidate >= today:
                return candidate
        return None
    if occ.date:
        try:
            return date.fromisoformat(occ.date)
        except ValueError:
            return None
    return None


def _has_bought_gift(session, occ: Occasion) -> bool:
    clauses = [GiftIdea.occasion_id == occ.id]
    if occ.person_id is not None:
        clauses.append(GiftIdea.person_id == occ.person_id)
    gifts = session.scalars(select(GiftIdea).where(or_(*clauses))).all()
    return any(g.status in ("bought", "given") for g in gifts)


def _unbought_titles(session, occ: Occasion) -> list[str]:
    clauses = [GiftIdea.occasion_id == occ.id]
    if occ.person_id is not None:
        clauses.append(GiftIdea.person_id == occ.person_id)
    gifts = session.scalars(select(GiftIdea).where(or_(*clauses))).all()
    return [g.idea for g in gifts if g.status == "idea"]


def evaluate(now: datetime, session) -> RuleResult:
    trigger = today_trigger_if_past(now, PROMPT_HH, PROMPT_MM)
    if trigger is None:
        return RuleResult()
    iso = now.isocalendar()  # (year, week, weekday)
    if iso.weekday == SUNDAY:
        slot = "sun"
    elif iso.weekday == WEDNESDAY:
        slot = "mid"
    else:
        return RuleResult()

    today = today_local(now)
    proposals: list[NudgeProposal] = []
    for occ in session.scalars(select(Occasion).where(Occasion.kind == "birthday")).all():
        target = _next_birthday(occ, today)
        if target is None:
            continue
        days = (target - today).days
        if days < 0 or days > occ.lead_days:
            continue
        if _has_bought_gift(session, occ):
            continue

        name = "Someone"
        if occ.person_id is not None:
            person = session.get(Person, occ.person_id)
            if person is not None:
                name = person.name
        titles = _unbought_titles(session, occ)
        soon = days <= 7
        when = "just a week away" if soon else f"in {days} days"
        if titles:
            body = f"{name}'s birthday is {when}. Ideas saved: {', '.join(titles[:3])} — time to pick one?"
        else:
            body = f"{name}'s birthday is {when} and nothing's saved yet — a good week to think of something."
        proposals.append(
            NudgeProposal(
                rule_key="birthday-gift",
                dedupe_key=f"gift:{occ.id}:{iso.year}:{iso.week}:{slot}",
                title=f"{name}'s birthday",
                body=body,
                scheduled_for=trigger,
                tags=["coach", "gift"],
                expiry=timedelta(hours=6),
            )
        )
    return RuleResult(proposals=proposals)


RULE = Rule(key="birthday-gift", evaluate=evaluate, cooldown_hours=0)
