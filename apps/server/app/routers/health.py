"""GET /api/health — unauthenticated liveness only (docs/ARCHITECTURE.md §1).

Deliberately minimal: this endpoint answers "is the process up", nothing
more. Per-sibling reachability (Mishka Hub, Michi, Kakeibo, calendar,
weather) is a separate concern owned by ``routers/status.py`` and the
Dyehouse status tile (docs/DESIGN.md §3.7, docs/phases/PHASE-3-siblings.md).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
