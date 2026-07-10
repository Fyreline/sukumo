"""Sukumo FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --port 8301 --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import engine
from .errors import register_error_handlers
from .identity import MishkaIdentityClient
from .models import Base
from .routers import auth, habits, health, ingest, status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.identity = MishkaIdentityClient(settings.mishka_base_url)
    # SQLite; tables created on startup (docs/ARCHITECTURE.md §4 — Alembic
    # only if a breaking change ever demands it).
    Base.metadata.create_all(engine)
    logger.info("lifespan: tables ensured, Mishka base url = %s", settings.mishka_base_url)
    yield


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title="Sukumo", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    # /api/health, /api/auth/(login|refresh|logout), and /api/ingest/* stay
    # public to JWT auth (ingest routes carry their own token-auth door,
    # docs/AUTH.md §3); /api/auth/me, /api/habits/*, /api/status enforce
    # JWT auth via Depends(current_user). Later phases' routers (dashboard/
    # people/nudges/journal/notify) are wired in as they're built
    # (docs/ARCHITECTURE.md §1).
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(habits.router, prefix="/api")
    app.include_router(status.router, prefix="/api")

    return app


app = create_app()
