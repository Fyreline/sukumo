"""Photo mapper — metadata-only, opt-in, graceful degrade (HANDOFF Q4,
docs/MEMORY.md §2). The real Photos library is NEVER touched by the suite:
these tests only exercise the not_configured guards. SYNTHETIC only."""
from __future__ import annotations

from app.db import SessionLocal
from app.memory import photos
from app.models import MemoryEvent


def test_map_photos_not_configured_without_path():
    with SessionLocal() as db:
        out = photos.map_photos(db, library_path=None)
        assert out["status"] == "not_configured"
        assert db.query(MemoryEvent).count() == 0


def test_map_photos_not_configured_for_missing_path():
    with SessionLocal() as db:
        out = photos.map_photos(db, library_path="/no/such/Photos Library.photoslibrary")
        assert out["status"] == "not_configured"
        assert db.query(MemoryEvent).count() == 0
