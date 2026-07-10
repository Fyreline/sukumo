"""POST /api/ingest/* — token-auth (not JWT) ingest endpoints for phone
health payloads and generic events — docs/API.md §2, docs/AUTH.md §3,
docs/phases/PHASE-2-ingestion.md.

Empty scaffold — built out in Phase 2.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["ingest"])
