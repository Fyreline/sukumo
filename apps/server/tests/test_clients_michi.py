"""app.clients.michi -- read-only client for Michi's GET /api/stats/service
(docs/API.md §4, docs/phases/PHASE-3-siblings.md). respx-mocked; never hits
the real network. Contract-filtering behaviour (DATA_MODEL §6) is asserted
directly against ``filter_payload`` since that's the single enforcement
point poll_sources.py relies on."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.clients import michi as michi_client
from app.config import Settings

SERVICE_URL = "http://127.0.0.1:8100/api/stats/service"

FULL_PAYLOAD = {
    "streak_days": 12,
    "studied_today": True,
    "due_reviews": 4,
    "words_known": 210,
    "last_session_at": "2026-07-10 08:15:00",
}


def _settings(**overrides) -> Settings:
    base = dict(michi_base_url="http://127.0.0.1:8100", michi_service_token="")
    base.update(overrides)
    return Settings(**base)


def test_filter_payload_keeps_only_contract_fields():
    """docs/DATA_MODEL.md §6: never re-derive sibling domain logic beyond
    the agreed read-contract fields -- extras must be dropped, not stored."""
    raw = dict(FULL_PAYLOAD, extra_field="should not survive", another=123)
    filtered = michi_client.filter_payload(raw)
    assert filtered == FULL_PAYLOAD
    assert "extra_field" not in filtered
    assert "another" not in filtered


def test_filter_payload_missing_fields_are_simply_absent():
    filtered = michi_client.filter_payload({"streak_days": 3})
    assert filtered == {"streak_days": 3}


@pytest.mark.anyio
async def test_fetch_raises_not_configured_when_token_unset():
    with pytest.raises(michi_client.MichiNotConfigured):
        await michi_client.fetch(_settings())


@pytest.mark.anyio
@respx.mock
async def test_fetch_returns_filtered_payload_on_200():
    respx.get(SERVICE_URL).mock(
        return_value=httpx.Response(200, json=dict(FULL_PAYLOAD, unexpected="drop me"))
    )
    result = await michi_client.fetch(_settings(michi_service_token="secret-token"))
    assert result == FULL_PAYLOAD


@pytest.mark.anyio
@respx.mock
async def test_fetch_sends_bearer_token():
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await michi_client.fetch(_settings(michi_service_token="secret-token"))
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_401():
    respx.get(SERVICE_URL).mock(return_value=httpx.Response(401, json={"detail": "unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await michi_client.fetch(_settings(michi_service_token="wrong-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_timeout():
    respx.get(SERVICE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(httpx.TimeoutException):
        await michi_client.fetch(_settings(michi_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_connect_error():
    respx.get(SERVICE_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError):
        await michi_client.fetch(_settings(michi_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_read_only_no_write_verbs_used():
    """docs/ARCHITECTURE.md §5.1: clients/*.py never call .post/.put/.delete
    (checked at the source level in test_architecture_rules.py); this just
    confirms the client actually issues a GET."""
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await michi_client.fetch(_settings(michi_service_token="secret-token"))
    assert route.called
