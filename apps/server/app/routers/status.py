"""Sibling health checks — the Dyehouse status (Ops) tile —
docs/DESIGN.md §3.7, docs/DATA_MODEL.md §7, docs/phases/PHASE-3-siblings.md.

Empty scaffold — built out in Phase 3.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["status"])
