"""Thin read-only client for Michi's study stats + streak — docs/API.md §4,
docs/phases/PHASE-3-siblings.md.

docs/ARCHITECTURE.md §5.1 (hard rule): read-only — this module must never
call ``.post``/``.put``/``.delete``. Empty scaffold — built out in Phase 3.
"""
from __future__ import annotations
