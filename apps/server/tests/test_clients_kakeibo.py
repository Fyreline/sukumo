"""app.clients.kakeibo -- read-only client for Kakeibo's GET /api/goal/service
(docs/API.md §4, docs/phases/PHASE-3-siblings.md). respx-mocked; never hits
the real network. Kakeibo's own endpoint doesn't exist yet this phase (its
repo is deliberately untouched) -- these tests exercise the client against a
synthetic mock, exactly as they will once the real endpoint lands."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.clients import kakeibo as kakeibo_client
from app.config import Settings

SERVICE_URL = "http://127.0.0.1:8200/api/goal/service"

FULL_PAYLOAD = {
    "goal_pence": 2000000,
    "saved_pence": 850000,
    "pct": 42.5,
    "pace_status": "on_track",
    "as_of": "2026-07-10 00:00:00",
}


def _settings(**overrides) -> Settings:
    base = dict(kakeibo_base_url="http://127.0.0.1:8200", kakeibo_service_token="")
    base.update(overrides)
    return Settings(**base)


def test_filter_payload_keeps_only_contract_fields():
    raw = dict(FULL_PAYLOAD, transactions=["should not survive"], balance_pence=999999)
    filtered = kakeibo_client.filter_payload(raw)
    assert filtered == FULL_PAYLOAD
    assert "transactions" not in filtered
    assert "balance_pence" not in filtered


@pytest.mark.anyio
async def test_fetch_raises_not_configured_when_token_unset():
    with pytest.raises(kakeibo_client.KakeiboNotConfigured):
        await kakeibo_client.fetch(_settings())


@pytest.mark.anyio
async def test_fetch_not_configured_is_the_default_settings():
    """Scope note (docs/API.md §4): Kakeibo's endpoint doesn't exist yet, so
    the default (unset) settings must always resolve to not_configured,
    never a network attempt."""
    with pytest.raises(kakeibo_client.KakeiboNotConfigured):
        await kakeibo_client.fetch(Settings())


@pytest.mark.anyio
@respx.mock
async def test_fetch_returns_filtered_payload_on_200():
    respx.get(SERVICE_URL).mock(
        return_value=httpx.Response(200, json=dict(FULL_PAYLOAD, extra="drop me"))
    )
    result = await kakeibo_client.fetch(_settings(kakeibo_service_token="secret-token"))
    assert result == FULL_PAYLOAD


@pytest.mark.anyio
@respx.mock
async def test_fetch_sends_bearer_token():
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await kakeibo_client.fetch(_settings(kakeibo_service_token="secret-token"))
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_401():
    respx.get(SERVICE_URL).mock(return_value=httpx.Response(401, json={"detail": "unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await kakeibo_client.fetch(_settings(kakeibo_service_token="wrong-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_timeout():
    respx.get(SERVICE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(httpx.TimeoutException):
        await kakeibo_client.fetch(_settings(kakeibo_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_connect_error():
    respx.get(SERVICE_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError):
        await kakeibo_client.fetch(_settings(kakeibo_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_read_only_no_write_verbs_used():
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await kakeibo_client.fetch(_settings(kakeibo_service_token="secret-token"))
    assert route.called
