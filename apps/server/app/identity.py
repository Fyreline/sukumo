"""The Mishka Hub identity client — docs/AUTH.md §1-2.

Sukumo holds no credential store of its own. At login it forwards the
submitted email/password to Mishka Hub's own ``/api/auth/login`` purely to
verify them, then discards whatever token pair Mishka Hub hands back (best-
effort logging out that throwaway Mishka session so its own
``refresh_tokens`` table stays tidy). One small class so tests stub it
trivially and a future standalone mode would swap one class. Line-for-line
port of Michi's ``app/identity.py``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class IdentityError(Exception):
    """Base class for identity verification failures."""


class IdentityUnavailable(IdentityError):
    """Mishka Hub could not be reached — connection error, timeout, or 5xx."""


class IdentityRejected(IdentityError):
    """Mishka Hub rejected the credentials (401)."""


class IdentityRateLimited(IdentityError):
    """Mishka Hub's own login rate limit tripped (429)."""


@dataclass
class IdentityUser:
    id: int
    email: str
    display_name: str


class MishkaIdentityClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        parsed = urlparse(base_url)
        is_loopback = parsed.hostname in _LOOPBACK_HOSTS
        if parsed.scheme == "http" and not is_loopback:
            raise ValueError(
                "SUKUMO_MISHKA_BASE_URL must be HTTPS or loopback "
                f"(got {base_url!r}) — docs/AUTH.md §1"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def verify(self, email: str, password: str) -> IdentityUser:
        """Verify credentials against Mishka Hub's login endpoint.

        Never logs the password — any exception raised here carries only a
        fixed message, never the request body (docs/AUTH.md §1).
        """
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                response = await client.post(
                    "/api/auth/login", json={"email": email, "password": password}
                )
                if response.status_code == 200:
                    body = response.json()
                    user = body["user"]
                    refresh_token = body.get("refresh_token")
                    if refresh_token:
                        await self._best_effort_logout(client, refresh_token)
                    return IdentityUser(
                        id=user["id"], email=user["email"], display_name=user["display_name"]
                    )
                if response.status_code == 401:
                    raise IdentityRejected("Incorrect email or password")
                if response.status_code == 429:
                    raise IdentityRateLimited("Mishka Hub's login rate limit was hit")
                raise IdentityUnavailable(f"Unexpected status {response.status_code}")
        except httpx.TimeoutException as exc:
            raise IdentityUnavailable("Mishka Hub timed out") from exc
        except httpx.HTTPError as exc:
            raise IdentityUnavailable("Mishka Hub is not reachable") from exc

    async def _best_effort_logout(self, client: httpx.AsyncClient, refresh_token: str) -> None:
        """Keeps Mishka's refresh_tokens table tidy. Never raises — a
        failure here must never fail the Sukumo login."""
        try:
            await client.post("/api/auth/logout", json={"refresh_token": refresh_token})
        except httpx.HTTPError:
            logger.warning("identity: best-effort logout of the throwaway Mishka session failed")

    async def ping(self) -> bool:
        """1s-timeout reachability probe (cached by callers)."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=1.0) as client:
                response = await client.get("/api/health")
                return response.status_code < 500
        except httpx.HTTPError:
            return False
