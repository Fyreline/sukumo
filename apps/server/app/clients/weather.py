"""Open-Meteo forecast client (keyless) -- docs/API.md #6,
docs/phases/PHASE-2-ingestion.md build item 5.

docs/ARCHITECTURE.md #5.1 (hard rule): read-only -- this module must never
issue a write HTTP verb (POST/PUT/DELETE).

Coordinates come from Settings (SUKUMO_HOME_LAT/LON, SUKUMO_OFFICE_LAT/LON),
which may be unset -- callers (scripts/poll_sources.py) turn that into a
'not_configured' sync_run rather than crashing.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_DAILY_FIELDS = "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"


class WeatherNotConfigured(RuntimeError):
    """Neither home nor office coordinates are set (SUKUMO_HOME_LAT/LON /
    SUKUMO_OFFICE_LAT/LON)."""


async def fetch_forecast(lat: float, lon: float, timeout: float = 10.0) -> dict:
    """One Open-Meteo daily forecast call for a single lat/lon (read-only GET)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": _DAILY_FIELDS,
        "timezone": "Europe/London",
        "forecast_days": 3,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        return response.json()


async def fetch_home_and_office(settings, timeout: float = 10.0) -> dict:
    """Fetches whichever of home/office is configured.

    Returns ``{"home": {...forecast...}, "office": {...forecast...}}`` with
    only the configured keys present. Raises WeatherNotConfigured if neither
    location has both lat and lon set.
    """
    have_home = settings.home_lat is not None and settings.home_lon is not None
    have_office = settings.office_lat is not None and settings.office_lon is not None
    if not have_home and not have_office:
        raise WeatherNotConfigured("neither SUKUMO_HOME_LAT/LON nor SUKUMO_OFFICE_LAT/LON are set")

    result: dict = {}
    if have_home:
        result["home"] = await fetch_forecast(settings.home_lat, settings.home_lon, timeout=timeout)
    if have_office:
        result["office"] = await fetch_forecast(settings.office_lat, settings.office_lon, timeout=timeout)
    result["_fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return result
