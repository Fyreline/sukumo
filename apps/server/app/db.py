"""Database engine/session setup.

Mirrors docs/DATA_MODEL.md and Michi's/Mishka Hub's app/db.py. This module
only builds the engine/session machinery; table creation is done once on
startup in app/main.py's lifespan (SQLite; no Alembic in Phase 1 — see
docs/ARCHITECTURE.md §4).
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()

# Ensure the parent directory of the SQLite file exists before connecting.
if settings.database_url.startswith("sqlite:///"):
    _db_path = settings.database_url.removeprefix("sqlite:///")
    Path(_db_path).resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """WAL + foreign keys + a busy timeout so two uvicorns / test runs don't
    trip over SQLite's file locking (matches the siblings' convention)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a Session, closing it after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
