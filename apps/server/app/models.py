"""SQLAlchemy 2.x ORM models — mirrors docs/DATA_MODEL.md §1 (identity &
tokens). Credentials live in Mishka Hub (docs/AUTH.md); Sukumo only mirrors
the household identity plus its own session tokens. Timestamps are UTC
``"%Y-%m-%d %H:%M:%S"`` strings (the siblings' convention).

Phase 1 (scaffold) only defines the identity tables auth needs. Habits,
people/occasions, memory, coach, notify, and ingest-token tables (DATA_MODEL
§2-7) are added by the phases that own them (docs/phases/PHASE-2..7).
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# datetime('now') default, shared by every *_at/created_at column that uses it.
NOW = text("datetime('now')")


# ============ users — one household identity, mirrored from Mishka Hub ============
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(nullable=False, unique=True)  # lower()
    display_name: Mapped[str] = mapped_column(nullable=False)  # refreshed at every login
    # 'primary' | 'partner' — set once, on first successful proxied login
    # (docs/AUTH.md §1: primary = email matches SUKUMO_PRIMARY_EMAIL).
    role: Mapped[str] = mapped_column(nullable=False, server_default=text("'partner'"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ refresh_tokens — line-for-line port of Michi's/Mishka's ============
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(nullable=False)
    revoked: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (Index("idx_refresh_user", "user_id", "revoked"),)
