"""Login/session endpoints — docs/AUTH.md §1, docs/API.md "Auth".

POST /api/auth/login    email + password -> access + refresh token pair
                         (verified against Mishka Hub; never stored locally)
POST /api/auth/refresh  refresh token -> new access + refresh token pair (rotated)
POST /api/auth/logout   refresh token -> revoked
GET  /api/auth/me       the authenticated user's own profile

No registration endpoint exists — there is only one credential store
(Mishka Hub's); see docs/AUTH.md.

The one delta from Michi's port (docs/AUTH.md §1): on first login, ``role``
is set to ``'primary'`` when the email matches ``SUKUMO_PRIMARY_EMAIL``,
else ``'partner'``.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..errors import SukumoHTTPException
from ..identity import (
    IdentityRateLimited,
    IdentityRejected,
    IdentityUnavailable,
    MishkaIdentityClient,
)
from ..models import RefreshToken, User
from ..security import create_access_token, generate_refresh_token, hash_refresh_token

router = APIRouter(tags=["auth"])

# --- simple in-process login rate limit (docs/AUTH.md: "same 5-failures/
# 15-min/IP deque as Mishka"), in front of the identity proxy call so a brute
# force can't use Sukumo to hammer Mishka. ---
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # cloudflared terminates TLS and proxies to loopback-only uvicorn, so
    # X-Forwarded-For is trustworthy here (docs/ARCHITECTURE.md §5).
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window = _login_failures[ip]
    while window and now - window[0] > _LOGIN_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _LOGIN_MAX_FAILURES:
        raise SukumoHTTPException(
            status_code=429,
            detail="Too many failed login attempts — try again later.",
            code="rate_limited",
        )


def _record_failure(ip: str) -> None:
    _login_failures[ip].append(time.monotonic())


def _record_success(ip: str) -> None:
    _login_failures.pop(ip, None)


class LoginBody(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: dict


def _issue_tokens(session: Session, user: User, request: Request) -> TokenPair:
    settings = request.app.state.settings
    access = create_access_token(user.id, settings)
    raw_refresh, refresh_hash = generate_refresh_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
    ).strftime("%Y-%m-%d %H:%M:%S")
    session.add(RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=expires_at))
    session.commit()
    return TokenPair(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
        },
    )


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, session: Session = Depends(get_session)) -> TokenPair:
    ip = _client_ip(request)
    _check_rate_limit(ip)

    settings = request.app.state.settings
    if not settings.auth_configured:
        raise SukumoHTTPException(
            status_code=503,
            detail="Login is not configured on this server (SUKUMO_JWT_SECRET unset).",
            code="auth_not_configured",
        )

    identity: MishkaIdentityClient = request.app.state.identity
    email = body.email.strip().lower()
    try:
        identity_user = await identity.verify(email, body.password)
    except IdentityRejected as exc:
        _record_failure(ip)
        raise SukumoHTTPException(
            status_code=401, detail="Incorrect email or password", code="invalid_credentials"
        ) from exc
    except IdentityRateLimited as exc:
        raise SukumoHTTPException(
            status_code=429,
            detail="Too many failed login attempts — try again later.",
            code="rate_limited",
        ) from exc
    except IdentityUnavailable as exc:
        raise SukumoHTTPException(
            status_code=503,
            detail="Mishka Hub isn't reachable — Sukumo borrows its login. Is it running?",
            code="identity_unavailable",
        ) from exc

    _record_success(ip)

    # Upsert local users row keyed by lower(email) — display_name refreshed
    # on every login, so renames on the Mishka Hub side follow too
    # (docs/AUTH.md §1). ``role`` is only ever set ONCE, at row creation —
    # the one delta from Michi's port (docs/AUTH.md §1).
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        role = "primary" if email == settings.primary_email.strip().lower() else "partner"
        user = User(email=email, display_name=identity_user.display_name, role=role)
        session.add(user)
    else:
        user.display_name = identity_user.display_name
    session.commit()
    session.refresh(user)

    return _issue_tokens(session, user, request)


class RefreshBody(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
async def refresh(
    body: RefreshBody, request: Request, session: Session = Depends(get_session)
) -> TokenPair:
    token_hash = hash_refresh_token(body.refresh_token)
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if row is None:
        raise SukumoHTTPException(status_code=401, detail="Invalid refresh token", code="invalid_refresh_token")

    if row.revoked:
        # Reuse of an already-rotated-away token: theft tripwire — revoke
        # every refresh token this user holds, forcing a fresh login
        # everywhere (docs/AUTH.md). Mishka Hub sessions are untouched.
        for other in session.scalars(
            select(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked == 0)
        ):
            other.revoked = 1
        session.commit()
        raise SukumoHTTPException(
            status_code=401,
            detail="Refresh token already used — all sessions revoked, please log in again.",
            code="refresh_reuse_detected",
        )

    expires_at = datetime.strptime(row.expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise SukumoHTTPException(status_code=401, detail="Refresh token expired", code="invalid_refresh_token")

    user = session.get(User, row.user_id)
    if user is None:
        raise SukumoHTTPException(status_code=401, detail="Invalid refresh token", code="invalid_refresh_token")

    row.revoked = 1  # rotate: this token is now spent
    session.commit()
    return _issue_tokens(session, user, request)


@router.post("/auth/logout")
async def logout(body: RefreshBody, session: Session = Depends(get_session)) -> dict:
    token_hash = hash_refresh_token(body.refresh_token)
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is not None:
        row.revoked = 1
        session.commit()
    return {"logged_out": True}


@router.get("/auth/me")
async def me(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise SukumoHTTPException(status_code=404, detail="User not found", code="not_found")
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }
