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
from .routers import auth, dashboard, habits, health, ingest, journal, notify, nudges, people, settings as settings_router, status

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
    # Discover coach rules at startup so their import side effects run — chiefly
    # registering action callbacks (the reading rule's one-tap habit-event
    # writer, COACH.md §3.3) so /api/nudges/act/{token} can find them.
    from .coach.rules import load_rules

    load_rules()
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

    # /api/health, /api/auth/(login|refresh|logout), /api/ingest/*, and
    # /api/notify stay public to JWT auth (ingest/notify routes carry their
    # own token-auth door, docs/AUTH.md §3); /api/auth/me, /api/habits/*,
    # /api/books/*, /api/status and /api/dashboard enforce JWT auth via
    # Depends(current_user); /api/people|occasions|gifts and /api/nudges
    # additionally require role='primary' (routers/people.py,
    # routers/nudges.py) — except GET /api/nudges/act/{token}, deliberately
    # open (AUTH.md §4). /api/journal + /api/digests are primary-only too
    # (routers/journal.py, Phase 7, docs/MEMORY.md §5).
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(notify.router, prefix="/api")
    app.include_router(nudges.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(habits.router, prefix="/api")
    app.include_router(people.router, prefix="/api")
    app.include_router(journal.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    app.include_router(settings_router.router, prefix="/api")

    return app


app = create_app()
