#!/usr/bin/env python3
"""Prints a new ingest token (raw shown once), stores its sha256 hash --
docs/AUTH.md #3, docs/DATA_MODEL.md #1, docs/phases/PHASE-2-ingestion.md.

Usage::

    python scripts/mint_ingest_token.py --name health-mack-iphone --scope ingest --user-id 1
    python scripts/mint_ingest_token.py --name michi-bus --scope notify
    python scripts/mint_ingest_token.py --name shortcut-office --scope ingest --user-id 1

The raw token is shown exactly once here; only its sha256 hash is stored
(app.auth.ingest_token_auth verifies by re-hashing the presented bearer
token and comparing). Losing it means minting a new one and updating the one
client (AUTH.md #3: "rotation = mint new, update the one client, revoke old").
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine, SessionLocal  # noqa: E402
from app.models import Base, IngestToken  # noqa: E402

VALID_SCOPES = {"ingest", "notify", "ingest+notify"}


def mint(name: str, scope: str, user_id: int | None) -> str:
    if scope not in VALID_SCOPES:
        raise SystemExit(f"scope must be one of {sorted(VALID_SCOPES)}, got {scope!r}")

    # No Alembic in Phase 1/2 (docs/ARCHITECTURE.md #4) -- ensure tables
    # exist even if this script runs before the API has started once.
    Base.metadata.create_all(engine)

    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with SessionLocal() as session:
        session.add(IngestToken(name=name, token_hash=token_hash, scope=scope, user_id=user_id))
        session.commit()
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="e.g. 'health-mack-iphone'")
    parser.add_argument("--scope", required=True, choices=sorted(VALID_SCOPES))
    parser.add_argument("--user-id", type=int, default=None, help="owning users.id, if any (DATA_MODEL #1)")
    args = parser.parse_args()

    raw = mint(args.name, args.scope, args.user_id)
    print(f"Ingest token minted for {args.name!r} (scope={args.scope}).")
    print("Store it now -- it will not be shown again:\n")
    print(raw)


if __name__ == "__main__":
    main()
