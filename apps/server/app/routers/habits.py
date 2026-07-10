"""Habit config + the 1-tap evidence log -- docs/DATA_MODEL.md #2,
docs/phases/PHASE-2-ingestion.md build item 7 -- plus the books endpoints
(Phase 4, HANDOFF Q1: the reading habit's companion lives with habits).

    GET    /api/habits              -- list, config as stored
    POST   /api/habits              -- create a habit
    PATCH  /api/habits/{id}         -- partial update
    POST   /api/habits/{id}/events  -- the one-tap log (source='tap',
                                        idempotent per Europe/London day --
                                        matches app.ingest.events' reading
                                        route, DATA_MODEL #2)
    GET    /api/books               -- current read + history (newest first)
    POST   /api/books               -- start a book (status 'reading')
    PATCH  /api/books/{id}          -- edit; finishing writes the
                                        memory_events milestone (DATA_MODEL #2)

JWT-auth (any authenticated household member); a habit's streak/gap maths
is computed off habit_events at read time elsewhere (DATA_MODEL #2), not
stored here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..errors import SukumoHTTPException
from ..models import Book, Habit, HabitEvent, MemoryEvent

router = APIRouter(tags=["habits"])

LONDON = ZoneInfo("Europe/London")


def _today_local() -> str:
    return datetime.now(timezone.utc).astimezone(LONDON).date().isoformat()


def _habit_dict(habit: Habit) -> dict:
    return {
        "id": habit.id,
        "user_id": habit.user_id,
        "key": habit.key,
        "title": habit.title,
        "kind": habit.kind,
        "target_json": json.loads(habit.target_json or "{}"),
        "evidence": habit.evidence,
        "active": bool(habit.active),
        "config_json": json.loads(habit.config_json or "{}"),
    }


class HabitCreate(BaseModel):
    key: str
    title: str
    kind: str
    target_json: dict = {}
    evidence: str | None = None
    active: bool = True
    config_json: dict = {}


class HabitPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    target_json: dict | None = None
    evidence: str | None = None
    active: bool | None = None
    config_json: dict | None = None


class HabitEventCreate(BaseModel):
    value: float = 1
    note: str | None = None
    local_date: str | None = None  # override, mainly for backfill/testing


@router.get("/habits")
async def list_habits(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    habits = session.scalars(select(Habit).order_by(Habit.id)).all()
    return [_habit_dict(h) for h in habits]


@router.post("/habits")
async def create_habit(
    body: HabitCreate, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    existing = session.scalar(select(Habit).where(Habit.key == body.key))
    if existing is not None:
        raise SukumoHTTPException(status_code=409, detail=f"habit key {body.key!r} already exists", code="conflict")

    habit = Habit(
        user_id=user_id,
        key=body.key,
        title=body.title,
        kind=body.kind,
        target_json=json.dumps(body.target_json),
        evidence=body.evidence,
        active=1 if body.active else 0,
        config_json=json.dumps(body.config_json),
    )
    session.add(habit)
    session.commit()
    session.refresh(habit)
    return _habit_dict(habit)


@router.patch("/habits/{habit_id}")
async def patch_habit(
    habit_id: int,
    body: HabitPatch,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    habit = session.get(Habit, habit_id)
    if habit is None:
        raise SukumoHTTPException(status_code=404, detail="Habit not found", code="not_found")

    if body.title is not None:
        habit.title = body.title
    if body.kind is not None:
        habit.kind = body.kind
    if body.target_json is not None:
        habit.target_json = json.dumps(body.target_json)
    if body.evidence is not None:
        habit.evidence = body.evidence
    if body.active is not None:
        habit.active = 1 if body.active else 0
    if body.config_json is not None:
        habit.config_json = json.dumps(body.config_json)

    session.commit()
    session.refresh(habit)
    return _habit_dict(habit)


@router.post("/habits/{habit_id}/events")
async def log_habit_event(
    habit_id: int,
    body: HabitEventCreate,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    habit = session.get(Habit, habit_id)
    if habit is None:
        raise SukumoHTTPException(status_code=404, detail="Habit not found", code="not_found")

    local_date = body.local_date or _today_local()
    existing = session.scalar(
        select(HabitEvent).where(
            HabitEvent.habit_id == habit_id, HabitEvent.local_date == local_date, HabitEvent.source == "tap"
        )
    )
    created = False
    if existing is None:
        existing = HabitEvent(habit_id=habit_id, local_date=local_date, value=body.value, source="tap", note=body.note)
        session.add(existing)
        created = True
    session.commit()
    session.refresh(existing)
    return {
        "id": existing.id,
        "habit_id": habit_id,
        "local_date": local_date,
        "value": existing.value,
        "source": existing.source,
        "note": existing.note,
        "created": created,
    }


# ------------------------------- books (DATA_MODEL §2, HANDOFF Q1) --------
BOOK_STATUSES = ("reading", "finished", "abandoned")


def _book_dict(book: Book) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "status": book.status,
        "started_on": book.started_on,
        "finished_on": book.finished_on,
        "notes": book.notes,
    }


class BookCreate(BaseModel):
    title: str
    author: str | None = None
    started_on: str | None = None  # default: today (Europe/London)
    notes: str | None = None


class BookPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    status: str | None = None
    started_on: str | None = None
    finished_on: str | None = None
    notes: str | None = None


@router.get("/books")
async def list_books(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    books = session.scalars(select(Book).order_by(Book.started_on.desc(), Book.id.desc())).all()
    return [_book_dict(b) for b in books]


@router.post("/books")
async def create_book(
    body: BookCreate, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    if not body.title.strip():
        raise SukumoHTTPException(status_code=422, detail="title is required", code="validation_error")
    book = Book(
        title=body.title.strip(),
        author=body.author,
        status="reading",
        started_on=body.started_on or _today_local(),
        notes=body.notes,
    )
    session.add(book)
    session.commit()
    session.refresh(book)
    return _book_dict(book)


@router.patch("/books/{book_id}")
async def patch_book(
    book_id: int,
    body: BookPatch,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    book = session.get(Book, book_id)
    if book is None:
        raise SukumoHTTPException(status_code=404, detail="Book not found", code="not_found")
    if body.status is not None and body.status not in BOOK_STATUSES:
        raise SukumoHTTPException(
            status_code=422, detail=f"status must be one of {BOOK_STATUSES}", code="validation_error"
        )

    finishing = body.status == "finished" and book.status != "finished"

    if body.title is not None:
        book.title = body.title.strip()
    if body.author is not None:
        book.author = body.author
    if body.started_on is not None:
        book.started_on = body.started_on
    if body.finished_on is not None:
        book.finished_on = body.finished_on
    if body.notes is not None:
        book.notes = body.notes
    if body.status is not None:
        book.status = body.status
        if finishing and not book.finished_on:
            book.finished_on = _today_local()

    # Finishing a book writes a memory_events milestone (DATA_MODEL §2) —
    # provider_uid keeps it idempotent if the same book is re-finished.
    if finishing:
        existing_milestone = session.scalar(
            select(MemoryEvent).where(
                MemoryEvent.source == "books", MemoryEvent.provider_uid == f"book:{book.id}:finished"
            )
        )
        if existing_milestone is None:
            session.add(
                MemoryEvent(
                    user_id=user_id,
                    ts=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    kind="milestone",
                    title=f"Finished “{book.title}”",
                    detail_json=json.dumps({"book_id": book.id, "author": book.author}),
                    source="books",
                    provider_uid=f"book:{book.id}:finished",
                )
            )

    session.commit()
    session.refresh(book)
    return _book_dict(book)
