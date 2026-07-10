#!/usr/bin/env python3
"""LaunchAgent entrypoint for the coach tick — docs/ARCHITECTURE.md §2-3,
docs/COACH.md, docs/phases/PHASE-6-coach.md.

Polls sources first, then runs the coach engine (one agent, not two —
ARCHITECTURE §2). Env-driven like scripts/poll_sources.py; runnable as
``python scripts/coach_tick.py`` or ``python -m app.coach``. Deployed by
Phase 8 via deploy/com.sukumo.coach.plist (StartInterval 900).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coach import engine as coach_engine  # noqa: E402
from app.coach import rules as coach_rules  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import Base  # noqa: E402


def main() -> None:
    Base.metadata.create_all(engine)  # no Alembic (ARCHITECTURE §4); mirrors app.main's lifespan
    coach_rules.load_rules()  # discover rules + register their action callbacks
    result = asyncio.run(coach_engine.run())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
