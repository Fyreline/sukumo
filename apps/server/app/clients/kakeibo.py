"""Thin read-only client for Kakeibo's house-goal snapshot — docs/API.md §4,
docs/phases/PHASE-3-siblings.md.

docs/ARCHITECTURE.md §5.1 (hard rule): read-only — this module must never
issue a write HTTP verb (POST/PUT/DELETE).

Scope note: Kakeibo's own GET /api/goal/service endpoint does not exist yet
(its repo has unrelated in-flight work and is deliberately left untouched
this phase) — this client is still built and wired into poll_sources.py so
the wiring costs nothing to add later. With SUKUMO_KAKEIBO_SERVICE_TOKEN
unset (the default), ``fetch`` always raises KakeiboNotConfigured, so every
poll cycle writes a clean 'not_configured' sync_run — never an error — until
the token is set for real.

Snapshot contract (docs/DATA_MODEL.md §6): sibling_snapshots.payload_json
must hold ONLY the fields API.md §4 agreed on. ``filter_payload`` is the
single enforcement point and is unit-tested directly (the contract test).
"""
from __future__ import annotations

import httpx

CONTRACT_FIELDS = ("goal_pence", "saved_pence", "pct", "pace_status", "as_of")


class KakeiboNotConfigured(RuntimeError):
    """SUKUMO_KAKEIBO_SERVICE_TOKEN is unset."""


def filter_payload(raw: dict) -> dict:
    """Keeps ONLY the agreed API.md §4 contract fields."""
    return {k: raw[k] for k in CONTRACT_FIELDS if k in raw}


async def fetch_goal(base_url: str, service_token: str, timeout: float = 3.0) -> dict:
    """Read-only GET of Kakeibo's GET /api/goal/service.

    Raises httpx.HTTPStatusError on a non-2xx response and
    httpx.TimeoutException / httpx.ConnectError on network failure —
    callers (scripts/poll_sources.py) turn any of those into a
    sibling_snapshots error row, never a crash.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/api/goal/service",
            headers={"Authorization": f"Bearer {service_token}"},
        )
        response.raise_for_status()
        return filter_payload(response.json())


async def fetch(settings, timeout: float = 3.0) -> dict:
    """Settings-aware entrypoint used by scripts/poll_sources.py — turns an
    unset SUKUMO_KAKEIBO_SERVICE_TOKEN into KakeiboNotConfigured rather than
    a doomed network round-trip."""
    if not settings.kakeibo_service_token:
        raise KakeiboNotConfigured("SUKUMO_KAKEIBO_SERVICE_TOKEN is unset")
    return await fetch_goal(settings.kakeibo_base_url, settings.kakeibo_service_token, timeout=timeout)
