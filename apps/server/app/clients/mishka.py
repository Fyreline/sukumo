"""Thin read-only client for Mishka Hub's recent watches — docs/API.md §4,
docs/phases/PHASE-3-siblings.md.

Distinct from ``app/identity.py`` (which only verifies logins): this client
reads sibling data via a service token, never credentials. docs/ARCHITECTURE.md
§5.1 (hard rule): read-only — this module must never call
``.post``/``.put``/``.delete``. Empty scaffold — built out in Phase 3.
"""
from __future__ import annotations
