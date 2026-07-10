"""People / occasions / gift vault + calendar birthday import —
docs/DATA_MODEL.md §3, docs/API.md §1, docs/phases/PHASE-4-dashboard.md.

    GET/POST        /api/people             PATCH /api/people/{id}
    GET/POST        /api/occasions          PATCH /api/occasions/{id}
    GET/POST        /api/gifts              PATCH /api/gifts/{id}
    GET             /api/people/candidates  (calendar birthday suggestions)
    POST            /api/people/candidates/confirm

Every route is **primary-only** (403 for role='partner'): people/occasion
data never reaches the partner role at v1 in ANY response, dashboard or
otherwise (DESIGN §3 partner portal, PRIVATE §2 ⚠️ via the phase doc).

Real names/birthdays are data — they enter the DB through these endpoints
and never appear in the repo (ARCHITECTURE §5.5). Import assist (HANDOFF
Q8): candidates are only ever SUGGESTED from calendar_events titles;
confirming one by hand is the only path that creates anything.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..errors import SukumoHTTPException
from ..models import CalendarEvent, GiftIdea, Occasion, Person, User

router = APIRouter(tags=["people"])

LONDON = ZoneInfo("Europe/London")

OCCASION_KINDS = ("birthday", "anniversary", "event", "deadline")
GIFT_STATUSES = ("idea", "bought", "given")
MONTH_DAY_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Birthday-shaped calendar titles (docs/DATA_MODEL.md §3): "Ken's birthday",
# "Aiko bday", "Birthday: Ren", "Birthday - Mio", … The name half is captured
# for the suggestion; anything unparseable still surfaces with the raw title.
_SUFFIX_RE = re.compile(
    r"^(?P<name>.+?)(?:['’]s)?\s*[-–—:]*\s*(?:birthday|b['’]?day)\s*[!🎂🎉]*\s*$", re.IGNORECASE
)
_PREFIX_RE = re.compile(
    r"^(?:birthday|b['’]?day)\s*(?:of|for)?\s*[-–—:]*\s*(?P<name>.+?)\s*$", re.IGNORECASE
)


def primary_only(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> int:
    """The people/occasions/gifts door: role='primary' only (v1)."""
    user = session.get(User, user_id)
    if user is None or user.role != "primary":
        raise SukumoHTTPException(
            status_code=403,
            detail="People and occasions are primary-only at v1",
            code="forbidden",
        )
    return user_id


def _today_local() -> str:
    return datetime.now(timezone.utc).astimezone(LONDON).date().isoformat()


# ---------------------------------------------------------------- shaping --
def _person_dict(person: Person, occasions: list[Occasion], gifts: list[GiftIdea]) -> dict:
    return {
        "id": person.id,
        "name": person.name,
        "relation": person.relation,
        "birthday": person.birthday,
        "notes": person.notes,
        "archived": bool(person.archived),
        "occasions": [_occasion_dict(o) for o in occasions],
        "gift_ideas": [_gift_dict(g) for g in gifts],
    }


def _occasion_dict(occ: Occasion) -> dict:
    return {
        "id": occ.id,
        "person_id": occ.person_id,
        "title": occ.title,
        "month_day": occ.month_day,
        "date": occ.date,
        "recurrence": occ.recurrence,
        "lead_days": occ.lead_days,
        "kind": occ.kind,
        "private_to_user": occ.private_to_user,
    }


def _gift_dict(gift: GiftIdea) -> dict:
    return {
        "id": gift.id,
        "person_id": gift.person_id,
        "idea": gift.idea,
        "url": gift.url,
        "price_pence": gift.price_pence,
        "status": gift.status,
        "occasion_id": gift.occasion_id,
    }


def _visible_occasions(session: Session, user_id: int, person_id: int) -> list[Occasion]:
    """A person's occasions minus other users' private ones (surprise guard)."""
    rows = session.scalars(select(Occasion).where(Occasion.person_id == person_id).order_by(Occasion.id)).all()
    return [o for o in rows if o.private_to_user is None or o.private_to_user == user_id]


# ----------------------------------------------------------------- people --
class PersonCreate(BaseModel):
    name: str
    relation: str | None = None
    birthday: str | None = None  # 'YYYY-MM-DD'
    notes: str | None = None


class PersonPatch(BaseModel):
    name: str | None = None
    relation: str | None = None
    birthday: str | None = None
    notes: str | None = None
    archived: bool | None = None


def _validate_birthday(birthday: str) -> None:
    if not DATE_RE.match(birthday):
        raise SukumoHTTPException(status_code=422, detail="birthday must be YYYY-MM-DD", code="validation_error")
    try:
        date.fromisoformat(birthday)
    except ValueError as exc:
        raise SukumoHTTPException(status_code=422, detail=f"birthday: {exc}", code="validation_error") from exc


def _sync_birthday_occasion(session: Session, person: Person) -> None:
    """Birthdays auto-materialise one yearly occasion per person with a
    birthday (DATA_MODEL §3 — handled here in the router, not by trigger
    magic). Updates the existing kind='birthday' row in place; removes it if
    the birthday was cleared."""
    existing = session.scalar(
        select(Occasion).where(Occasion.person_id == person.id, Occasion.kind == "birthday")
    )
    if person.birthday:
        month_day = person.birthday[5:]
        title = f"{person.name}'s birthday"
        if existing is None:
            session.add(
                Occasion(
                    person_id=person.id,
                    title=title,
                    month_day=month_day,
                    recurrence="yearly",
                    kind="birthday",
                )
            )
        else:
            existing.month_day = month_day
            existing.title = title
    elif existing is not None:
        session.delete(existing)


@router.get("/people")
async def list_people(
    include_archived: bool = False,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> list[dict]:
    q = select(Person).order_by(Person.name)
    if not include_archived:
        q = q.where(Person.archived == 0)
    people = session.scalars(q).all()
    return [
        _person_dict(
            p,
            _visible_occasions(session, user_id, p.id),
            session.scalars(select(GiftIdea).where(GiftIdea.person_id == p.id).order_by(GiftIdea.id)).all(),
        )
        for p in people
    ]


@router.post("/people")
async def create_person(
    body: PersonCreate, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    name = body.name.strip()
    if not name:
        raise SukumoHTTPException(status_code=422, detail="name is required", code="validation_error")
    if body.birthday:
        _validate_birthday(body.birthday)
    existing = session.scalar(select(Person).where(Person.name == name, Person.archived == 0))
    if existing is not None:
        raise SukumoHTTPException(status_code=409, detail=f"{name!r} is already tracked", code="conflict")

    person = Person(name=name, relation=body.relation, birthday=body.birthday, notes=body.notes)
    session.add(person)
    session.flush()
    _sync_birthday_occasion(session, person)
    session.commit()
    session.refresh(person)
    return _person_dict(person, _visible_occasions(session, user_id, person.id), [])


@router.patch("/people/{person_id}")
async def patch_person(
    person_id: int,
    body: PersonPatch,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    person = session.get(Person, person_id)
    if person is None:
        raise SukumoHTTPException(status_code=404, detail="Person not found", code="not_found")

    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        person.name = body.name.strip()
    if "relation" in fields:
        person.relation = body.relation
    if "notes" in fields:
        person.notes = body.notes
    if "archived" in fields and body.archived is not None:
        person.archived = 1 if body.archived else 0
    if "birthday" in fields:
        if body.birthday:
            _validate_birthday(body.birthday)
        person.birthday = body.birthday
    # name or birthday changes both reflect into the auto birthday occasion
    if fields & {"name", "birthday"}:
        _sync_birthday_occasion(session, person)

    session.commit()
    session.refresh(person)
    return _person_dict(
        person,
        _visible_occasions(session, user_id, person.id),
        session.scalars(select(GiftIdea).where(GiftIdea.person_id == person.id).order_by(GiftIdea.id)).all(),
    )


# -------------------------------------------------------------- occasions --
class OccasionCreate(BaseModel):
    title: str
    person_id: int | None = None
    month_day: str | None = None
    date: str | None = None
    recurrence: str | None = None  # inferred from month_day/date when omitted
    lead_days: int = 21
    kind: str = "event"
    private_to_user: int | None = None


class OccasionPatch(BaseModel):
    title: str | None = None
    month_day: str | None = None
    date: str | None = None
    recurrence: str | None = None
    lead_days: int | None = None
    kind: str | None = None
    private_to_user: int | None = None


def _validate_occasion_fields(month_day: str | None, occ_date: str | None, kind: str) -> str:
    """Exactly one of month_day/date (DATA_MODEL §3); returns the implied
    recurrence."""
    if bool(month_day) == bool(occ_date):
        raise SukumoHTTPException(
            status_code=422,
            detail="exactly one of month_day (yearly) or date (once) is required",
            code="validation_error",
        )
    if month_day and not MONTH_DAY_RE.match(month_day):
        raise SukumoHTTPException(status_code=422, detail="month_day must be MM-DD", code="validation_error")
    if occ_date:
        if not DATE_RE.match(occ_date):
            raise SukumoHTTPException(status_code=422, detail="date must be YYYY-MM-DD", code="validation_error")
        try:
            date.fromisoformat(occ_date)
        except ValueError as exc:
            raise SukumoHTTPException(status_code=422, detail=f"date: {exc}", code="validation_error") from exc
    if kind not in OCCASION_KINDS:
        raise SukumoHTTPException(
            status_code=422, detail=f"kind must be one of {OCCASION_KINDS}", code="validation_error"
        )
    return "yearly" if month_day else "once"


@router.get("/occasions")
async def list_occasions(
    user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> list[dict]:
    rows = session.scalars(select(Occasion).order_by(Occasion.id)).all()
    return [_occasion_dict(o) for o in rows if o.private_to_user is None or o.private_to_user == user_id]


@router.post("/occasions")
async def create_occasion(
    body: OccasionCreate, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    if not body.title.strip():
        raise SukumoHTTPException(status_code=422, detail="title is required", code="validation_error")
    recurrence = _validate_occasion_fields(body.month_day, body.date, body.kind)
    if body.recurrence is not None and body.recurrence != recurrence:
        raise SukumoHTTPException(
            status_code=422,
            detail="recurrence must be 'yearly' with month_day or 'once' with date",
            code="validation_error",
        )
    if body.person_id is not None and session.get(Person, body.person_id) is None:
        raise SukumoHTTPException(status_code=404, detail="Person not found", code="not_found")

    occ = Occasion(
        person_id=body.person_id,
        title=body.title.strip(),
        month_day=body.month_day,
        date=body.date,
        recurrence=recurrence,
        lead_days=body.lead_days,
        kind=body.kind,
        private_to_user=body.private_to_user,
    )
    session.add(occ)
    session.commit()
    session.refresh(occ)
    return _occasion_dict(occ)


@router.patch("/occasions/{occasion_id}")
async def patch_occasion(
    occasion_id: int,
    body: OccasionPatch,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    occ = session.get(Occasion, occasion_id)
    if occ is None:
        raise SukumoHTTPException(status_code=404, detail="Occasion not found", code="not_found")

    fields = body.model_fields_set
    month_day = body.month_day if "month_day" in fields else occ.month_day
    occ_date = body.date if "date" in fields else occ.date
    kind = body.kind if body.kind is not None else occ.kind
    recurrence = _validate_occasion_fields(month_day, occ_date, kind)

    occ.month_day = month_day
    occ.date = occ_date
    occ.kind = kind
    occ.recurrence = recurrence
    if body.title is not None:
        occ.title = body.title.strip()
    if body.lead_days is not None:
        occ.lead_days = body.lead_days
    if "private_to_user" in fields:
        occ.private_to_user = body.private_to_user

    session.commit()
    session.refresh(occ)
    return _occasion_dict(occ)


# ------------------------------------------------------------------ gifts --
class GiftCreate(BaseModel):
    person_id: int
    idea: str
    url: str | None = None
    price_pence: int | None = None
    status: str = "idea"
    occasion_id: int | None = None


class GiftPatch(BaseModel):
    idea: str | None = None
    url: str | None = None
    price_pence: int | None = None
    status: str | None = None
    occasion_id: int | None = None


@router.get("/gifts")
async def list_gifts(
    person_id: int | None = None,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> list[dict]:
    q = select(GiftIdea).order_by(GiftIdea.id)
    if person_id is not None:
        q = q.where(GiftIdea.person_id == person_id)
    return [_gift_dict(g) for g in session.scalars(q).all()]


@router.post("/gifts")
async def create_gift(
    body: GiftCreate, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    if not body.idea.strip():
        raise SukumoHTTPException(status_code=422, detail="idea is required", code="validation_error")
    if body.status not in GIFT_STATUSES:
        raise SukumoHTTPException(
            status_code=422, detail=f"status must be one of {GIFT_STATUSES}", code="validation_error"
        )
    if session.get(Person, body.person_id) is None:
        raise SukumoHTTPException(status_code=404, detail="Person not found", code="not_found")

    gift = GiftIdea(
        person_id=body.person_id,
        idea=body.idea.strip(),
        url=body.url,
        price_pence=body.price_pence,
        status=body.status,
        occasion_id=body.occasion_id,
    )
    session.add(gift)
    session.commit()
    session.refresh(gift)
    return _gift_dict(gift)


@router.patch("/gifts/{gift_id}")
async def patch_gift(
    gift_id: int,
    body: GiftPatch,
    user_id: int = Depends(primary_only),
    session: Session = Depends(get_session),
) -> dict:
    gift = session.get(GiftIdea, gift_id)
    if gift is None:
        raise SukumoHTTPException(status_code=404, detail="Gift idea not found", code="not_found")

    if body.status is not None:
        if body.status not in GIFT_STATUSES:
            raise SukumoHTTPException(
                status_code=422, detail=f"status must be one of {GIFT_STATUSES}", code="validation_error"
            )
        gift.status = body.status
    if body.idea is not None:
        gift.idea = body.idea.strip()
    fields = body.model_fields_set
    if "url" in fields:
        gift.url = body.url
    if "price_pence" in fields:
        gift.price_pence = body.price_pence
    if "occasion_id" in fields:
        gift.occasion_id = body.occasion_id

    session.commit()
    session.refresh(gift)
    return _gift_dict(gift)


# ------------------------------------------- calendar birthday candidates --
def _extract_candidate_name(title: str, calendar_name: str | None) -> str | None:
    """Pull the person's name out of a birthday-shaped calendar title.
    Returns None when the title is birthday-flavoured but carries no name."""
    t = title.strip()
    for pattern in (_SUFFIX_RE, _PREFIX_RE):
        m = pattern.match(t)
        if m:
            name = m.group("name").strip(" -–—:!,")
            return name or None
    # Apple's dedicated birthday calendar puts just the name in the title.
    if calendar_name and "birthday" in calendar_name.lower():
        return t or None
    return None


def _is_birthday_shaped(event: CalendarEvent) -> bool:
    title = (event.title or "").lower()
    calendar_name = (event.calendar_name or "").lower()
    return "birthday" in title or "bday" in title or "birthday" in calendar_name


@router.get("/people/candidates")
async def birthday_candidates(
    user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> list[dict]:
    """Scan calendar_events for birthday-shaped entries and suggest people
    to track (HANDOFF Q8). Suggestions only — POST /confirm is the only
    thing that creates rows. Names already tracked (case-insensitive) are
    filtered out."""
    events = session.scalars(
        select(CalendarEvent).where(
            or_(
                CalendarEvent.title.ilike("%birthday%"),
                CalendarEvent.title.ilike("%bday%"),
                CalendarEvent.calendar_name.ilike("%birthday%"),
            )
        )
    ).all()

    known_names = {
        p.name.strip().lower()
        for p in session.scalars(select(Person)).all()
    }

    seen: set[tuple[str, str]] = set()
    candidates = []
    for event in events:
        if not event.title or not _is_birthday_shaped(event):
            continue
        name = _extract_candidate_name(event.title, event.calendar_name)
        if not name:
            continue
        month_day = event.starts_at[5:10]  # 'YYYY-MM-DD …' -> 'MM-DD'
        key = (name.lower(), month_day)
        if key in seen or name.lower() in known_names:
            continue
        seen.add(key)
        candidates.append(
            {
                "name": name,
                "month_day": month_day,
                "next_date": event.starts_at[:10],
                "source_title": event.title,
                "calendar_name": event.calendar_name,
            }
        )
    candidates.sort(key=lambda c: (c["month_day"], c["name"]))
    return candidates


class CandidateConfirm(BaseModel):
    name: str
    month_day: str
    relation: str | None = None


@router.post("/people/candidates/confirm")
async def confirm_candidate(
    body: CandidateConfirm, user_id: int = Depends(primary_only), session: Session = Depends(get_session)
) -> dict:
    """The hand-confirmation step: creates the person + their yearly
    birthday occasion. The calendar only knows the month/day, not the birth
    year, so person.birthday stays null until edited by hand."""
    name = body.name.strip()
    if not name:
        raise SukumoHTTPException(status_code=422, detail="name is required", code="validation_error")
    if not MONTH_DAY_RE.match(body.month_day):
        raise SukumoHTTPException(status_code=422, detail="month_day must be MM-DD", code="validation_error")
    existing = session.scalar(select(Person).where(Person.name == name, Person.archived == 0))
    if existing is not None:
        raise SukumoHTTPException(status_code=409, detail=f"{name!r} is already tracked", code="conflict")

    person = Person(name=name, relation=body.relation)
    session.add(person)
    session.flush()
    occasion = Occasion(
        person_id=person.id,
        title=f"{name}'s birthday",
        month_day=body.month_day,
        recurrence="yearly",
        kind="birthday",
    )
    session.add(occasion)
    session.commit()
    session.refresh(person)
    session.refresh(occasion)
    return {
        "person": _person_dict(person, [occasion], []),
        "occasion": _occasion_dict(occasion),
    }
