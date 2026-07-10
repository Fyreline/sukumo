#!/usr/bin/env python3
"""First bus customer (docs/phases/PHASE-5-notify.md build item 7): POSTs a
sample ops nudge through POST /api/notify end-to-end -- proves "every app
gains a voice" through one pipe, before any real sibling adopts it. The real
Michi LaunchAgent wrapper is Phase 8 deployment work (ARCHITECTURE.md §1) --
deliberately NOT touched here; Michi's own repo stays untouched this phase.

Usage::

    python scripts/notify_test.py --token <notify-scoped ingest token, raw>
    python scripts/notify_test.py --token <...> --base http://127.0.0.1:8301
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", required=True, help="a notify-scoped ingest token (raw, from mint_ingest_token.py)")
    parser.add_argument("--base", default="http://127.0.0.1:8301", help="Sukumo API base URL")
    parser.add_argument("--source", default="sukumo-ops-test", help="the bus 'source' tag -> rule_key 'bus:<source>'")
    parser.add_argument("--priority", default="default", choices=["low", "default", "high"])
    args = parser.parse_args()

    payload = {
        "title": "Sukumo bus check",
        "body": "The notification bus is wired up and delivering.",
        "priority": args.priority,
        "tags": ["ops", "sukumo"],
        "source": args.source,
    }
    response = httpx.post(
        f"{args.base.rstrip('/')}/api/notify",
        json=payload,
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=15.0,
    )
    print(f"POST /api/notify -> {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    if response.status_code >= 400:
        sys.exit(1)


if __name__ == "__main__":
    main()
