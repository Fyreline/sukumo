"""Shared pytest fixtures.

Sets test-only env vars (isolated sqlite file, a throwaway JWT secret) BEFORE
anything imports the ``app`` package, since app/config.py + app/db.py read
settings at import time. No pytest-asyncio needed: FastAPI's own dependency
(starlette) pulls in anyio, which registers its own pytest plugin, so plain
``@pytest.mark.anyio`` works for testing async code directly (e.g.
identity.py) without an extra dev dependency.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="sukumo-test-"))
os.environ.setdefault("SUKUMO_JWT_SECRET", "test-secret-not-for-production-use-only")
os.environ.setdefault("SUKUMO_DATABASE_URL", f"sqlite:///{_TEST_DATA_DIR / 'sukumo-test.db'}")
os.environ.setdefault("SUKUMO_MISHKA_BASE_URL", "http://127.0.0.1:8000")
os.environ.setdefault("SUKUMO_PRIMARY_EMAIL", "mack@example.com")
os.environ.setdefault("SUKUMO_ENVIRONMENT", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.routers import auth as auth_module  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh tables and a reset login rate-limit deque for every test — both
    are module-level state that would otherwise leak between tests."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    auth_module._login_failures.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_user(
    email: str = "amy@example.com", display_name: str = "Amy", role: str = "partner"
) -> int:
    """Insert a Sukumo user row directly (bypassing the Mishka login proxy)
    and return its id — for exercising authed routes without standing up a
    fake identity server."""
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        user = User(
            email=email.lower(),
            display_name=display_name,
            role=role,
            created_at="2026-07-01 00:00:00",
        )
        db.add(user)
        db.commit()
        return user.id


def auth_headers(user_id: int) -> dict[str, str]:
    from app.config import get_settings
    from app.security import create_access_token

    token = create_access_token(user_id, get_settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def authed(client):
    """(client, user_id, headers) for a freshly-inserted household user."""
    user_id = make_user()
    return client, user_id, auth_headers(user_id)
