"""app/identity.py — MishkaIdentityClient, stubbed via respx (docs/AUTH.md §1).

Covers the 200/401/429/timeout/connection-error cases per
docs/phases/PHASE-1-scaffold.md's pytest requirement.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from app.identity import (
    IdentityRateLimited,
    IdentityRejected,
    IdentityUnavailable,
    MishkaIdentityClient,
)

BASE = "http://127.0.0.1:8000"


@pytest.mark.anyio
@respx.mock
async def test_verify_success_returns_user_and_logs_out_throwaway_session():
    respx.post(f"{BASE}/api/auth/login").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "throwaway-access",
                "refresh_token": "throwaway-refresh",
                "expires_in": 900,
                "user": {"id": 1, "email": "a@example.com", "display_name": "Amy"},
            },
        )
    )
    logout_route = respx.post(f"{BASE}/api/auth/logout").mock(
        return_value=httpx.Response(200, json={"logged_out": True})
    )

    client = MishkaIdentityClient(BASE)
    user = await client.verify("a@example.com", "hunter2")

    assert user.id == 1
    assert user.email == "a@example.com"
    assert user.display_name == "Amy"
    assert logout_route.called, "should best-effort log out the throwaway Mishka session"


@pytest.mark.anyio
@respx.mock
async def test_verify_401_raises_rejected():
    respx.post(f"{BASE}/api/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "no", "code": "invalid_credentials"})
    )
    client = MishkaIdentityClient(BASE)
    with pytest.raises(IdentityRejected):
        await client.verify("a@example.com", "wrong")


@pytest.mark.anyio
@respx.mock
async def test_verify_429_raises_rate_limited():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=httpx.Response(429, json={"detail": "slow down"}))
    client = MishkaIdentityClient(BASE)
    with pytest.raises(IdentityRateLimited):
        await client.verify("a@example.com", "pw")


@pytest.mark.anyio
@respx.mock
async def test_verify_timeout_raises_unavailable():
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=httpx.TimeoutException("timed out"))
    client = MishkaIdentityClient(BASE)
    with pytest.raises(IdentityUnavailable):
        await client.verify("a@example.com", "pw")


@pytest.mark.anyio
@respx.mock
async def test_verify_connection_error_raises_unavailable():
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    client = MishkaIdentityClient(BASE)
    with pytest.raises(IdentityUnavailable):
        await client.verify("a@example.com", "pw")


@pytest.mark.anyio
@respx.mock
async def test_ping_true_when_reachable():
    respx.get(f"{BASE}/api/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    client = MishkaIdentityClient(BASE)
    assert await client.ping() is True


@pytest.mark.anyio
@respx.mock
async def test_ping_false_when_unreachable():
    respx.get(f"{BASE}/api/health").mock(side_effect=httpx.ConnectError("refused"))
    client = MishkaIdentityClient(BASE)
    assert await client.ping() is False


def test_rejects_plain_http_non_loopback():
    with pytest.raises(ValueError):
        MishkaIdentityClient("http://example.com")


def test_accepts_https_non_loopback():
    MishkaIdentityClient("https://example.com")  # should not raise


def test_accepts_plain_http_loopback():
    MishkaIdentityClient("http://127.0.0.1:8000")  # should not raise
