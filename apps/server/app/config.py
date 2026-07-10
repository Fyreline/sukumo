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

    @property
    def auth_configured(self) -> bool:
        return bool(self.jwt_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
