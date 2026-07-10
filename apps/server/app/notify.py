"""The notification bus core — docs/API.md §5, docs/phases/PHASE-5-notify.md.

Owns the channel drivers (ntfy v1, webpush later) and the redaction gate:
notification text carries categories, not values (docs/ARCHITECTURE.md §5.2).
Coach rules and ``routers/notify.py`` are the only callers of ``send()``
(docs/ARCHITECTURE.md §5.3). Empty scaffold — built out in Phase 5.
"""
from __future__ import annotations
