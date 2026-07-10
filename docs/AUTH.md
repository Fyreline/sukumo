# Sukumo — Auth

Michi's pattern, verbatim in spirit: **one household credential store — Mishka Hub's.**
Sukumo never stores, hashes, or sees a hash of a password.

## 1. Interactive login (humans, the PWA)

`POST /api/auth/login` proxies the email/password to
`{SUKUMO_MISHKA_BASE_URL}/api/auth/login` (httpx, 5s timeout); on 200 it upserts the
local `users` row from the returned `{id, email, display_name}` and issues **Sukumo's
own** JWT access + rotating refresh tokens (`security.py` is a port of Michi's,
including the refresh-reuse tripwire). 401/429 pass through with the same shape;
connection failure → 503 `identity_unavailable`. Sessions are fully independent of
Mishka after login — its restarts don't log anyone out here.

Port checklist (files named in ARCHITECTURE §1): `security.py`, `identity.py`,
`routers/auth.py`, web `auth.ts` (storage key `sukumo_auth`) + `api.ts` 401-refresh
retry. The only delta from Michi: on first login, `role` is set `primary` for the email
matching `SUKUMO_PRIMARY_EMAIL`, else `partner` — the coach only nudges `primary` at
v1 (HANDOFF Q9 decides Amy's experience later).

## 2. Why not the alternatives

Same table as Michi's AUTH.md §1 — copied conclusions, not re-argued: no credential
copy/sync (drift), no cross-app DB reads (locking, coupling), no shared JWT secret
(coupled rotation, shared blast radius). Proxy-verify + own tokens wins again.

## 3. Ingest tokens (machines)

Everything that can't do a login flow — the health-sync Shortcut, other Shortcuts, sibling scripts
posting to the bus — authenticates with a **long-lived bearer token**: minted by
`scripts/mint_ingest_token.py` (prints raw once, stores sha256; DATA_MODEL §1), sent as
`Authorization: Bearer …`, checked by an `ingest_token` dependency that also stamps
`last_seen_at` (the Ops tile shows token liveness). Scopes: `ingest` (only
`/api/ingest/*`), `notify` (only `/api/notify`). Revocation = set `revoked_at`; rotation
= mint new, update the one client, revoke old. Tokens never grant any JWT-protected
route, and JWTs never grant ingest routes — two disjoint doors.

## 4. The one-click action link

`GET /api/nudges/act/{token}` (API.md §1) is deliberately open-but-signed: token =
HMAC(JWT_SECRET, nudge_id + expiry), single-use (consumed on first hit), expires when
the nudge does. It can only ever mark *that one nudge* `actioned`/`dismissed` — no data
readable, no other write reachable — which is the correct privilege for a URL that
lives inside a phone notification.
