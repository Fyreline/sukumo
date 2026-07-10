"""The coach tick loop: evaluate → dedupe → schedule → deliver —
docs/COACH.md, docs/ARCHITECTURE.md §2-3, docs/phases/PHASE-6-coach.md.

docs/ARCHITECTURE.md §5.3 (hard rule): the coach may only create nudges via
this engine (dedupe/caps/quiet-hours live here) — no route or script calls
``notify.send()`` directly except the bus endpoint itself. Empty scaffold —
built out in Phase 6.
"""
from __future__ import annotations
