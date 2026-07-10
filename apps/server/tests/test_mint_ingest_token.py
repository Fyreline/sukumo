"""scripts/mint_ingest_token.py -- mints a token, stores only its sha256
hash, rejects an invalid scope (docs/AUTH.md #3)."""
from __future__ import annotations

import hashlib

import pytest

from scripts.mint_ingest_token import mint


def test_mint_stores_hash_not_raw_token():
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import IngestToken

    raw = mint("test-mint", "ingest", None)
    assert raw  # non-empty raw token returned to the caller

    with SessionLocal() as db:
        row = db.scalar(select(IngestToken).where(IngestToken.name == "test-mint"))
        assert row is not None
        assert row.token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert row.token_hash != raw


def test_mint_rejects_invalid_scope():
    with pytest.raises(SystemExit):
        mint("bad-scope-token", "not-a-real-scope", None)


def test_mint_with_user_id_binds_token():
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import IngestToken, User

    with SessionLocal() as db:
        user = User(email="mint-test@example.com", display_name="Mint Test", role="partner", created_at="2026-01-01 00:00:00")
        db.add(user)
        db.commit()
        user_id = user.id

    mint("bound-token", "ingest", user_id)

    with SessionLocal() as db:
        row = db.scalar(select(IngestToken).where(IngestToken.name == "bound-token"))
        assert row.user_id == user_id
