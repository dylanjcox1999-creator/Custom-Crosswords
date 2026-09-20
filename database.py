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
from zoneinfo import ZoneInfo

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship


def _central_today() -> datetime.date:
    """'Today' in Central Time, not server-local (Render runs in UTC).
    Used as the default for daily-reset date columns below, so a brand
    new row starts out already consistent with how usage_limits.py and
    stats.py interpret "today" everywhere else -- without this, a user
    who signs up late at night Central but after UTC midnight would get
    stamped with the wrong day from the very first row."""
    return datetime.datetime.now(ZoneInfo("America/Chicago")).date()

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

    # Optional display name shown in the UI (and any future leaderboard)
    # instead of a raw email address. Nullable -- falls back to the part
    # of the email before "@" if not set, so nothing breaks for existing
    # accounts created before this field existed. This is exactly the
    # kind of new-column-on-an-existing-table change that needs the
    # init_db() schema-check to pick it up automatically -- see the
    # comment there and the README for why.
    display_name = Column(String, nullable=True)

    # Paid-tier support: "free" or "paid". Paid users are never limited on
    # anything below. Flipped automatically by Stripe webhooks in
    # stripe_service.py / main.py's /stripe_webhook -- see there for the
    # full subscription lifecycle. Can also still be set manually via the
    # admin tool (e.g. for comping a user), independent of Stripe.
    tier = Column(String, default="free", nullable=False)

    # One-time bonus generations, separate from and consumed BEFORE the
    # daily free-tier cap in usage_limits.py's check_and_increment_usage.
    # Two things feed into this field:
    #   1. Unused anonymous trial credits merged in at signup (see /signup) --
    #      fixes a real gap where authenticating made the anonymous trial
    #      pool permanently unreachable, so someone who signed up before
    #      using their trial lost those credits entirely.
    #   2. Referral bonuses (see referral_count below) -- both sides of a
    #      referral get REFERRAL_BONUS_AMOUNT added here when a new
    #      signup includes a valid ?ref= from an existing user.
    bonus_generations_remaining = Column(Integer, default=0, nullable=False)

    # How many successful referrals this user has been credited for.
    # Capped in usage_limits.py's REFERRAL_MAX_CREDITED_SIGNUPS -- without
    # a cap, referral bonus is a real, unbounded cost exposure (each
    # bonus generation still costs a real Claude API call once spent),
    # the same reasoning that led to capping "unlimited" paid usage
    # earlier. A generous cap doesn't limit genuine sharing; it only
    # bounds the cost of someone deliberately farming fake signups.
    referral_count = Column(Integer, default=0, nullable=False)

    # Login rate limiting: after FAILED_LOGIN_LOCKOUT_THRESHOLD consecutive
    # wrong-password attempts, login_locked_until is set and further
    # attempts are rejected until that time passes, regardless of whether
    # the password given is actually correct -- see /login in main.py.
    # Resets to 0 / None on any successful login. Tracked per-account
    # (not per-IP): IP-based tracking was already rejected elsewhere in
    # this codebase (see usage_limits.py) for the same reasons -- shared
    # IPs, mobile NAT, trivial bypass by switching networks -- and those
    # reasons apply here too. The tradeoff: this weakly leaks account
    # existence (only a real account can ever show lockout behavior,
    # never a made-up email), which is a known, accepted, industry-
    # standard tradeoff for this kind of protection -- see the comment
    # on /login for how the response message is kept as neutral as
    # possible despite this.
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    login_locked_until = Column(DateTime, nullable=True)

    # Stripe's customer object ID for this user. Created lazily on first
    # checkout attempt (see stripe_service.get_or_create_customer) and
    # reused after that -- NOT the same as the subscription ID, since a
    # customer can exist (and be billed) without an active subscription.
    stripe_customer_id = Column(String, nullable=True, index=True)

    # The currently-active subscription ID, if any. Nullable: a "paid"
    # tier set manually via the admin tool has no real Stripe subscription
    # behind it, and a canceled subscription clears this back to None.
    stripe_subscription_id = Column(String, nullable=True, index=True)

    # When the current billing period ends (Unix timestamp, from Stripe's
    # current_period_end), and whether the subscription is set to cancel
    # at that point rather than auto-renew. Together these let the
    # frontend show "your paid access continues until <date>" after a
    # user cancels via the billing portal -- Stripe's default cancel flow
    # doesn't revoke access immediately, it just stops the NEXT renewal,
    # so `tier` correctly stays "paid" through the end of the period; these
    # two fields are what let the UI actually communicate that instead of
    # just silently still saying "paid" with no explanation. Populated by
    # the checkout.session.completed and customer.subscription.updated
    # webhook handlers in main.py; cleared on customer.subscription.deleted.
    subscription_period_end = Column(Integer, nullable=True)
    subscription_cancel_at_period_end = Column(Boolean, nullable=True, default=False)

    # Daily cap for /generate_puzzle specifically (free tier only -- see
    # usage_limits.py). Named "premium_actions" from when this was a
    # single pool shared with reword; kept as-is for schema stability
    # rather than renaming an existing column, but it's generate-only now.
    daily_premium_actions_used = Column(Integer, default=0, nullable=False)
    daily_premium_actions_date = Column(Date, default=_central_today, nullable=False)

    # Separate daily cap for /reword_clue (free tier only). Split out from
    # the generate cap above on purpose: reword has no anonymous-trial
    # access at all (login required), and free accounts get their own
    # independent daily allowance rather than sharing one pool with
    # generation -- see usage_limits.py for the full reasoning.
    daily_reword_used = Column(Integer, default=0, nullable=False)
    daily_reword_date = Column(Date, default=_central_today, nullable=False)

    # Password reset support. We store a HASH of the reset token, never
    # the raw token itself -- same principle as password_hash: if the
    # database were ever exposed, a stored raw token would let an
    # attacker reset anyone's password directly, exactly the outcome
    # this feature exists to prevent. Both nullable -- most users have no
    # active reset request most of the time. See auth.py for token
    # generation/hashing and main.py's /forgot_password and
    # /reset_password endpoints.
    reset_token_hash = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)

    # Email verification. Not enforced as a hard gate on core features (a
    # brand-new user can still generate puzzles immediately -- blocking
    # that would hurt signup conversion for little real benefit). What it
    # DOES gate: referral bonus crediting (see pending_referrer_id below)
    # -- without verification, nothing stops someone from spinning up
    # fake/disposable emails purely to farm referral credits, since the
    # existing REFERRAL_MAX_CREDITED_SIGNUPS cap only limits credits per
    # REFERRER, not per fake new account. Same hash-not-raw-token pattern
    # as reset_token_hash above, and reuses the same auth.py helpers.
    email_verified = Column(Boolean, default=False, nullable=False)
    verification_token_hash = Column(String, nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)

    # Set at signup if a valid ?ref= was present, left un-applied until
    # this account actually verifies its email -- see main.py's /signup
    # and /verify_email for where this gets set and consumed. Cleared
    # back to None once the bonus is actually granted (or if verification
    # never happens, it just... never happens, which is the point).
    pending_referrer_id = Column(Integer, nullable=True)

    # cascade="all, delete-orphan": deleting a User automatically deletes
    # their SolveRecord rows too via the ORM (issues the child DELETEs
    # before the parent DELETE) -- needed for /delete_account to work
    # without leaving orphaned rows or hitting a foreign-key violation,
    # since SolveRecord.user_id is NOT NULL.
    solves = relationship("SolveRecord", back_populates="user", cascade="all, delete-orphan")


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
    daily_actions_date = Column(Date, default=_central_today, nullable=False)


def init_db():
    """Creates tables if they don't already exist, AND adds any columns
    that exist in the Python models but not yet in the actual database --
    a lightweight substitute for a real migration tool (Alembic), which
    would be the correct long-term answer but is more than this project
    needs right now.

    This matters because Base.metadata.create_all() on its own only
    creates MISSING TABLES -- it does not alter a table that already
    exists to add new columns. Every time a column gets added to a model
    (like `tier` on User) after the table was already created in a real
    deployed database, every query touching that table breaks until the
    column is actually added -- this is exactly what caused login to fail
    with "Failed to fetch" after the paid-tier usage-cap columns were
    added to User: the code expected them, the live database didn't have
    them, and the resulting SQL error surfaced as a generic network
    failure in the browser rather than a clear error message.
    """
    from sqlalchemy import inspect, text

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue  # just created above, nothing to add
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue

            col_type = column.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}'

            # If the column is NOT NULL, a table with existing rows needs a
            # database-level DEFAULT to backfill them -- otherwise Postgres
            # rejects the ALTER outright, since existing rows would have no
            # value for a new required column.
            if not column.nullable:
                default_sql = _literal_default_for_column(column)
                if default_sql is not None:
                    ddl += f" NOT NULL DEFAULT {default_sql}"
                else:
                    # No safe literal default available -- add it nullable
                    # rather than fail the whole startup. Application code
                    # (usage_limits.py) should treat a None value the same
                    # as "not set yet" for any column added this way.
                    pass

            with engine.begin() as conn:
                conn.execute(text(ddl))
            print(f"Added missing column: {table.name}.{column.name}")


def _literal_default_for_column(column):
    """Returns a SQL literal to use as a DEFAULT when backfilling a newly
    added NOT NULL column on a table that may already have rows. Only
    handles the simple, static-value cases this project actually uses --
    not a general solution for arbitrary defaults."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        # Dynamic defaults (e.g. lambda: datetime.date.today()) can't be
        # expressed as a fixed literal -- special-case the ones this
        # project uses by column name instead.
        if column.name == "daily_premium_actions_date":
            return "CURRENT_DATE"
        return None

    value = default.arg
    if isinstance(value, str):
        return f"'{value}'"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
