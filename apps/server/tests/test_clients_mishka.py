"""app.clients.mishka -- read-only client for Mishka Hub's GET
/api/activity/service (docs/API.md §4, docs/phases/PHASE-3-siblings.md).
respx-mocked; never hits the real network. filter_payload's nested-list
filtering (each `recent` item) is exercised directly since that's the part
most likely to regress silently."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.clients import mishka as mishka_client
from app.config import Settings

SERVICE_URL = "http://127.0.0.1:8000/api/activity/service"

FULL_PAYLOAD = {
    "recent": [
        {"title": "Paddington", "watched_at": "2026-07-09", "poster_url": "https://img/p.jpg", "rating": 4.5},
        {"title": "Arrival", "watched_at": "2026-07-05", "poster_url": None, "rating": None},
    ],
    "watchlist_count": 7,
}


def _settings(**overrides) -> Settings:
    base = dict(mishka_base_url="http://127.0.0.1:8000", mishka_service_token="")
    base.update(overrides)
    return Settings(**base)


def test_filter_payload_keeps_only_top_level_contract_fields():
    raw = dict(FULL_PAYLOAD, ratings_breakdown={"5": 3}, user_ids=[1, 2])
    filtered = mishka_client.filter_payload(raw)
    assert set(filtered.keys()) == {"recent", "watchlist_count"}


def test_filter_payload_strips_extra_fields_inside_recent_items():
    raw = {
        "recent": [
            {
                "title": "Paddington",
                "watched_at": "2026-07-09",
                "poster_url": "https://img/p.jpg",
                "rating": 4.5,
                "tmdb_id": 123456,
                "letterboxd_uri": "https://letterboxd.com/film/paddington/",
            }
        ],
        "watchlist_count": 1,
    }
    filtered = mishka_client.filter_payload(raw)
    assert filtered["recent"] == [
        {"title": "Paddington", "watched_at": "2026-07-09", "poster_url": "https://img/p.jpg", "rating": 4.5}
    ]


def test_filter_payload_handles_missing_recent_key():
    filtered = mishka_client.filter_payload({"watchlist_count": 3})
    assert filtered == {"watchlist_count": 3}


@pytest.mark.anyio
async def test_fetch_raises_not_configured_when_token_unset():
    with pytest.raises(mishka_client.MishkaNotConfigured):
        await mishka_client.fetch(_settings())


@pytest.mark.anyio
@respx.mock
async def test_fetch_returns_filtered_payload_on_200():
    respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    result = await mishka_client.fetch(_settings(mishka_service_token="secret-token"))
    assert result == FULL_PAYLOAD


@pytest.mark.anyio
@respx.mock
async def test_fetch_sends_bearer_token():
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await mishka_client.fetch(_settings(mishka_service_token="secret-token"))
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_401():
    respx.get(SERVICE_URL).mock(return_value=httpx.Response(401, json={"detail": "unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await mishka_client.fetch(_settings(mishka_service_token="wrong-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_timeout():
    respx.get(SERVICE_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(httpx.TimeoutException):
        await mishka_client.fetch(_settings(mishka_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_fetch_raises_on_connect_error():
    respx.get(SERVICE_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError):
        await mishka_client.fetch(_settings(mishka_service_token="secret-token"))


@pytest.mark.anyio
@respx.mock
async def test_read_only_no_write_verbs_used():
    route = respx.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=FULL_PAYLOAD))
    await mishka_client.fetch(_settings(mishka_service_token="secret-token"))
    assert route.called
