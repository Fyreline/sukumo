#!/usr/bin/env python3
"""Nightly snapshot of the production SQLite db (data/sukumo.db — the
household's only copy). Run by the com.sukumo.backup LaunchAgent
(docs/ARCHITECTURE.md §2), which invokes this via the venv's python — not
/bin/sh, matching Michi's com.michi.backup convention.

Uses sqlite3's own .backup() API, not a plain file copy — a copy of a
WAL-mode db mid-write can grab an inconsistent snapshot. Port of Michi's
apps/server/scripts/backup_db.py, verbatim apart from the db name.

Standalone, stdlib-only. Run from anywhere; paths are resolved relative to
this file, not the CWD.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# .../sukumo/apps/server/scripts/backup_db.py
#   parents[3] = sukumo (project root, where data/ lives)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB = PROJECT_ROOT / "data" / "sukumo.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
KEEP = 30


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


def main() -> int:
    if not DB.exists():
        log(f"skip: no db at {DB}")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"sukumo-{stamp}.db"

    src_conn = sqlite3.connect(str(DB))
    dest_conn = sqlite3.connect(str(dest))
    with dest_conn:
        src_conn.backup(dest_conn)
    dest_conn.close()
    src_conn.close()
    log(f"backed up to {dest}")

    snapshots = sorted(BACKUP_DIR.glob("sukumo-*.db"), key=lambda p: p.name, reverse=True)
    for old in snapshots[KEEP:]:
        old.unlink()
        log(f"pruned {old}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
