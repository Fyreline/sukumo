"""app.clients.weather -- Open-Meteo client, keyless, read-only
(docs/API.md #6, docs/ARCHITECTURE.md #5.1)."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.clients import weather as weather_client
from app.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(home_lat=None, home_lon=None, office_lat=None, office_lon=None)
    base.update(overrides)
    return Settings(**base)


@pytest.mark.anyio
async def test_not_configured_when_no_coords_set():
    with pytest.raises(weather_client.WeatherNotConfigured):
        await weather_client.fetch_home_and_office(_settings())


@pytest.mark.anyio
@respx.mock
async def test_fetches_only_configured_locations():
    respx.get(weather_client.OPEN_METEO_URL).mock(
        return_value=httpx.Response(200, json={"daily": {"temperature_2m_max": [20.0]}})
    )
    result = await weather_client.fetch_home_and_office(_settings(home_lat=55.95, home_lon=-3.19))
    assert "home" in result
    assert "office" not in result
    assert result["home"]["daily"]["temperature_2m_max"] == [20.0]


@pytest.mark.anyio
@respx.mock
async def test_fetches_both_when_both_configured():
    respx.get(weather_client.OPEN_METEO_URL).mock(
        return_value=httpx.Response(200, json={"daily": {"temperature_2m_max": [18.0]}})
    )
    result = await weather_client.fetch_home_and_office(
        _settings(home_lat=55.95, home_lon=-3.19, office_lat=55.86, office_lon=-4.25)
    )
    assert "home" in result
    assert "office" in result


@pytest.mark.anyio
@respx.mock
async def test_read_only_no_write_verbs_used():
    """docs/ARCHITECTURE.md #5.1: clients/*.py never call .post/.put/.delete
    (checked at the source level in test_architecture_rules.py); this just
    confirms the client actually issues a GET."""
    route = respx.get(weather_client.OPEN_METEO_URL).mock(
        return_value=httpx.Response(200, json={"daily": {}})
    )
    await weather_client.fetch_forecast(55.95, -3.19)
    assert route.called
