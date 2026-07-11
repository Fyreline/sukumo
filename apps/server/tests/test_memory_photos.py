"""Photo mapper + journal filter + moment grouping — metadata-only, opt-in,
graceful degrade (HANDOFF Q4, docs/MEMORY.md §2). The real Photos library is
NEVER touched by the suite: osxphotos objects are stand-in fakes and every
uuid/place/moment title here is SYNTHETIC only."""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.db import SessionLocal
from app.memory import photos
from app.models import MemoryEvent

UUID_A = "AAAAAAAA-0000-0000-0000-000000000001"
UUID_B = "AAAAAAAA-0000-0000-0000-000000000002"
UUID_C = "AAAAAAAA-0000-0000-0000-000000000003"
UUID_D = "AAAAAAAA-0000-0000-0000-000000000004"


def fake_photo(
    uuid: str,
    when: datetime | None,
    *,
    place: str | None = None,
    moment: str | None = None,
    screenshot: bool = False,
    screen_recording: bool = False,
    hidden: bool = False,
    intrash: bool = False,
) -> SimpleNamespace:
    """A stand-in osxphotos.PhotoInfo carrying exactly the properties the
    module reads (all verified against osxphotos 0.76.x)."""
    return SimpleNamespace(
        uuid=uuid,
        date=when,
        place=SimpleNamespace(name=place) if place is not None else None,
        moment_info=SimpleNamespace(title=moment) if moment is not None else None,
        screenshot=screenshot,
        screen_recording=screen_recording,
        hidden=hidden,
        intrash=intrash,
    )


def _t(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-07-08T{hhmm}:00")


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


# ------------------------------------------------- the ONE journal predicate --
def test_predicate_excludes_exactly_the_four_flags():
    keep = fake_photo(UUID_A, _t("10:00"))
    assert photos.is_journal_photo(keep) is True
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), screenshot=True)) is False
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), screen_recording=True)) is False
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), hidden=True)) is False
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), intrash=True)) is False


def test_predicate_does_not_over_filter():
    """A perfectly ordinary photo — geocoded or not, momented or not, even a
    saved-from-WhatsApp shape with no place — stays (MEMORY §2: the filter is
    screenshots/recordings/hidden/trash ONLY)."""
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), place="Somewhere")) is True
    assert photos.is_journal_photo(fake_photo(UUID_A, _t("10:00"), moment="A Trip")) is True
    # objects missing the flags entirely (older schema, doubles) pass too
    assert photos.is_journal_photo(SimpleNamespace(uuid=UUID_A, date=_t("10:00"))) is True


# -------------------------------------------------------- mapper + filter -----
def _install_fake_library(monkeypatch, tmp_path, photo_list):
    """Point map_photos at a fake osxphotos over a real (empty) tmp dir."""
    fake_mod = types.ModuleType("osxphotos")
    fake_mod.PhotosDB = lambda dbfile: SimpleNamespace(photos=lambda: list(photo_list))
    monkeypatch.setitem(sys.modules, "osxphotos", fake_mod)
    return str(tmp_path)


def test_mapper_counts_only_journal_photos(monkeypatch, tmp_path):
    lib = _install_fake_library(
        monkeypatch,
        tmp_path,
        [
            fake_photo(UUID_A, _t("09:10"), place="Synthetic Green"),
            fake_photo(UUID_B, _t("11:30"), screenshot=True),
            fake_photo(UUID_C, _t("13:45"), screen_recording=True),
            fake_photo(UUID_D, _t("10:20")),
        ],
    )
    with SessionLocal() as db:
        out = photos.map_photos(db, library_path=lib)
        assert out["status"] == "ok"
        row = db.scalar(select(MemoryEvent).where(MemoryEvent.kind == "photo"))
        detail = json.loads(row.detail_json)
        assert detail["count"] == 2  # the screenshot + recording never counted
        assert detail["first"] == "09:10"
        assert detail["last"] == "10:20"  # not the screenshot's 11:30/13:45
        assert row.title.startswith("2 photos")


def test_mapper_skips_days_that_are_all_screenshots(monkeypatch, tmp_path):
    lib = _install_fake_library(
        monkeypatch,
        tmp_path,
        [
            fake_photo(UUID_A, _t("09:10"), screenshot=True),
            fake_photo(UUID_B, _t("11:30"), hidden=True),
        ],
    )
    with SessionLocal() as db:
        out = photos.map_photos(db, library_path=lib)
        assert out["status"] == "ok"
        assert db.query(MemoryEvent).count() == 0  # no row = no "2 photos" line


# ------------------------------------------------------- moment grouping ------
def _install_fake_db(monkeypatch, photo_list):
    monkeypatch.setattr(
        photos, "_photosdb", lambda lib: SimpleNamespace(photos=lambda: list(photo_list))
    )


def test_photos_for_date_groups_by_moment_title(monkeypatch):
    _install_fake_db(
        monkeypatch,
        [
            fake_photo(UUID_B, _t("14:40"), moment="Synthetic Outing"),
            fake_photo(UUID_A, _t("14:05"), moment="Synthetic Outing", place="Somewhere"),
            fake_photo(UUID_C, _t("09:00")),
        ],
    )
    groups = photos.photos_for_date("/fake/lib", "2026-07-08")
    assert [g["label"] for g in groups] == [None, "Synthetic Outing"]  # ordered by start
    outing = groups[1]
    assert outing["start"] == "14:05" and outing["end"] == "14:40"
    assert [p["uuid"] for p in outing["photos"]] == [UUID_A, UUID_B]  # time-sorted


def test_photos_for_date_time_gap_clusters_label_dominant_place(monkeypatch):
    _install_fake_db(
        monkeypatch,
        [
            fake_photo(UUID_A, _t("09:00"), place="Synthetic Green"),
            fake_photo(UUID_B, _t("09:45"), place="Synthetic Green"),
            fake_photo(UUID_C, _t("10:30"), place="Elsewhere"),
            # 12:30 is >90 min after 10:30 → a new cluster, ungeocoded → None
            fake_photo(UUID_D, _t("12:30")),
        ],
    )
    groups = photos.photos_for_date("/fake/lib", "2026-07-08")
    assert len(groups) == 2
    assert groups[0]["label"] == "Synthetic Green"  # dominant place (2 of 3)
    assert groups[0]["start"] == "09:00" and groups[0]["end"] == "10:30"
    assert groups[1]["label"] is None  # UI falls back to the time range
    assert groups[1]["start"] == groups[1]["end"] == "12:30"


def test_photos_for_date_gap_at_exactly_90_min_stays_one_group(monkeypatch):
    _install_fake_db(
        monkeypatch,
        [
            fake_photo(UUID_A, _t("09:00")),
            fake_photo(UUID_B, _t("10:30")),  # exactly 90 min — NOT a new group
        ],
    )
    groups = photos.photos_for_date("/fake/lib", "2026-07-08")
    assert len(groups) == 1
    assert len(groups[0]["photos"]) == 2


def test_photos_for_date_empty_moment_title_falls_back_to_time_gap(monkeypatch):
    _install_fake_db(
        monkeypatch,
        [
            fake_photo(UUID_A, _t("09:00"), moment=""),
            fake_photo(UUID_B, _t("09:30"), moment="   "),
        ],
    )
    groups = photos.photos_for_date("/fake/lib", "2026-07-08")
    assert len(groups) == 1  # blank titles never become a group label
    assert groups[0]["label"] is None


def test_photos_for_date_filters_and_scopes_to_the_day(monkeypatch):
    _install_fake_db(
        monkeypatch,
        [
            fake_photo(UUID_A, _t("09:00")),
            fake_photo(UUID_B, _t("09:05"), screenshot=True),
            fake_photo(UUID_C, _t("09:06"), intrash=True),
            fake_photo(UUID_D, datetime.fromisoformat("2026-07-09T09:00:00")),  # other day
        ],
    )
    groups = photos.photos_for_date("/fake/lib", "2026-07-08")
    assert sum(len(g["photos"]) for g in groups) == 1
    assert groups[0]["photos"][0]["uuid"] == UUID_A


def test_export_thumb_refuses_filtered_photo(monkeypatch, tmp_path):
    """Same gate as the listing: a guessed screenshot uuid serves nothing."""
    shot = fake_photo(UUID_A, _t("09:05"), screenshot=True)
    monkeypatch.setattr(
        photos, "_photosdb", lambda lib: SimpleNamespace(get_photo=lambda u: shot)
    )
    assert photos.export_thumb("/fake/lib", UUID_A, tmp_path) is None
