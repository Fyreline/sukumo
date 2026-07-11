"""Thin read-only client for Mishka Hub's recent watches — docs/API.md §4,
docs/phases/PHASE-3-siblings.md.

Distinct from ``app/identity.py`` (which only verifies logins): this client
reads sibling data via a service token, never credentials. docs/ARCHITECTURE.md
§5.1 (hard rule): read-only — this module must never issue a write HTTP verb
(POST/PUT/DELETE).

Snapshot contract (docs/DATA_MODEL.md §6): sibling_snapshots.payload_json
must hold ONLY the fields API.md §4 agreed on — including inside the nested
``recent`` list, which is why ``filter_payload`` filters both the top-level
keys AND each recent item's keys. Unit-tested directly (the contract test)
so an accidental extra field (top-level or nested) never silently leaks into
a stored snapshot.
"""
from __future__ import annotations

import httpx

CONTRACT_FIELDS = ("recent", "watchlist_count")
_RECENT_ITEM_FIELDS = ("title", "watched_at", "poster_url", "rating", "user_email")


class MishkaNotConfigured(RuntimeError):
    """SUKUMO_MISHKA_SERVICE_TOKEN is unset."""


def filter_payload(raw: dict) -> dict:
    """Keeps ONLY the agreed API.md §4 contract fields, top-level and within
    each ``recent`` item."""
    result = {k: raw[k] for k in CONTRACT_FIELDS if k in raw}
    recent = result.get("recent")
    if isinstance(recent, list):
        result["recent"] = [
            {k: item[k] for k in _RECENT_ITEM_FIELDS if k in item}
            for item in recent
            if isinstance(item, dict)
        ]
    return result


async def fetch_activity(base_url: str, service_token: str, timeout: float = 3.0) -> dict:
    """Read-only GET of Mishka Hub's GET /api/activity/service.

    Raises httpx.HTTPStatusError on a non-2xx response and
    httpx.TimeoutException / httpx.ConnectError on network failure —
    callers (scripts/poll_sources.py) turn any of those into a
    sibling_snapshots error row, never a crash.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/api/activity/service",
            headers={"Authorization": f"Bearer {service_token}"},
        )
        response.raise_for_status()
        return filter_payload(response.json())


async def fetch(settings, timeout: float = 3.0) -> dict:
    """Settings-aware entrypoint used by scripts/poll_sources.py — turns an
    unset SUKUMO_MISHKA_SERVICE_TOKEN into MishkaNotConfigured rather than a
    doomed network round-trip. Base URL is shared with app/identity.py's
    login proxy (settings.mishka_base_url) — one app, one loopback address."""
    if not settings.mishka_service_token:
        raise MishkaNotConfigured("SUKUMO_MISHKA_SERVICE_TOKEN is unset")
    return await fetch_activity(settings.mishka_base_url, settings.mishka_service_token, timeout=timeout)
