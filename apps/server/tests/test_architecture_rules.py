"""Grep-able acceptance items from docs/ARCHITECTURE.md #5 /
docs/phases/PHASE-2-ingestion.md, encoded as tests so CI catches a
regression, not just a one-off manual grep."""
from __future__ import annotations

import subprocess
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]


def test_clients_are_read_only():
    """ARCHITECTURE.md #5.1: 'clients/*.py contain no .post/.put/.delete
    ... Sukumo never writes to a sibling.' grep -rn "\\.post\\|\\.put\\|\\.delete"
    app/clients/ must come back empty."""
    result = subprocess.run(
        ["grep", "-rn", r"\.post\|\.put\|\.delete", str(SERVER_DIR / "app" / "clients")],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", f"write verb found in app/clients/: {result.stdout}"


def test_location_never_reaches_push_surfaces():
    """MEMORY.md #2 hard line: nothing location-derived enters push
    composition. The coach package and the notify pipe must reference
    neither the raw table (location_points / LocationPoint) nor the journal's
    stats_json (where the trace lives) -- pinned as a grep so a future rule
    can't quietly pick the trace up."""
    for target in ("app/coach", "app/notify.py"):
        result = subprocess.run(
            [
                "grep",
                "-rn",
                r"location_points\|LocationPoint\|stats_json",
                str(SERVER_DIR / target),
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", f"location/stats reference in {target}: {result.stdout}"


def test_no_private_coordinates_or_urls_committed_in_fixtures():
    """ARCHITECTURE.md #5.5: PRIVATE data enters via .env/DB only. The
    committed calendar fixture must not reference the real SUKUMO_ICS_URLS
    host/scheme (icloud.com) -- it must stay a synthetic 'example.invalid' feed."""
    fixture = SERVER_DIR / "tests" / "fixtures" / "sample_calendar.ics"
    text = fixture.read_text()
    assert "icloud.com" not in text.lower()
    assert "caldav" not in text.lower()
