"""POST /api/notify — the notification bus entry point (token-auth) —
docs/API.md §5, docs/ARCHITECTURE.md §5.3, docs/phases/PHASE-5-notify.md.

Empty scaffold — built out in Phase 5.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["notify"])
