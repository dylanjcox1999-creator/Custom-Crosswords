# Custom Crosswords Daily — Backend

Real backend API: Claude generates a topical word bank on request, then your
actual crossword generator (`generator2.py` + `compact_lib.py`, the same
engine used to build every book in this series) places it into a grid.
No more JS approximation — this is the real thing.

## Setup

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn main:app --reload
```

Then it's running at `http://localhost:8000`.

## Endpoints

### `POST /generate_puzzle`
```
{"topic": "lighthouses", "num_words": 13}
```
Calls Claude to write a word bank for the topic, then runs it through the
real generator. Returns the same JSON shape used throughout the book
pipeline: `grid_w`, `grid_h`, `grid`, `placed` (each entry has word, clue,
row, col, dir, num).

### `GET /on_this_day?date=2026-09-10`
Same output shape. `date` is optional and defaults to today. Pulls from
`historical_events.py`.

### `POST /hint`
```
{"word": "BEACON", "clue": "...", "hint": "...", "tier": 1}
```
Returns `{"tier": 1, "text": "...", "is_reveal": false}`. The prototype HTML
file calls this live when a player taps the hint button, falling back to
identical local logic if the backend isn't reachable.

### `POST /submit_solve`
```
{"topic": "lighthouses", "solve_time_seconds": 145.2, "hints_used": 1, "completed": true}
```
Logs the attempt in memory and returns a running average for that topic.
The prototype calls this automatically the moment a puzzle is fully solved.

### `GET /health`
Returns `{"status": "ok"}` — the prototype HTML pings this on load to decide
whether to show "Backend: connected" or fall back to local computation.

## Connecting the prototype HTML to this backend

`custom_crosswords_daily.html` now has a real `fetch()`-based integration,
not just a placeholder. Open `main.py`'s CORS settings before relying on
this beyond local testing -- `allow_origins=["*"]` is set for convenience
during development and should be locked down to your actual frontend's
origin before this touches real users.

To test the live connection yourself:
1. `uvicorn main:app --reload` (with `ANTHROPIC_API_KEY` set)
2. Open `custom_crosswords_daily.html` in a browser
3. Within ~2 seconds the "Backend: checking..." indicator should flip to
   "Backend: connected" -- if it stays on "not running", check the browser
   console for the actual fetch error (most likely CORS or the server not
   being up on port 8000)

## What's been tested, and how

I don't have live internet access in the sandbox I built this in, so I
could not call the real Claude API or install `fastapi`/`uvicorn` there to
launch an actual HTTP server. Here's exactly what was and wasn't verified
before this was handed to you:

**Verified, offline, using the real generator:**
- `/on_this_day` full pipeline: real Sept 10 historical data → real
  `compact_search()` → placed 9 of 9 words into an 11x11 grid
- `/generate_puzzle` downstream pipeline: a simulated Claude response (10
  words/clues about lighthouses) → real `compact_search()` → placed 10 of
  10 words into a 9x13 grid with correct across/down numbering
- All three Python files compile with no syntax errors

**Not yet verified — needs to happen in your environment:**
- The actual live call to the Claude API in `claude_wordbank.py` (network
  access, your API key, and Claude's real output format all need
  confirming together)
- Running the FastAPI server itself end-to-end (`uvicorn main:app`) and
  hitting it over HTTP
- Claude occasionally returning malformed JSON or fewer than the requested
  word count — `claude_wordbank.py` has basic retry-worthy validation
  (drops bad entries, raises a clear error if fewer than 5 remain), but
  this hasn't been stress-tested against real model output yet

**A known real limitation, not a bug:**
`historical_events.py` only has verified data for one sample date
(September 10). It's built as a clean, swappable function
(`get_events_for_date`) specifically so you can wire in a real source —
Wikipedia's "On this day" API is a reasonable free starting point — without
touching anything else. Do not fill this out using an LLM with no grounding
source; historical dates are exactly the kind of content where a model can
generate confident, plausible, wrong answers.

## Suggested next steps
1. Run this locally, confirm the live Claude call actually behaves like the
   mocked test did
2. Wire `historical_events.py` to a real data source
3. Add basic caching (today's `/on_this_day` puzzle should generate once and
   be served to everyone, not regenerated per request)
4. From here, the earlier product plan's remaining pieces — adaptive
   difficulty, the tiered hint system, accounts — sit on top of this API
   rather than inside it
