"""
Database layer: users and their solve history.

IMPORTANT: reads DATABASE_URL from the environment. Point this at a real
hosted Postgres instance (Supabase, Neon, or similar) for production --
see README.md for why Render's own free tier can't be used for this.

If DATABASE_URL isn't set, falls back to a local SQLite file for quick
local testing. That fallback is NOT suitable for real deployment on
Render's free tier (ephemeral filesystem -- see README.md), only for
running this on your own machine.
"""
import os
import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./local_dev.db")

# Render/Heroku-style Postgres URLs sometimes use the old "postgres://"
# scheme, which SQLAlchemy's modern driver no longer accepts -- normalize it.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args=(
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Paid-tier support: "free" or "paid". Free-tier users share one daily
    # cap across /generate_puzzle and /reword_clue (the two endpoints that
    # actually cost money per call) -- see usage_limits.py. Paid users are
    # never limited. Nothing bills anyone yet -- this field is what a real
    # payment integration would flip, it doesn't process payment itself.
    tier = Column(String, default="free", nullable=False)
    daily_premium_actions_used = Column(Integer, default=0, nullable=False)
    daily_premium_actions_date = Column(Date, default=lambda: datetime.date.today(), nullable=False)

    solves = relationship("SolveRecord", back_populates="user")


class SolveRecord(Base):
    __tablename__ = "solve_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    topic = Column(String, nullable=False, index=True)
    difficulty = Column(String, nullable=False, default="medium")
    solve_time_seconds = Column(Float, nullable=False)
    hints_used = Column(Integer, nullable=False, default=0)
    completed = Column(Boolean, nullable=False, default=True)
    logged_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    user = relationship("User", back_populates="solves")


class AnonymousUsage(Base):
    """Tracks a small trial allowance for visitors who haven't signed up
    yet, keyed by a random ID generated client-side and stored in the
    browser's localStorage -- NOT by IP address. See usage_limits.py for
    why IP-based tracking was rejected (shared IPs punish innocent users,
    mobile carrier-grade NAT makes it unreliable, and it's trivially
    bypassed by switching networks, which defeats the point of a cost
    control anyway).

    Deliberately stored in the real database, not in-memory: Render's free
    tier sleeps after 15 minutes idle, which would silently reset an
    in-memory counter far too often for this to function as a real trial
    limit.
    """
    __tablename__ = "anonymous_usage"

    anon_id = Column(String, primary_key=True)
    daily_actions_used = Column(Integer, default=0, nullable=False)
    daily_actions_date = Column(Date, default=lambda: datetime.date.today(), nullable=False)


def init_db():
    """Creates tables if they don't already exist. Safe to call on every
    startup -- it's a no-op if the schema is already there."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
