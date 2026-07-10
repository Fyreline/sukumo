"""JWT access tokens + opaque rotating refresh tokens.

Ported from Dev/learningLanguageMachine (Michi)/apps/server/app/security.py,
itself a port of Mishka Hub's, per docs/AUTH.md: the password-hashing
functions and their password-hashing-library import are deleted entirely —
Sukumo never stores, hashes, or even sees a hash of a password (there is no
password-hashing dependency anywhere in requirements.txt; that absence is the
proof Sukumo holds no passwords).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import Settings

_JWT_ALGORITHM = "HS256"


# --------------------------------------------------------------------------
# JWT access tokens — short-lived, stateless, never revoked individually
# (revocation is via the refresh token; a leaked access token just expires).
# --------------------------------------------------------------------------
def create_access_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


class TokenError(RuntimeError):
    pass


def decode_access_token(token: str, settings: Settings) -> int:
    """Returns the user id, or raises TokenError on invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("malformed token payload") from exc


# --------------------------------------------------------------------------
# Refresh tokens — opaque random strings, stored as a sha256 hash
# (`refresh_tokens.token_hash`) so a DB read alone never yields a usable
# token. Rotated on every use (docs/AUTH.md): the presented token is marked
# revoked and a new one issued in the same request.
# --------------------------------------------------------------------------
def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token_to_send_to_client, sha256_hash_to_store)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
