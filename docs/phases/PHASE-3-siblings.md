# Phase 3 — Sibling read endpoints + clients (owner: Sonnet)

Three small additive PRs in the sibling repos + Honmaru's clients. Needs HANDOFF Q7
green-lit. Each sibling patch follows that repo's own conventions (their CLAUDE.md /
docs take precedence over anything here except the response shapes, which API §4 owns).

## Build
1. **Michi** `GET /api/stats/service`: shape per API §4, `MICHI_SERVICE_TOKEN` env,
   401 without; reuses existing stats queries — no new logic. Tests in Michi's suite.
2. **Kakeibo** `GET /api/goal/service`: same pattern (`KAKEIBO_SERVICE_TOKEN`); goal
   numbers from its existing goal engine; respects its PRIVATE-config rule (target
   comes from runtime config, never hardcoded).
3. **Mishka** `GET /api/activity/service`: recent watches + watchlist_count
   (`MISHKA_SERVICE_TOKEN`).
4. Honmaru `clients/michi|kakeibo|mishka.py`: httpx GET, 3s timeout, snapshot row
   ok/error/latency; wired into `poll_sources.py` (15-min cadence with the tick).
5. Consecutive-failure counting for the ops rule (query over last N snapshots — no
   new state).

## Acceptance
- [ ] Each sibling: endpoint 200s with token, 401s without, in *its* test suite;
      deployed to the household Mac; sibling's own health endpoint still fine.
- [ ] Honmaru `/api/status` shows all three green with real latencies; stopping
      Michi's uvicorn → snapshot error rows accumulate → status shows it red with
      age; restart → green again (run this, don't imagine it).
- [ ] Snapshot payloads contain ONLY the API §4 fields (contract test).
- [ ] All four repos: tests + typecheck green (paste each).
