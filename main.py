"""
TopiCross — backend API

Endpoints:
  POST /signup             { "email": str, "password": str }
  POST /login               { "email": str, "password": str }
  POST /generate_puzzle    { "topic": str, "num_words": int?, "difficulty": str? }
  GET  /on_this_day        ?date=YYYY-MM-DD (optional, defaults to today)
  POST /submit_solve       (requires auth) logs a per-user solve record
  GET  /recommend_difficulty?topic=...  (requires auth) per-user recommendation
  GET  /me                  (requires auth) current user's tier/subscription status
  POST /create_checkout_session  (requires auth) starts a Stripe subscription checkout
  POST /billing_portal      (requires auth) Stripe billing portal (manage/cancel)
  POST /stripe_webhook      Stripe -> us: subscription lifecycle events (not user-facing)

Run locally:
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=sk-ant-...
  export JWT_SECRET_KEY=some-long-random-string
  export DATABASE_URL=postgresql://...   (see README -- required for real persistence)
  uvicorn main:app --reload
"""
import os
import hmac
import traceback
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
import jwt as pyjwt
import stripe

from compact_lib import compact_search
from claude_wordbank import generate_word_bank
from historical_events import get_events_for_date
from hints import get_hint, VALID_TIERS
from topic_recommender import recommend_topics
from clue_rewriter import reword_clue
from email_service import send_reset_email
import stripe_service
from usage_limits import (
    check_and_increment_usage, check_and_increment_reword_usage,
    check_and_increment_anonymous_usage, UsageLimitExceeded,
)
from stats import build_stats
import auth
import database
from database import get_db, User, SolveRecord, AnonymousUsage

app = FastAPI(title="TopiCross API")

app.add_middleware(
    CORSMiddleware,
    # Allows both the old GitHub Pages origin and the new custom domain
    # during the DNS transition -- once topicross.app is confirmed fully
    # live and propagated, the github.io entry can be removed.
    allow_origins=[
        "https://dylanjcox1999-creator.github.io",
        "https://topicross.app",
        "https://www.topicross.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer_scheme = HTTPBearer(auto_error=False)


@app.on_event("startup")
def on_startup():
    database.init_db()


class TopicRequest(BaseModel):
    topic: str
    num_words: int = 13
    difficulty: str = "medium"  # "easy" | "medium" | "hard"


class HintRequest(BaseModel):
    word: str
    tier: int


class RewordRequest(BaseModel):
    word: str
    clue: str


class SolveSubmission(BaseModel):
    topic: str
    difficulty: str = "medium"
    solve_time_seconds: float
    hints_used: int = 0
    completed: bool = True


class SignupRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UpdateDisplayNameRequest(BaseModel):
    display_name: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str


class SetTierRequest(BaseModel):
    email: str
    tier: str  # "free" | "paid"


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: validates the Authorization: Bearer <token> header
    and returns the corresponding User, or raises 401."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    try:
        payload = auth.decode_access_token(creds.credentials)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again.")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")

    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return user


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Same idea as get_current_user, but returns None instead of raising
    when there's no token -- used by endpoints that accept EITHER a logged
    -in user OR an anonymous trial ID (/generate_puzzle, /reword_clue)."""
    if creds is None:
        return None
    try:
        payload = auth.decode_access_token(creds.credentials)
    except pyjwt.InvalidTokenError:
        return None
    return db.query(User).filter(User.id == int(payload["sub"])).first()


def get_or_create_anonymous_usage(anon_id: str, db: Session) -> AnonymousUsage:
    row = db.query(AnonymousUsage).filter(AnonymousUsage.anon_id == anon_id).first()
    if row is None:
        row = AnonymousUsage(anon_id=anon_id)
        db.add(row)
    return row


def build_puzzle_response(entries, seed_base=1):
    """Runs a list of (WORD, clue) tuples through the real compaction-search
    generator and returns the same JSON shape used across the whole book
    pipeline: {grid_w, grid_h, grid, placed}."""
    gen = compact_search(entries, seed_base, tries_per_seed=25, n_seeds=20)
    if gen is None:
        raise HTTPException(
            status_code=422,
            detail="Could not place a valid crossword grid from this word bank "
                   "(words may not share enough letters to interlock). Try a "
                   "broader topic or fewer words.",
        )
    return {
        "grid_w": gen.n_cols,
        "grid_h": gen.n_rows,
        "grid": {f"{r},{c}": ch for (r, c), ch in gen.grid.items()},
        "placed": gen.placed,
        "unplaced_words": gen.unplaced,
    }


# ---------------- Accounts ----------------

def _effective_display_name(user: User) -> str:
    """Returns the user's set display name, or a fallback derived from
    their email (the part before "@") if they haven't set one. Used
    anywhere a name needs to be shown -- keeps a raw email address from
    ever being the only thing displayed in the UI."""
    if user.display_name and user.display_name.strip():
        return user.display_name.strip()
    return user.email.split("@")[0]


@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    display_name = req.display_name.strip() if req.display_name else None
    if display_name and (len(display_name) < 2 or len(display_name) > 30):
        raise HTTPException(status_code=400, detail="Display name must be 2-30 characters.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(email=email, password_hash=auth.hash_password(req.password), display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = auth.create_access_token(user_id=user.id, email=user.email)
    return {
        "access_token": token, "token_type": "bearer",
        "email": user.email, "display_name": _effective_display_name(user),
        "tier": user.tier,
    }


@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not auth.verify_password(req.password, user.password_hash):
        # Deliberately the same error for "no such user" and "wrong password"
        # -- don't leak which emails have accounts.
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = auth.create_access_token(user_id=user.id, email=user.email)
    return {
        "access_token": token, "token_type": "bearer",
        "email": user.email, "display_name": _effective_display_name(user),
        "tier": user.tier,
    }


@app.post("/update_display_name")
def update_display_name(
    req: UpdateDisplayNameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = req.display_name.strip()
    if len(name) < 2 or len(name) > 30:
        raise HTTPException(status_code=400, detail="Display name must be 2-30 characters.")
    current_user.display_name = name
    db.add(current_user)
    db.commit()
    return {"display_name": _effective_display_name(current_user)}


# The page a reset-password link points users back to. Configurable via
# environment variable -- defaults to the new custom domain now that
# topicross.app is set up, but keep this overridable in Render's
# Environment tab in case the domain isn't fully propagated yet when this
# deploys (set FRONTEND_URL there temporarily back to the github.io URL
# if reset links break before DNS finishes propagating).
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL",
    "https://topicross.app/",
)


@app.post("/forgot_password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Starts a password reset. Always returns the same generic message
    whether or not the email has an account -- same principle as /login's
    error message: don't leak which emails have accounts to someone
    probing this endpoint.

    Sends the reset link via Resend using RESEND_API_KEY /
    RESEND_FROM_ADDRESS (see email_service.py). Falls back to
    log-only mode only if RESEND_API_KEY isn't set."""
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user is not None:
        raw_token, token_hash = auth.generate_reset_token()
        user.reset_token_hash = token_hash
        user.reset_token_expires = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(minutes=auth.RESET_TOKEN_EXPIRY_MINUTES)
        db.add(user)
        db.commit()

        reset_link = f"{FRONTEND_URL}?reset_token={raw_token}"
        try:
            send_reset_email(user.email, reset_link)
        except Exception as e:
            # A real send can fail (e.g. Resend rejects it with a 403
            # because no domain is verified and the recipient isn't the
            # account owner -- see email_service.py). Log it server-side
            # for whoever's watching, but don't let it 500 the request or
            # change the generic response below -- that response's whole
            # point is staying identical whether or not the email exists,
            # and it shouldn't also leak "the email attempt failed" to
            # whoever's calling this endpoint.
            print(f"[forgot_password] send_reset_email failed for {user.email}: {e}")

    return {
        "message": "If an account with that email exists, a password reset link has been sent."
    }


@app.post("/reset_password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    token_hash = auth.hash_reset_token(req.token)
    user = db.query(User).filter(User.reset_token_hash == token_hash).first()

    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    if user.reset_token_expires is None or datetime.datetime.now(datetime.timezone.utc) > user.reset_token_expires:
        raise HTTPException(
            status_code=400, detail="This reset link has expired. Please request a new one."
        )

    user.password_hash = auth.hash_password(req.new_password)
    # Single-use: clear the token immediately so this same link can't be
    # replayed to reset the password again.
    user.reset_token_hash = None
    user.reset_token_expires = None
    db.add(user)
    db.commit()
    return {"message": "Password successfully reset. You can now log in with your new password."}


@app.post("/delete_account")
def delete_account(
    req: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently deletes the logged-in user's account and all their
    solve history. Requires re-entering the password (not just a valid
    session token) as a deliberate speed bump against a stolen/leaked
    token alone being enough to destroy an account -- same reasoning as
    requiring a password to change one. Cascades to delete SolveRecord
    rows too, via the relationship's cascade config in database.py."""
    if not auth.verify_password(req.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    # Cancel any active Stripe subscription FIRST -- otherwise deleting
    # the user row orphans a live subscription that keeps billing the
    # user's card with no account left to apply the eventual webhook to.
    # Best-effort: log and continue with deletion even if this fails
    # (e.g. Stripe not configured, or already canceled), since a failed
    # cancellation shouldn't block the user's right to delete their
    # account -- but it does mean this needs to be visible in logs so
    # it can be handled manually if it ever happens.
    if current_user.stripe_subscription_id:
        try:
            stripe_service.cancel_subscription(current_user.stripe_subscription_id)
        except Exception as e:
            print(
                f"[delete_account] Failed to cancel Stripe subscription "
                f"{current_user.stripe_subscription_id} for user {current_user.email}: {e}"
            )

    db.delete(current_user)
    db.commit()
    return {"deleted": True}


# ---------------- Admin (testing only) ----------------
# Manually flips a user's tier for testing the paid-tier logic before any
# real billing integration exists. Protected by ADMIN_SECRET_KEY, a
# separate environment variable from JWT_SECRET_KEY/ANTHROPIC_API_KEY --
# set it in Render's Environment tab, and send it back as the X-Admin-Key
# header on this request. If ADMIN_SECRET_KEY isn't set, this endpoint
# refuses to run at all rather than silently having no protection.
#
# IMPORTANT: this is a stand-in for real billing, not a permanent feature.
# Anyone with the admin key can grant themselves (or anyone) paid access
# for free -- that's fine while you're the only person testing this, but
# this endpoint should be removed or replaced with real Stripe webhook
# handling before this app has real, non-you users.

@app.post("/admin/set_tier")
def admin_set_tier(
    req: SetTierRequest,
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    admin_secret = os.environ.get("ADMIN_SECRET_KEY")
    if not admin_secret:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoint not configured -- set ADMIN_SECRET_KEY in your environment.",
        )
    # Constant-time comparison -- same reasoning as password verification
    # in auth.py, avoids leaking timing information about the correct key.
    if not x_admin_key or not hmac.compare_digest(x_admin_key, admin_secret):
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Key header.")

    if req.tier not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="tier must be 'free' or 'paid'.")

    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=404, detail=f"No account found for {email}.")

    user.tier = req.tier
    db.add(user)
    db.commit()
    return {"email": user.email, "tier": user.tier, "updated": True}


# ---------------- Billing (Stripe) ----------------
# Real payment integration: recurring subscription via Stripe Checkout.
# Card details never touch this backend or the frontend -- both checkout
# and billing management happen on Stripe-hosted pages. This backend only
# ever sees Stripe's webhook events telling it what happened, and flips
# User.tier accordingly. See stripe_service.py's module docstring for the
# one-time Stripe Dashboard setup this depends on.

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """Lightweight endpoint for the frontend to check the logged-in
    user's current tier (e.g. right after redirecting back from Stripe
    Checkout, to see whether the webhook has flipped it yet)."""
    return {
        "email": current_user.email,
        "display_name": _effective_display_name(current_user),
        "tier": current_user.tier,
        "has_active_subscription": current_user.stripe_subscription_id is not None,
    }


@app.post("/create_checkout_session")
def create_checkout_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tier == "paid" and current_user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="You already have an active subscription. Use the billing portal to manage it.",
        )
    try:
        url = stripe_service.create_checkout_session(current_user, db, FRONTEND_URL)
    except RuntimeError as e:
        # Not-yet-configured (missing env vars) -- a real setup problem,
        # not a user-facing payment failure, so it gets a 503 rather than
        # looking like something the user did wrong.
        raise HTTPException(status_code=503, detail=str(e))
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e.user_message or str(e)}")
    return {"checkout_url": url}


@app.post("/billing_portal")
def billing_portal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        url = stripe_service.create_billing_portal_session(current_user, FRONTEND_URL)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e.user_message or str(e)}")
    return {"portal_url": url}


@app.post("/stripe_webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Receives events from Stripe and updates User.tier accordingly.
    This is the SOURCE OF TRUTH for who's paid -- not the Checkout
    redirect, which only tells the browser the payment page closed, not
    that the payment actually succeeded.

    Must read the raw request body (not parsed JSON) for signature
    verification -- Stripe signs the exact bytes it sent, so re-
    serializing a parsed body would break verification.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe_service.verify_webhook(payload, sig_header)
    except RuntimeError as e:
        # Not configured -- surfaces clearly in logs rather than a
        # generic 500, same reasoning as the other RuntimeErrors above.
        raise HTTPException(status_code=503, detail=str(e))
    except stripe.error.SignatureVerificationError:
        # Deliberately a 400, not swallowed -- an unverifiable webhook
        # should be visible in logs (could be a misconfigured secret,
        # or someone probing this endpoint), not silently ignored.
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

    event_type = event["type"]
    data = event["data"]["object"]

    # Everything below was previously unguarded -- any exception in here
    # (bad data shape, a DB error, anything) propagated up as a bare 500
    # with NOTHING useful in the logs beyond "500 happened". Wrapping it
    # means a failure is actually diagnosable next time instead of a
    # dead end. Still re-raises as a 500 afterward (not swallowed) so
    # Stripe's automatic retry logic still kicks in -- this only adds
    # visibility, it doesn't change whether Stripe considers this a
    # failed delivery.
    try:
        if event_type == "checkout.session.completed":
            # A subscription checkout just finished successfully. The
            # subscription ID is on the session for subscription-mode
            # checkouts. Look the user up by client_reference_id (set to
            # our own user.id when the session was created) rather than by
            # email, since that's an unambiguous, unspoofable link back to
            # exactly the user who started this checkout.
            user_id = data.get("client_reference_id")
            subscription_id = data.get("subscription")
            if user_id:
                user = db.query(User).filter(User.id == int(user_id)).first()
                if user:
                    user.tier = "paid"
                    user.stripe_subscription_id = subscription_id
                    db.add(user)
                    db.commit()

        elif event_type == "customer.subscription.updated":
            # Covers e.g. a past-due subscription recovering after a retried
            # payment, or a plan change. "active" and "trialing" both count
            # as paid access; anything else (past_due, unpaid, incomplete,
            # incomplete_expired) does not.
            customer_id = data.get("customer")
            status = data.get("status")
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.tier = "paid" if status in ("active", "trialing") else "free"
                db.add(user)
                db.commit()

        elif event_type == "customer.subscription.deleted":
            # Subscription fully canceled (not just past-due) -- revoke
            # paid access and clear the subscription ID so a future
            # checkout doesn't get blocked by the "already subscribed"
            # check in /create_checkout_session above.
            customer_id = data.get("customer")
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.tier = "free"
                user.stripe_subscription_id = None
                db.add(user)
                db.commit()

        elif event_type == "invoice.payment_failed":
            # Don't immediately revoke access on the FIRST failed payment --
            # Stripe automatically retries a few times over about two weeks
            # (Smart Retries) before giving up, and customer.subscription.
            # updated will fire with status="past_due" or eventually
            # "unpaid"/"canceled" if all retries fail, which the handler
            # above already covers. Immediately cutting access on the first
            # failure would punish a user for a temporarily-declined card
            # that recovers on retry. This branch exists mainly so the event
            # type is acknowledged (200) rather than landing in Stripe's
            # dashboard as an unhandled event; log it for visibility.
            print(f"[stripe_webhook] invoice.payment_failed for customer {data.get('customer')}")

    except Exception as e:
        db.rollback()
        traceback.print_exc()
        print(f"[stripe_webhook] Unhandled error processing {event_type} (event {event.get('id')}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error processing {event_type} -- see server logs.",
        )

    return {"received": True}


# ---------------- Puzzles ----------------
# /generate_puzzle and /reword_clue accept EITHER a logged-in user
# (Authorization: Bearer <token>, 3/day) OR an anonymous trial ID
# (X-Anonymous-Id header, 1/day) -- see usage_limits.py for why this isn't
# IP-based. Exactly one of the two is required; anonymous IDs are
# generated and stored client-side in localStorage, not tied to any
# personal info.

def _check_usage_for_request(
    current_user: Optional[User], anon_id: Optional[str], db: Session
) -> int:
    """Shared by /generate_puzzle and /reword_clue. Returns the remaining
    action count to surface to the frontend, or raises HTTPException on
    missing identity or a hit usage cap."""
    if current_user is not None:
        try:
            return check_and_increment_usage(current_user)
        except UsageLimitExceeded as e:
            raise HTTPException(status_code=429, detail=str(e))

    if anon_id:
        anon_usage = get_or_create_anonymous_usage(anon_id, db)
        try:
            return check_and_increment_anonymous_usage(anon_usage)
        except UsageLimitExceeded as e:
            raise HTTPException(status_code=429, detail=str(e))

    raise HTTPException(
        status_code=401,
        detail="Log in, or provide an X-Anonymous-Id header to use your free trial generation.",
    )


@app.post("/generate_puzzle")
def generate_puzzle(
    req: TopicRequest,
    current_user: Optional[User] = Depends(get_current_user_optional),
    x_anonymous_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if not req.topic or not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    if not (5 <= req.num_words <= 20):
        raise HTTPException(status_code=400, detail="num_words must be between 5 and 20.")

    remaining = _check_usage_for_request(current_user, x_anonymous_id, db)

    try:
        entries = generate_word_bank(
            req.topic.strip(), n_words=req.num_words, difficulty=req.difficulty
        )
        result = build_puzzle_response(entries, seed_base=abs(hash(req.topic)) % 10000)
    except (ValueError, HTTPException) as e:
        # Generation can fail at TWO separate stages: Claude's word bank
        # (ValueError) or grid placement afterward (build_puzzle_response
        # raises HTTPException if the words won't interlock into a valid
        # grid). Either way, don't charge the daily/lifetime quota for an
        # attempt that produced no usable puzzle -- roll back the
        # increment before it commits. This fixes a real bug: previously
        # only the word-bank failure was caught here, so a grid-placement
        # failure would silently consume a trial/daily use while handing
        # back nothing -- exactly what made an anonymous 3-try trial
        # sometimes only yield 2 real puzzles.
        db.rollback()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=422, detail=str(e))

    db.commit()

    result["topic"] = req.topic
    result["difficulty"] = req.difficulty
    result["word_bank_used"] = [{"word": w, "clue": c} for w, c in entries]
    result["daily_actions_remaining"] = remaining
    return result


@app.get("/on_this_day")
def on_this_day(date: Optional[str] = None):
    if date:
        try:
            target_date = datetime.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        target_date = datetime.date.today()

    events = get_events_for_date(target_date)
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"No historical events available for {target_date.isoformat()}.",
        )

    entries = [(evt["word"], evt["clue"]) for evt in events]
    result = build_puzzle_response(entries, seed_base=target_date.toordinal())
    result["date"] = target_date.isoformat()
    return result


@app.post("/hint")
def hint(req: HintRequest):
    if req.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier must be one of {VALID_TIERS}")
    return get_hint(req.word, req.tier)


@app.post("/reword_clue")
def reword(
    req: RewordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rewrites a clue in plainer language, without changing how hard the
    puzzle is to solve. Requires login -- unlike /generate_puzzle, there
    is NO anonymous trial access to this endpoint at all. Free accounts
    get their own separate daily pool (independent of /generate_puzzle's
    cap), and paid accounts are unlimited. See usage_limits.py for the
    full reasoning, and clue_rewriter.py for the accessibility rationale
    behind the feature itself."""
    if not req.word or not req.clue:
        raise HTTPException(status_code=400, detail="word and clue are both required.")

    try:
        remaining = check_and_increment_reword_usage(current_user)
    except UsageLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    result = reword_clue(req.word, req.clue)

    db.add(current_user)
    db.commit()
    result["daily_actions_remaining"] = remaining
    return result


# ---------------- Progress tracking (login required) ----------------

@app.post("/submit_solve")
def submit_solve(
    req: SolveSubmission,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Records a completed (or abandoned) solve attempt against the logged-in
    user's account -- this is now real, personal history, not a shared
    in-memory list. Persists as long as DATABASE_URL points at a real
    hosted Postgres instance (see README)."""
    record = SolveRecord(
        user_id=current_user.id,
        topic=req.topic,
        difficulty=req.difficulty,
        solve_time_seconds=req.solve_time_seconds,
        hints_used=req.hints_used,
        completed=req.completed,
    )
    db.add(record)
    db.commit()

    same_topic = (
        db.query(SolveRecord)
        .filter(SolveRecord.user_id == current_user.id, SolveRecord.topic == req.topic)
        .all()
    )
    avg_time = sum(s.solve_time_seconds for s in same_topic) / len(same_topic)

    return {
        "recorded": True,
        "topic_attempts_logged": len(same_topic),
        "average_solve_time_seconds_this_topic": round(avg_time, 1),
    }


@app.get("/recommend_difficulty")
def recommend_difficulty(
    topic: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recommends a difficulty level for `topic` based on THIS user's own
    solve history -- genuinely personalized now that accounts exist, not
    the aggregate-across-everyone placeholder from before."""
    same_topic = (
        db.query(SolveRecord)
        .filter(SolveRecord.user_id == current_user.id, SolveRecord.topic == topic)
        .all()
    )
    if len(same_topic) < 2:
        return {
            "topic": topic,
            "recommended_difficulty": "medium",
            "reason": "Not enough solve history for this topic yet (need at least 2 attempts) -- defaulting to medium.",
            "attempts_considered": len(same_topic),
        }

    avg_hints = sum(s.hints_used for s in same_topic) / len(same_topic)
    avg_time = sum(s.solve_time_seconds for s in same_topic) / len(same_topic)
    completion_rate = sum(1 for s in same_topic if s.completed) / len(same_topic)

    if avg_hints < 0.5 and completion_rate >= 0.8:
        recommendation = "hard"
        reason = f"Low hint usage (avg {avg_hints:.1f}) and a high completion rate ({completion_rate:.0%}) suggest this topic is too easy for you at the current level."
    elif avg_hints > 1.5 or completion_rate < 0.5:
        recommendation = "easy"
        reason = f"High hint usage (avg {avg_hints:.1f}) or a low completion rate ({completion_rate:.0%}) suggest this topic is currently too hard for you."
    else:
        recommendation = "medium"
        reason = f"Your hint usage (avg {avg_hints:.1f}) and completion rate ({completion_rate:.0%}) both look reasonable at the current level."

    return {
        "topic": topic,
        "recommended_difficulty": recommendation,
        "reason": reason,
        "attempts_considered": len(same_topic),
        "stats": {
            "average_hints_used": round(avg_hints, 2),
            "average_solve_time_seconds": round(avg_time, 1),
            "completion_rate": round(completion_rate, 2),
        },
    }


@app.get("/recommend_topics")
def get_recommend_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Suggests new topics based on the logged-in user's own play history.
    Always returns something usable -- falls back to a diverse starter set
    for new users or if the live recommendation call fails, rather than
    ever erroring out on this endpoint."""
    records = (
        db.query(SolveRecord)
        .filter(SolveRecord.user_id == current_user.id)
        .all()
    )
    # One representative entry per topic (most recent attempt), not one
    # entry per solve -- a topic played 5 times shouldn't just dominate
    # the history by volume.
    by_topic = {}
    for r in records:
        by_topic[r.topic] = {
            "topic": r.topic,
            "hints_used": r.hints_used,
            "completed": r.completed,
        }
    history = list(by_topic.values())

    topics = recommend_topics(history, n=5)
    return {
        "suggested_topics": topics,
        "based_on_history": len(history) > 0,
        "topics_considered": len(history),
    }


@app.get("/stats")
def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paid-tier stats dashboard: totals, averages, favorite topics,
    difficulty breakdown, fastest solve, and solve streaks. See stats.py
    for the actual computation, kept database-free and fully offline
    -testable on purpose -- this endpoint just fetches the records and
    hands them off as plain dicts."""
    if current_user.tier != "paid":
        raise HTTPException(
            status_code=403,
            detail="The stats dashboard is a paid feature. Upgrade to see your "
                   "solve history, favorite topics, and streaks.",
        )

    records = db.query(SolveRecord).filter(SolveRecord.user_id == current_user.id).all()
    record_dicts = [
        {
            "topic": r.topic,
            "difficulty": r.difficulty,
            "solve_time_seconds": r.solve_time_seconds,
            "hints_used": r.hints_used,
            "completed": r.completed,
            "logged_at": r.logged_at,
        }
        for r in records
    ]
    return build_stats(record_dicts)


@app.get("/health")
def health():
    return {"status": "ok"}
