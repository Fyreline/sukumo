"""Per-user JWT auth guard + the ingest-token guard (docs/AUTH.md §3).

Every router except ``/api/health`` and the login/refresh/logout endpoints in
``routers/auth.py`` requires a valid ``Authorization: Bearer <access token>``
JWT, verified here. Unchanged port of Michi's ``app/auth.py`` (itself a
renamed port of Mishka Hub's) — docs/AUTH.md.

``ingest_token_auth`` is the second, disjoint door (docs/AUTH.md §3):
``/api/ingest/*`` and ``/api/notify`` check a sha256-hashed bearer token
against ``ingest_tokens``, never a JWT — a JWT presented here won't hash to
any stored token (401), and a raw ingest token presented to ``current_user``
above isn't valid JWT structure (also 401). The two token kinds share
nothing but the ``Authorization: Bearer`` header shape.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .errors import SukumoHTTPException
from .models import IngestToken
from .security import TokenError, decode_access_token


def current_user(request: Request) -> int:
    """Verify the bearer JWT and return the authenticated user's id.

    Also sets ``request.state.user_id`` so downstream handlers can read it
    without re-decoding the token.
    """
    settings = request.app.state.settings

    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise SukumoHTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
            code="unauthorized",
        )

    token = header.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(token, settings)
    except TokenError as exc:
        raise SukumoHTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
            code="unauthorized",
        ) from exc

    request.state.user_id = user_id
    return user_id


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ingest_token_auth(required_scope: str):
    """FastAPI dependency factory for the ingest-token door (docs/AUTH.md §3).

    ``required_scope`` is ``'ingest'`` (for ``/api/ingest/*``) or ``'notify'``
    (for ``/api/notify``). A token's ``scope`` column is ``'ingest'``,
    ``'notify'``, or ``'ingest+notify'`` — split on ``'+'`` and check
    membership, so a combined token satisfies either door. Also stamps
    ``last_seen_at`` (the Ops/status tile shows token liveness) and 401s on
    revocation, 403s on scope mismatch.
    """

    def _dependency(request: Request, session: Session = Depends(get_session)) -> IngestToken:
        header = request.headers.get("Authorization")
        if not header or not header.startswith("Bearer "):
            raise SukumoHTTPException(
                status_code=401,
                detail="Missing or malformed Authorization header",
                code="unauthorized",
            )

        raw = header.removeprefix("Bearer ").strip()
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        token = session.scalar(select(IngestToken).where(IngestToken.token_hash == token_hash))
        if token is None:
            raise SukumoHTTPException(status_code=401, detail="Invalid ingest token", code="unauthorized")
        if token.revoked_at is not None:
            raise SukumoHTTPException(status_code=401, detail="Ingest token revoked", code="unauthorized")

        allowed_scopes = token.scope.split("+")
        if required_scope not in allowed_scopes:
            raise SukumoHTTPException(
                status_code=403,
                detail=f"Ingest token scope {token.scope!r} does not permit this route",
                code="forbidden",
            )

        token.last_seen_at = _utcnow_str()
        session.commit()
        return token

    return _dependency
