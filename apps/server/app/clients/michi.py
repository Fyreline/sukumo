"""Thin read-only client for Michi's study stats + streak — docs/API.md §4,
docs/phases/PHASE-3-siblings.md.

docs/ARCHITECTURE.md §5.1 (hard rule): read-only — this module must never
issue a write HTTP verb (POST/PUT/DELETE).

Snapshot contract (docs/DATA_MODEL.md §6): sibling_snapshots.payload_json
must hold ONLY the fields API.md §4 agreed on — never re-derive sibling
domain logic from anything else Michi's endpoint happens to return.
``filter_payload`` is the single place that enforces this and is
unit-tested directly (the contract test) so an accidental extra field never
silently leaks into a stored snapshot.
"""
from __future__ import annotations

import httpx

CONTRACT_FIELDS = ("streak_days", "studied_today", "due_reviews", "words_known", "last_session_at")


class MichiNotConfigured(RuntimeError):
    """SUKUMO_MICHI_SERVICE_TOKEN is unset."""


def filter_payload(raw: dict) -> dict:
    """Keeps ONLY the agreed API.md §4 contract fields."""
    return {k: raw[k] for k in CONTRACT_FIELDS if k in raw}


async def fetch_stats(base_url: str, service_token: str, timeout: float = 3.0) -> dict:
    """Read-only GET of Michi's GET /api/stats/service.

    Raises httpx.HTTPStatusError on a non-2xx response (e.g. Michi 401s a
    wrong/rotated token) and httpx.TimeoutException / httpx.ConnectError on
    network failure — callers (scripts/poll_sources.py) turn any of those
    into a sibling_snapshots error row, never a crash.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/api/stats/service",
            headers={"Authorization": f"Bearer {service_token}"},
        )
        response.raise_for_status()
        return filter_payload(response.json())


async def fetch(settings, timeout: float = 3.0) -> dict:
    """Settings-aware entrypoint used by scripts/poll_sources.py — turns an
    unset SUKUMO_MICHI_SERVICE_TOKEN into MichiNotConfigured rather than a
    doomed network round-trip."""
    if not settings.michi_service_token:
        raise MichiNotConfigured("SUKUMO_MICHI_SERVICE_TOKEN is unset")
    return await fetch_stats(settings.michi_base_url, settings.michi_service_token, timeout=timeout)
