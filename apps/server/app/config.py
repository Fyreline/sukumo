"""Application settings, loaded from environment / .env file.

All settings are prefixed with SUKUMO_ (docs/ARCHITECTURE.md §4). Sukumo's
secret and settings are entirely independent of Mishka Hub's own — the two
apps share nothing but the identity verification call (docs/AUTH.md).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../sukumo/apps/server/app/config.py
#   parents[1] = apps/server (the backend dir, where .env lives)
#   parents[3] = sukumo (the project root, where data/ lives)
SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVER_DIR / ".env"),
        env_prefix="SUKUMO_",
        extra="ignore",
    )

    environment: str = "development"

    # --- Auth (docs/AUTH.md). 32+ random bytes, e.g. `openssl rand -hex 32`.
    # Independent of MISHKA_JWT_SECRET/MICHI_JWT_SECRET/KAKEIBO_JWT_SECRET —
    # rotating one never affects the other apps' sessions. ---
    jwt_secret: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # --- The one call Sukumo makes to Mishka Hub: verifying a login
    # (docs/AUTH.md §1). Loopback by default; identity.py refuses a plain
    # http non-loopback URL at startup. ---
    mishka_base_url: str = "http://127.0.0.1:8000"

    # --- docs/AUTH.md §1, the one delta from Michi: the household member
    # whose (lowercased) email matches this becomes role='primary' on first
    # login; everyone else is 'partner'. The coach only nudges 'primary' at
    # v1 (HANDOFF Q9 decides Amy's experience later). Set via .env, never
    # committed (docs/ARCHITECTURE.md §5.5). ---
    primary_email: str = ""

    # --- CORS. Sukumo's web app owns 5179 (Mishka 5173, Michi 5174, Kakeibo
    # 5178). ---
    cors_origins: list[str] = [
        "http://localhost:5179",
        "http://127.0.0.1:5179",
        "https://fyreline.github.io",
    ]

    # SQLite lives in the project-level data/ folder (CWD-independent absolute path).
    database_url: str = f"sqlite:///{DATA_DIR / 'sukumo.db'}"

    # --- docs/API.md §6 (ambient sources), docs/ARCHITECTURE.md §4. Comma-
    # separated ICS subscription URLs; may be unset (poll_sources reports
    # sync_runs status 'not_configured', never crashes). Not a pydantic
    # list[str] field on purpose — that would parse the env var as JSON. ---
    ics_urls: str = ""

    # --- Weather (docs/API.md §6): Open-Meteo coords for home/office. Any or
    # all may be unset — clients/weather.py + poll_sources.py handle that as
    # 'not_configured', never a crash. PRIVATE values (ARCHITECTURE §5.5):
    # .env only, never committed. ---
    home_lat: float | None = None
    home_lon: float | None = None
    office_lat: float | None = None
    office_lon: float | None = None

    # --- Sibling read clients (docs/API.md §4, docs/phases/PHASE-3-siblings.md):
    # one static service token per app, deliberately NOT the user-JWT flow —
    # Sukumo never holds a household password for the siblings. Base URLs
    # default to loopback at each app's own port (ARCHITECTURE §2's port
    # ladder); an empty *_service_token is what makes a client
    # 'not_configured' (never a crash — app/clients/*.py + poll_sources.py).
    # Kakeibo's endpoint doesn't exist yet server-side as of this phase (its
    # repo has unrelated in-flight work) — the client stays wired and stays
    # 'not_configured' until KAKEIBO_SERVICE_TOKEN is set for real. Mishka's
    # base URL is deliberately the SAME field identity.py already uses
    # (mishka_base_url) — one app, one loopback address. ---
    michi_base_url: str = "http://127.0.0.1:8100"
    michi_service_token: str = ""

    kakeibo_base_url: str = "http://127.0.0.1:8200"
    kakeibo_service_token: str = ""

    mishka_service_token: str = ""

    @property
    def auth_configured(self) -> bool:
        return bool(self.jwt_secret)

    @property
    def ics_url_list(self) -> list[str]:
        return [u.strip() for u in self.ics_urls.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
