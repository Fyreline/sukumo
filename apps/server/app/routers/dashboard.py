"""GET /api/dashboard — one aggregate tile payload for BridgePage —
docs/API.md §1, docs/DESIGN.md §3, docs/phases/PHASE-4-dashboard.md.

Empty scaffold — built out in Phase 4.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])
