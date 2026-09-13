"""
Custom Crosswords Daily — backend API

Endpoints:
  POST /signup             { "email": str, "password": str }
  POST /login               { "email": str, "password": str }
  POST /generate_puzzle    { "topic": str, "num_words": int?, "difficulty": str? }
  GET  /on_this_day        ?date=YYYY-MM-DD (optional, defaults to today)
  POST /submit_solve       (requires auth) logs a per-user solve record
  GET  /recommend_difficulty?topic=...  (requires auth) per-user recommendation

Run locally:
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=sk-ant-...
  export JWT_SECRET_KEY=some-long-random-string
  export DATABASE_URL=postgresql://...   (see README -- required for real persistence)
  uvicorn main:app --reload
"""
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
import jwt as pyjwt

from compact_lib import compact_search
from claude_wordbank import generate_word_bank
from historical_events import get_events_for_date
from hints import get_hint, VALID_TIERS
from topic_recommender import recommend_topics
from clue_rewriter import reword_clue
from usage_limits import check_and_increment_usage, check_and_increment_anonymous_usage, UsageLimitExceeded
import auth
import database
from database import get_db, User, SolveRecord, AnonymousUsage

app = FastAPI(title="Custom Crosswords Daily API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dylanjcox1999-creator.github.io"],
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


class LoginRequest(BaseModel):
    email: str
    password: str


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

@app.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(email=email, password_hash=auth.hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = auth.create_access_token(user_id=user.id, email=user.email)
    return {"access_token": token, "token_type": "bearer", "email": user.email}


@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not auth.verify_password(req.password, user.password_hash):
        # Deliberately the same error for "no such user" and "wrong password"
        # -- don't leak which emails have accounts.
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = auth.create_access_token(user_id=user.id, email=user.email)
    return {"access_token": token, "token_type": "bearer", "email": user.email}


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
    except ValueError as e:
        # Generation failed -- don't charge the daily quota for a failed
        # attempt that wasn't the caller's fault (a malformed Claude
        # response, for example). Roll back the increment before it commits.
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))

    db.commit()

    result = build_puzzle_response(entries, seed_base=abs(hash(req.topic)) % 10000)
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
    current_user: Optional[User] = Depends(get_current_user_optional),
    x_anonymous_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Rewrites a clue in plainer language, without changing how hard the
    puzzle is to solve. Accepts either a logged-in user or an anonymous
    trial ID, sharing the same daily cap as /generate_puzzle -- both are
    metered together as "premium actions" since both cost a real Claude
    API call. See clue_rewriter.py for the accessibility rationale and why
    this is kept separate from the hint tiers rather than merged into them."""
    if not req.word or not req.clue:
        raise HTTPException(status_code=400, detail="word and clue are both required.")

    remaining = _check_usage_for_request(current_user, x_anonymous_id, db)

    result = reword_clue(req.word, req.clue)

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


@app.get("/health")
def health():
    return {"status": "ok"}
