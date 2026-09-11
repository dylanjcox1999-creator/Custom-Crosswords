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
    create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey
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
