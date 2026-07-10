"""Per-user JWT auth guard.

Every router except ``/api/health`` and the login/refresh/logout endpoints in
``routers/auth.py`` requires a valid ``Authorization: Bearer <access token>``
JWT, verified here. Unchanged port of Michi's ``app/auth.py`` (itself a
renamed port of Mishka Hub's) — docs/AUTH.md.
"""
from __future__ import annotations

from fastapi import Request

from .errors import SukumoHTTPException
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
