"""
Custom Crosswords Daily — backend API

Endpoints:
  POST /generate_puzzle   { "topic": str, "num_words": int? }
  GET  /on_this_day       ?date=YYYY-MM-DD (optional, defaults to today)

Run locally:
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=sk-ant-...
  uvicorn main:app --reload
"""
import sys
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/home/claude/backend")
from compact_lib import compact_search
from claude_wordbank import generate_word_bank
from historical_events import get_events_for_date
from hints import get_hint, VALID_TIERS

app = FastAPI(title="Custom Crosswords Daily API")

# Allows the prototype HTML file (opened directly as file://, or served from
# a different origin/port during development) to call this API from the
# browser. Tighten this to your actual frontend's origin before shipping to
# real users -- "*" is fine for local development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for solve-time submissions. NOT a real database -- resets
# every time the server restarts. This is here to prove the shape of the
# feature (recording solve time + hints used per topic) so it can be swapped
# for a real DB once accounts exist. See README for the honest scope note.
_solve_log = []


class TopicRequest(BaseModel):
    topic: str
    num_words: int = 13


class HintRequest(BaseModel):
    word: str
    clue: str
    hint: str = ""
    tier: int


class SolveSubmission(BaseModel):
    topic: str
    solve_time_seconds: float
    hints_used: int = 0
    completed: bool = True


def build_puzzle_response(entries, hints=None, seed_base=1):
    """Runs a list of (WORD, clue) tuples through the real compaction-search
    generator and returns the same JSON shape used across the whole book
    pipeline: {grid_w, grid_h, grid, placed}, with each placed word also
    carrying its "hint" field merged in from the side-channel `hints` dict."""
    gen = compact_search(entries, seed_base, tries_per_seed=25, n_seeds=20)
    if gen is None:
        raise HTTPException(
            status_code=422,
            detail="Could not place a valid crossword grid from this word bank "
                   "(words may not share enough letters to interlock). Try a "
                   "broader topic or fewer words.",
        )
    hints = hints or {}
    placed = []
    for p in gen.placed:
        p = dict(p)
        p["hint"] = hints.get(p["word"], p["clue"])
        placed.append(p)

    return {
        "grid_w": gen.n_cols,
        "grid_h": gen.n_rows,
        "grid": {f"{r},{c}": ch for (r, c), ch in gen.grid.items()},
        "placed": placed,
        "unplaced_words": gen.unplaced,
    }


@app.post("/generate_puzzle")
def generate_puzzle(req: TopicRequest):
    if not req.topic or not req.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    if not (5 <= req.num_words <= 20):
        raise HTTPException(status_code=400, detail="num_words must be between 5 and 20.")

    try:
        entries, hints = generate_word_bank(req.topic.strip(), n_words=req.num_words)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = build_puzzle_response(entries, hints=hints, seed_base=abs(hash(req.topic)) % 10000)
    result["topic"] = req.topic
    result["word_bank_used"] = [{"word": w, "clue": c, "hint": hints.get(w, c)} for w, c in entries]
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
    hints = {evt["word"]: evt.get("hint", evt["clue"]) for evt in events}
    result = build_puzzle_response(entries, hints=hints, seed_base=target_date.toordinal())
    result["date"] = target_date.isoformat()
    return result


@app.post("/hint")
def hint(req: HintRequest):
    if req.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier must be one of {VALID_TIERS}")
    return get_hint(req.word, req.clue, req.hint, req.tier)


@app.post("/submit_solve")
def submit_solve(req: SolveSubmission):
    """Records a completed (or abandoned) solve attempt: topic, time taken,
    hints used. This is the raw data a future adaptive-difficulty engine
    would train on -- this endpoint only logs it in memory for now, it does
    not yet adjust anything. Meaningful adaptive difficulty needs accounts
    (to track a given player over time) which isn't built yet -- see README."""
    entry = req.model_dump()
    entry["logged_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _solve_log.append(entry)

    same_topic = [s for s in _solve_log if s["topic"] == req.topic]
    avg_time = sum(s["solve_time_seconds"] for s in same_topic) / len(same_topic)

    return {
        "recorded": True,
        "topic_attempts_logged_this_session": len(same_topic),
        "average_solve_time_seconds_this_topic": round(avg_time, 1),
    }


@app.get("/health")
def health():
    return {"status": "ok"}
