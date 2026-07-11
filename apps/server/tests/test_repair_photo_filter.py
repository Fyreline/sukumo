"""scripts/repair_photo_filter.py -- data-repair for the journal-photo
filter (memory_events kind='photo' previously counted screenshots, screen
recordings, hidden and trashed assets). Idempotent: once the well is in the
corrected steady state, repeated runs report the same counts. All data here
is SYNTHETIC and the real Photos library is never touched (the fake-osxphotos
pattern from test_memory_photos.py)."""
from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

from sqlalchemy import select

from app.db import SessionLocal
from app.models import JournalDay, MemoryEvent

from .conftest import make_user
from .test_memory_photos import UUID_A, UUID_B, _t, fake_photo
from scripts import repair_photo_filter as repair


def _seed_pre_filter_photo_events() -> None:
    """Simulate the BUGGY state: per-day photo rows whose counts include
    screenshots (as the old, unfiltered mapper produced)."""
    make_user(email="mack@example.com", display_name="Mack", role="primary")
    with SessionLocal() as db:
        db.add(
            MemoryEvent(
                ts="2026-07-08 11:00:00",
                kind="photo",
                title="34 photos",
                detail_json=json.dumps(
                    {"count": 34, "first": "09:10", "last": "22:41", "places": []}
                ),
                source="photos",
                provider_uid="photo:2026-07-08",
            )
        )
        db.add(
            MemoryEvent(
                ts="2026-07-07 11:00:00",
                kind="photo",
                title="3 photos",
                detail_json=json.dumps(
                    {"count": 3, "first": "12:00", "last": "12:30", "places": []}
                ),
                source="photos",
                provider_uid="photo:2026-07-07",
            )
        )
        db.commit()


def _install_fake_library(monkeypatch, tmp_path, photo_list) -> str:
    fake_mod = types.ModuleType("osxphotos")
    fake_mod.PhotosDB = lambda dbfile: SimpleNamespace(photos=lambda: list(photo_list))
    monkeypatch.setitem(sys.modules, "osxphotos", fake_mod)
    return str(tmp_path)


def test_repair_deletes_remaps_and_reassembles(monkeypatch, tmp_path):
    """The 2026-07-08 library day is 1 real photo + 1 screenshot: the repair
    must bring the day back as count=1 and drop 07-07 (all-screenshot day)
    entirely, re-assembling both journal days."""
    _seed_pre_filter_photo_events()
    lib = _install_fake_library(
        monkeypatch,
        tmp_path,
        [
            fake_photo(UUID_A, _t("09:10")),
            fake_photo(UUID_B, _t("11:30"), screenshot=True),
        ],
    )
    with SessionLocal() as db:
        from app.memory.assemble import assemble_day

        assemble_day(db, "2026-07-07", run_maps=False)
        assemble_day(db, "2026-07-08", run_maps=False)
        db.commit()
        assert db.get(JournalDay, "2026-07-08").stats_json.count('"photos": 34')

        result = repair.repair_photo_filter(db, library_path=lib, thumbs_dir=tmp_path / "thumbs")
        db.commit()

        assert result["mapper_status"] == "ok"
        assert result["photo_day_rows_deleted"] == 2
        assert result["photo_day_rows_recreated"] == 1
        assert result["photos_counted_before"] == 37
        assert result["photos_counted_after"] == 1
        assert result["journal_days_reassembled"] == 2

        rows = db.scalars(select(MemoryEvent).where(MemoryEvent.kind == "photo")).all()
        assert len(rows) == 1
        assert rows[0].provider_uid == "photo:2026-07-08"

        stats_08 = json.loads(db.get(JournalDay, "2026-07-08").stats_json)
        assert stats_08["photos"] == 1  # the summary/stats recomputed
        stats_07 = json.loads(db.get(JournalDay, "2026-07-07").stats_json)
        assert stats_07["photos"] == 0  # all-screenshot day reads photo-free


def test_repair_is_idempotent(monkeypatch, tmp_path):
    _seed_pre_filter_photo_events()
    lib = _install_fake_library(monkeypatch, tmp_path, [fake_photo(UUID_A, _t("09:10"))])
    with SessionLocal() as db:
        first = repair.repair_photo_filter(db, library_path=lib, thumbs_dir=tmp_path / "thumbs")
        db.commit()
        second = repair.repair_photo_filter(db, library_path=lib, thumbs_dir=tmp_path / "thumbs")
        db.commit()
        third = repair.repair_photo_filter(db, library_path=lib, thumbs_dir=tmp_path / "thumbs")
        db.commit()

        assert first["photo_day_rows_recreated"] == 1
        assert second == third
        assert second["photo_day_rows_deleted"] == 1
        assert second["photo_day_rows_recreated"] == 1
        assert second["photos_counted_before"] == second["photos_counted_after"] == 1


def test_repair_purges_the_thumb_cache(monkeypatch, tmp_path):
    make_user(email="mack@example.com", display_name="Mack", role="primary")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    (thumbs / f"{UUID_A}.jpg").write_bytes(b"\xff\xd8 synthetic")
    (thumbs / f"{UUID_B}.jpg").write_bytes(b"\xff\xd8 synthetic")
    with SessionLocal() as db:
        result = repair.repair_photo_filter(db, library_path=None, thumbs_dir=thumbs)
        assert result["thumbs_purged"] == 2
        assert list(thumbs.glob("*.jpg")) == []
        again = repair.repair_photo_filter(db, library_path=None, thumbs_dir=thumbs)
        assert again["thumbs_purged"] == 0  # rebuilds lazily; nothing left to purge


def test_repair_without_library_still_cleans_stale_rows(tmp_path):
    """No library configured (or moved away): the stale unfiltered rows must
    still be deleted and their days re-assembled honestly photo-free."""
    _seed_pre_filter_photo_events()
    with SessionLocal() as db:
        result = repair.repair_photo_filter(db, library_path=None, thumbs_dir=tmp_path / "thumbs")
        db.commit()
        assert result["mapper_status"] == "not_configured"
        assert result["photo_day_rows_deleted"] == 2
        assert result["photo_day_rows_recreated"] == 0
        assert result["journal_days_reassembled"] == 2
        assert db.query(MemoryEvent).count() == 0


def test_repair_never_touches_other_kinds(monkeypatch, tmp_path):
    _seed_pre_filter_photo_events()
    with SessionLocal() as db:
        db.add(
            MemoryEvent(
                ts="2026-07-08 20:30:00",
                kind="film",
                title="A Synthetic Film",
                detail_json=json.dumps({"rating": 4}),
                source="mishka",
                provider_uid="mishka:2026-07-08 20:30:00:ffffffff",
            )
        )
        db.commit()
        repair.repair_photo_filter(db, library_path=None, thumbs_dir=tmp_path / "thumbs")
        db.commit()
        kinds = [r.kind for r in db.scalars(select(MemoryEvent)).all()]
        assert kinds == ["film"]
