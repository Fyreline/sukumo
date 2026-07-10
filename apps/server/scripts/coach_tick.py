#!/usr/bin/env python3
"""LaunchAgent entrypoint for the coach tick (also runnable as
``python -m app.coach``) — docs/ARCHITECTURE.md §2-3, docs/COACH.md,
docs/phases/PHASE-6-coach.md.

Runs ``poll_sources`` first, then the coach engine (one agent, not two —
docs/ARCHITECTURE.md §2). Empty scaffold — built out in Phase 6.
"""
from __future__ import annotations
