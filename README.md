# Custom Crosswords Daily — Backend

Real backend API: Claude generates a topical word bank on request, then your
actual crossword generator (`generator2.py` + `compact_lib.py`, the same
engine used to build every book in this series) places it into a grid.
Accounts, solve-history tracking, and personalized difficulty recommendations
are now real, backed by a real database -- not the in-memory placeholder used
earlier in this project.

## Setup

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export JWT_SECRET_KEY=<a long random string -- see below>
export DATABASE_URL=postgresql://...   (see "Database" section below -- required)
uvicorn main:app --reload
```

### Generating a JWT_SECRET_KEY
Any long random string works. One easy way:
```
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Set this in your environment (or Render's "Environment" tab). **If it's not
set, the app will still run using a randomly generated key, but every
restart invalidates all existing logins** -- fine for quick local testing,
not acceptable for anything real.

## Database -- read this before deploying

**Render's free web service tier has an ephemeral filesystem.** Any local
file (including a SQLite database file) gets wiped every time the service
redeploys or spins down from inactivity. This means accounts and solve
history would silently reset, over and over, if the database lived on
Render's own free compute.

**The fix: use a real hosted Postgres database, separate from Render's web
service.** Two options with genuinely permanent free tiers:
- **Supabase** (supabase.com) -- free Postgres, doesn't expire
- **Neon** (neon.tech) -- free serverless Postgres, doesn't expire

(Render also offers its own free Postgres, but that free tier **expires
after 30 days** -- fine for a demo, not for anything you want to keep
working.)

Whichever you pick, copy its connection string and set it as `DATABASE_URL`
in Render's Environment tab. The code expects a standard
`postgresql://user:pass@host:port/dbname` URL -- both Supabase and Neon give
you exactly that from their dashboard.

If `DATABASE_URL` isn't set at all, the app falls back to a local SQLite
file (`local_dev.db`) so you can still run and test everything on your own
machine -- just don't rely on that fallback once it's deployed anywhere with
an ephemeral filesystem.

## Endpoints

### `POST /signup`
```
{"email": "you@example.com", "password": "at least 8 characters"}
```
Creates an account, returns `{"access_token": "...", "token_type": "bearer"}`.

### `POST /login`
```
{"email": "you@example.com", "password": "..."}
```
Same response shape as signup. Use this token as
`Authorization: Bearer <token>` on the two endpoints below.

### `POST /submit_solve` (requires login)
```
{"topic": "lighthouses", "difficulty": "medium", "solve_time_seconds": 145.2, "hints_used": 1, "completed": true}
```
Logs the attempt against your account specifically -- this is now real,
persistent, per-player history, not a shared session-wide list.

### `GET /recommend_difficulty?topic=...` (requires login)
Now genuinely personalized: looks at **your own** solve history for that
topic (not everyone's), and recommends easy/medium/hard accordingly.

### `POST /generate_puzzle`
```
{"topic": "lighthouses", "num_words": 13, "difficulty": "medium"}
```
No login required -- generating and playing a puzzle stays open to anyone.
Login is only needed to save progress and get personalized recommendations.

### `GET /on_this_day?date=2026-09-10`
Same as always, no login required.

### `POST /hint`
Same as always, no login required.

### `GET /health`
Returns `{"status": "ok"}`.

## What's been tested, and how

**Verified, fully, offline:**
- Password hashing (`auth.py`): correct hash format, correct-password
  verification, wrong-password rejection, and confirmed salting actually
  produces different hashes for the same password each time
- JWT tokens (`auth.py`): full create/decode round trip with real claims,
  a tampered token correctly rejected, an expired token correctly rejected
- All three new/changed Python files compile with no syntax errors
- The adaptive-difficulty recommendation logic itself (four real scenarios:
  insufficient data, "breezing through", "struggling", and "moderate")
  -- unchanged by this update, still correct

**Not verified here, needs to happen in your environment:**
- `database.py`'s actual SQLAlchemy behavior -- I don't have SQLAlchemy
  installed in the sandbox I built this in (no network access to install
  new packages), so table creation and querying are written using standard,
  well-established patterns but haven't been executed. Test this by running
  `uvicorn main:app --reload` locally and trying signup → login →
  submit_solve → recommend_difficulty end to end.
- A real connection to Supabase/Neon specifically -- the connection string
  handling (including the `postgres://` → `postgresql://` normalization,
  needed because some providers still hand out the old URL scheme) is
  written defensively but untested against a real live database.

## Suggested next steps
1. Set up Supabase or Neon, get `DATABASE_URL`, deploy, and confirm
   signup/login/submit_solve/recommend_difficulty actually work end to end
2. Wire the frontend's login/signup UI to these endpoints (see
   `custom_crosswords_daily.html`)
3. Expand `historical_events.py` beyond the one verified sample date
4. Consider rate-limiting `/signup` and `/login` before this is public --
   right now there's nothing stopping repeated login attempts
