# TopiCross — Backend

Real backend API: Claude generates a topical word bank on request, then your
actual crossword generator (`generator2.py` + `compact_lib.py`, the same
engine used to build every book in this series) places it into a grid.
Accounts, solve-history tracking, and personalized difficulty recommendations
are backed by a real Postgres database. The On This Day feature pulls real,
editorially-curated events from Wikipedia for any day of the year, grounding
Claude's clue-writing in that real data instead of asking it to recall
historical facts from memory.

## Setup

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export JWT_SECRET_KEY=<a long random string -- see below>
export DATABASE_URL=postgresql://...   (see "Database" section below -- required)
uvicorn main:app --reload
```

### Generating a JWT_SECRET_KEY
```
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Set this in your environment (or Render's "Environment" tab). If it's not
set, the app still runs using a randomly generated key, but every restart
invalidates all existing logins -- fine for local testing, not for anything
real.

## Database -- read this before deploying

**Render's free web service tier has an ephemeral filesystem.** Any local
file (including a SQLite database file) gets wiped every time the service
redeploys or spins down from inactivity.

**The fix: use a real hosted Postgres database, separate from Render's web
service.** Two options with genuinely permanent free tiers:
- **Supabase** (supabase.com) -- free Postgres, doesn't expire
- **Neon** (neon.tech) -- free serverless Postgres, doesn't expire

(Render's own free Postgres expires after 30 days -- fine for a demo, not
for anything you want to keep working.)

**If you're on Supabase specifically and deploying to Render:** use the
**Session pooler** connection string, not "Direct connection." Render (like
several other hosts) only supports outbound IPv4, while Supabase's direct
connection hostname resolves to IPv6 only by default. The Session pooler
routes through a different host that supports IPv4. The pooler username
also has a different format -- it includes your project ref
(`postgres.xxxxxxxx`, not just `postgres`) -- so copy the whole string
Supabase gives you rather than reusing a username from a different mode.

Whichever provider you use, set the connection string as `DATABASE_URL` in
Render's Environment tab. If it isn't set at all, the app falls back to a
local SQLite file (`local_dev.db`) for local testing only.

## Endpoints

### `POST /signup` / `POST /login`
```
{"email": "you@example.com", "password": "at least 8 characters"}
```
Returns `{"access_token": "...", "token_type": "bearer"}`. Use the token as
`Authorization: Bearer <token>` on the two endpoints below.

### `POST /submit_solve` (requires login)
```
{"topic": "lighthouses", "difficulty": "medium", "solve_time_seconds": 145.2, "hints_used": 1, "completed": true}
```
Logs the attempt against your account specifically.

### `GET /recommend_difficulty?topic=...` (requires login)
Personalized to your own solve history for that topic.

### `POST /generate_puzzle`
```
{"topic": "lighthouses", "num_words": 13, "difficulty": "medium"}
```
No login required.

### `GET /on_this_day?date=2026-09-10`
No login required. Works for any calendar date, any year -- see
"How On This Day actually works" below.

### `POST /hint`
```
{"word": "BEACON", "tier": 1}
```
Rebuilt to be purely letter-based, with zero dependency on clue text and
zero LLM call per hint -- entirely deterministic and free to compute.
Tier 1 reveals the first letter only. Tier 2 is cumulative and reveals
first + last letter (not a replacement of tier 1's info, an addition to
it). Tier 3 is the full answer. Rebuilt from an earlier version where
tier 1 was a softer, rephrased clue -- that overlapped too much in
function with the separate Reword feature below, which also rephrases
the clue. Returns `{"tier": 1, "text": "...", "is_reveal": false}`.

### `POST /reword_clue`
```
{"word": "JACKSON", "clue": "Known as the King of Pop"}
```
Rewrites a clue in plainer language -- removing assumed cultural
references, era-specific slang, or niche terminology -- WITHOUT making the
puzzle any easier to solve. This is the direct answer to an accessibility
gap identified at the very start of this project: the original competitor
app markets itself as "designed for seniors" but has no way to handle a
clue built around a reference a given player might not recognize. No login
required. Returns `{"original": ..., "reworded": ..., "changed": bool}` --
includes a safety check that rejects and falls back to the original clue
if Claude's rewrite accidentally leaks the answer word.

Named "reword" rather than "simplify" -- deliberately. The original name
implied the feature would make clues *easier*, which it never did by
design (a same-difficulty reword doesn't help you solve faster, it just
uses more universal language). Real user testing surfaced exactly this
mismatch: "it doesn't really make the clue simpler" was the correct
observation about a feature that was working as designed but named in a
way that promised the wrong thing.

Deliberately kept separate from the hint tiers rather than merged into
them, even though a "fold the reword into hint tier 1" alternative was
seriously considered. A hint tier's whole job is genuine solving help --
that's what fixed the original "punitive coin-gated hints" complaint this
project started from. A same-difficulty reword doesn't help you solve
faster, so merging it in would make that first hint tier weaker, not
stronger. Kept as a separate feature since it answers a different need
(understand the wording) than hints do (get help solving).

**Also fixed alongside the rename:** the underlying prompt originally gave
Claude an explicit "if no change is needed, return it unchanged" escape
hatch, stacked with several other constraints. Since this app's own
clue-generation prompts already write reasonably plain clues, Claude
reviewing its own earlier output almost always took that easy path and
returned the clue verbatim -- which is what actually caused the "doesn't
change anything" symptom, on top of the naming problem. Removed the escape
hatch, added an explicit "you must produce a genuinely different rewrite"
instruction. Verified the safety nets (answer-leak rejection, exception
fallback) still work correctly with the new prompt -- not yet verified
against a live API call.

### `GET /health`
Returns `{"status": "ok"}`.

## How On This Day actually works

`historical_events.py` calls Wikipedia's real, official On This Day REST API
(`en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{mm}/{dd}`), which
returns real, editor-curated historical events for that calendar date --
covering all 365/366 days, not just one hardcoded sample.

Those real event descriptions are then handed to Claude with explicit
grounding instructions: extract a crossword word and write a clue **only**
from the given text, never adding outside historical knowledge. This is the
same principle as retrieval-augmented generation -- Claude formats and
summarizes real retrieved facts, it doesn't recall dates from its own
training data, which is what actually avoids hallucinated "facts" rather
than just working around the risk.

Results are cached in memory per (month, day) so a given date is only
fetched and processed once per server run.

**A safety detail worth knowing:** if the live Wikipedia fetch fails, there's
exactly one hardcoded fallback -- verified, non-AI-generated data for
September 10 specifically. For any other date, a failed fetch returns an
empty result rather than fabricating anything. Confirmed by direct test:
a date with no real data and a failed fetch returns `[]`, not invented facts.

## Clue-overlap protection

Both `/generate_puzzle` and `/on_this_day` now run their word banks through
`entry_dedup.py` before building the grid. This catches the case where
Claude extracts two different answer words from the same underlying fact --
producing two clues that read almost identically but point to different
answers, which is confusing in a real crossword. Detection uses two
signals: near-identical wording (character-level), or substantial shared
vocabulary combined with a matching year mention (including decade forms
like "1850s"), with basic singular/plural normalization ("island" /
"islands") so minor word-form differences don't hide a real match.

This went through two real rounds of calibration, not one:
  1. First version caught the originally-reported bug (two words extracted
     from one event) but missed a decade-year case ("1850s") due to a
     regex gap, and used thresholds that were too strict
  2. After deploying that first fix, an actual live case still slipped
     through in production -- two clues both about Hurricane Iniki hitting
     Kauai in 1992, phrased differently enough that the word-overlap score
     (0.46) landed just under the threshold (0.5). Recalibrated the
     threshold down (with a wide safety margin against the false-positive
     guard case, which scores 0.17) and added plural normalization, then
     re-verified against all 6 scenarios including this exact real case
     -- not just assumed the new number was right.

## What's been tested, and how

**Verified, fully, offline:**
- Password hashing and JWT tokens (`auth.py`): hash/verify round trip,
  confirmed salting, tampered tokens rejected, expired tokens rejected
- The On This Day grounding pipeline (`historical_events.py`), using mocked
  Wikipedia and Claude responses: the prompt correctly includes only the
  given real facts with an explicit "don't use outside knowledge"
  instruction; a mocked Claude response is correctly parsed into clean
  entries; caching confirmed (a second request for the same date doesn't
  re-fetch); the verified fallback correctly activates only for its one
  specific date when the live fetch fails; and -- most importantly -- a
  random date with no fallback and a failed fetch correctly returns an
  empty list rather than inventing anything
- The adaptive-difficulty recommendation logic (four scenarios: insufficient
  data, "breezing through," "struggling," "moderate")
- All Python files compile with no syntax errors

**Not verified here, needs to happen in your environment:**
- `database.py`'s actual SQLAlchemy behavior against a real Postgres
  instance -- SQLAlchemy isn't installed in the sandbox this was built in
- A real live call to Wikipedia's API and to Claude for the On This Day
  extraction -- the pipeline logic is tested with mocked responses, but the
  real Wikipedia response shape and real Claude output should be confirmed
  once this is actually running
- A real connection to Supabase/Neon specifically

## Free-tier usage cap

`/generate_puzzle` and `/reword_clue` are metered together as "premium
actions" -- free accounts get 3 combined per day (shared between both, not
3 each), reset at midnight server time. Paid accounts (`User.tier ==
"paid"`) are never limited. See `usage_limits.py`.

**This is why both endpoints now require login**, where they didn't
before: there's no reliable way to enforce a per-user daily cap on an
anonymous request with no persistent identity. `/on_this_day` and `/hint`
stay open to anyone, since those cost nothing or next-to-nothing per call
regardless of who's asking.

A failed generation (e.g. a malformed Claude response) does NOT consume
the user's daily quota -- the usage check happens before the Claude call,
but only commits to the database after a successful generation. Verified
via 4 offline tests against a mock user object: the cap triggers at
exactly 3, the counter is genuinely shared across both action types (not
tracked separately), the daily counter correctly resets on a new day even
with stale usage stored from a previous day, and a paid-tier user is never
blocked regardless of how much usage is on their row.

Nothing here processes real payment -- `tier` is just a field on the user
row that a real billing integration (Stripe, etc.) would need to set.
That integration doesn't exist yet.

## Anonymous trial (try before signing up)

`/generate_puzzle` and `/reword_clue` accept EITHER a logged-in user
(`Authorization: Bearer <token>`, 3/day) OR an anonymous trial ID
(`X-Anonymous-Id` header, 1/day). Exactly one is required -- a request
with neither gets a 401 asking for one or the other.

The anonymous ID is a random UUID generated once in the browser
(`crypto.randomUUID()`) and stored in `localStorage`, sent on every
request while the visitor isn't logged in. **Deliberately not IP-based**:
shared IPs (home wifi, offices, schools) would punish unrelated people,
mobile carrier-grade NAT makes IPs unreliable identifiers, and IP-based
limiting is trivially bypassed by switching networks -- which defeats the
actual purpose of a cost control. A localStorage ID has the same
"resettable" property, but clearing browser data is meaningfully
higher-friction than reconnecting wifi, and it's an honest tradeoff for a
try-before-signup flow rather than a security boundary.

Stored in the real database (`AnonymousUsage` table), not in memory --
Render's free tier sleeps after 15 minutes idle, which would silently
reset an in-memory counter far too often to function as a real limit.

Tested with 3 additional scenarios beyond the free-tier tests: the
existing free-tier logic (3/day) is unaffected by this addition, the
anonymous trial correctly caps at exactly 1 with a signup-nudging error
message, and the anonymous daily counter resets correctly on a new day.
Also confirmed in-browser: the anonymous ID persists correctly across a
page reload rather than regenerating each time, the header is genuinely
sent on the request when logged out, and a logged-in user correctly uses
their auth token instead, never sending the anonymous header.

## Real bug found and fixed: schema drift on an existing deployed database

Login started failing with a generic "Failed to fetch" after the
paid-tier usage columns (`tier`, `daily_premium_actions_used`,
`daily_premium_actions_date`) were added to the `User` model. Root cause:
`init_db()`'s `Base.metadata.create_all()` only creates tables that don't
exist yet -- it does NOT add new columns to a table that already exists in
a real deployed database. The `users` table had already been created
(before these columns existed), so every query touching it started
failing against a live SQLAlchemy error, which surfaced to the browser as
an opaque network failure rather than a clear message.

`init_db()` now also inspects the actual database schema on startup and
adds any columns present in the Python models but missing from the real
table -- a lightweight stand-in for a real migration tool (Alembic would
be the correct long-term answer, more than this project needs right now).
Handles the NOT-NULL-on-an-existing-table problem correctly: a new
required column on a table that already has rows needs a database-level
DEFAULT to backfill those rows, or Postgres rejects the ALTER outright.
Tested the default-literal generation against the three actual columns
this was built for (string, integer, and a dynamic date default requiring
a special-cased `CURRENT_DATE` SQL literal rather than a fixed Python
value) -- all three produce correct SQL. Not yet verified against a real
live ALTER TABLE run, since SQLAlchemy isn't available in the sandbox this
was built in.

## Admin endpoint for testing paid tier (temporary)

`POST /admin/set_tier` manually flips a user's tier between "free" and
"paid" -- a stand-in for testing the paid-tier logic before any real
billing integration exists.

**Setup:** generate a secret and add it to Render's Environment tab:
```
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Set that as `ADMIN_SECRET_KEY`. If this variable isn't set at all, the
endpoint refuses to run rather than silently having no protection.

**Usage:**
```
POST /admin/set_tier
Header: X-Admin-Key: <your ADMIN_SECRET_KEY>
Body: {"email": "you@example.com", "tier": "paid"}
```
Uses a constant-time comparison for the key check (same reasoning as
password verification in `auth.py`) -- tested against matching, wrong,
and empty key values.

**This is explicitly temporary.** Anyone holding the admin key can grant
free paid access to any account. Fine while you're the only person
testing this; should be removed or replaced with real Stripe webhook
handling before this app has real users who aren't you.

## Display name / username

Users can optionally set a display name (2-30 characters) at signup, or
add/change one anytime while logged in via `POST /update_display_name`.
Falls back to the part of the email before "@" if never set -- so nothing
looks broken for accounts created before this field existed, and raw
email addresses are never the only thing shown in the UI.

Added specifically as groundwork for a future leaderboard feature (see
product discussion): showing real email addresses on any shared/social
feature would be a real privacy problem, so this needed to exist before
any leaderboard could be built responsibly, regardless of which
leaderboard direction (global vs. friends/family) gets built first.

`display_name` is nullable on the `User` model, so it's picked up
automatically by the same schema-drift fix in `init_db()` that handles
adding new columns to an already-deployed database (see the "Real bug
found and fixed" section above) -- no manual database changes needed
beyond redeploying.

Tested: the fallback logic (set name used directly, no name falls back to
email prefix, whitespace-only name treated as not set), and in-browser --
the name displays correctly after signup, persists across a page reload,
correctly falls back to email when not set, and the update form's
client-side length validation rejects a too-short name.

## Free-tier cap changed: 3/day -> 1/day ("Option B")

Following product discussion weighing a fully-paid-generation model
("Option A") against dropping the free cap to match the anonymous trial
("Option B") -- Option B was chosen. On This Day stays fully free and
uncapped for everyone. Both anonymous visitors and free-account holders
now get exactly 1 combined generate/reword action per day, not 3.

This was a deliberate, reasoned change, not an arbitrary tweak: a 3/day
cap likely doesn't bind for most casual users in a single sitting, so it
doesn't create real upgrade pressure. 1/day is far more likely to
actually surface the moment someone wants a second puzzle in the same
session.

**A real consequence of this, fixed in the same change:** with both caps
now equal, the anonymous-trial-exceeded message could no longer honestly
claim that signing up gets you "more" generations, since it doesn't
anymore -- that would have been a false claim sitting in the code.
Rewrote the message to correctly frame what creating a free account
actually unlocks at this cap level: solve history tracking and
personalized recommendations, not additional generations. Paying is now
the only way to get more generations -- account creation and payment are
cleanly separated concerns.

No frontend changes were needed for this -- confirmed by searching for
any hardcoded "3 per day" text and finding none; every place that shows a
remaining-count already reads the live number from the backend response
rather than a hardcoded value, so it automatically reflects the new cap.

Re-verified all 5 usage-limit test scenarios at the new limit (exact cap
enforcement, the shared pool across generate/reword, the corrected
messaging, daily reset, and paid-tier bypass) -- all pass.

## Anonymous trial changed: lifetime cap, not daily

The anonymous trial no longer resets each day -- it's now a genuine
one-time-ever allowance per anonymous ID (the random UUID stored in the
browser's localStorage), not a refreshing daily one. Implemented by
simply never resetting the counter based on date for anonymous usage
(`check_and_increment_anonymous_usage` no longer has any date-comparison
reset logic at all) -- once used, that anonymous ID is blocked
permanently, for as long as its database row and localStorage ID both
persist.

This meaningfully raises the bar on the "just wait a day" bypass -- the
only ways to get a fresh trial now are clearing browser storage (which
wipes the localStorage ID) or switching to a different browser/device,
both higher-friction than waiting for midnight.

**A real consequence, fixed in the same change:** this also makes signing
up for a free account genuinely more valuable again. The previous version
(equal 1/day caps for both anonymous and free accounts) meant an account
didn't unlock more generations, only tracking/personalization. Now it
does: the trial is used once, ever; a free account's 1/day allowance
actually renews. The anonymous-limit-exceeded message was rewritten to
reflect this correctly.

**The logged-in free-tier cap is unaffected** -- it still resets daily,
exactly as before. Only the anonymous trial's behavior changed.

Tested: the free-tier daily reset still works correctly (regression
check), the anonymous trial still blocks a same-day second attempt, and
-- the key test -- an anonymous ID that used its trial 365 days ago is
still correctly blocked today, confirming this is genuinely a lifetime
cap and not a daily one with a very long window. Also confirmed a
genuinely fresh anonymous ID still gets its one trial use.

## Reword split from Generate into its own tier structure

Following further product discussion, /generate_puzzle and /reword_clue
no longer share a usage pool or an anonymous-access policy at all:

- **Anonymous (no account):** /generate_puzzle only, 3 tries, lifetime
  (not daily -- see the "Anonymous trial changed" section above). NO
  anonymous access to /reword_clue at all -- it requires login, full
  stop, enforced via `Depends(get_current_user)` rather than the optional
  dependency /generate_puzzle uses.
- **Free account:** /generate_puzzle capped at 1/day, /reword_clue capped
  at 3/day -- two genuinely INDEPENDENT pools tracked by separate columns
  on the User model (`daily_premium_actions_used`/`_date` for generate,
  new `daily_reword_used`/`_date` for reword). Maxing out one has zero
  effect on the other in either direction.
  **The reword cap of 3/day is a proposed default, not a number handed
  down from product discussion -- flagged as an assumption when built,
  easy to adjust.**
- **Paid account:** unlimited on both, independently.

Why: generation is the core, expensive, headline feature this app is
built around; reword is a smaller, cheaper accessibility nice-to-have
(see clue_rewriter.py). Gating reword entirely behind an account keeps
the anonymous trial experience focused on the one thing that actually
needs demonstrating, and giving free accounts a separate pool for reword
means using it doesn't eat into someone's one daily custom puzzle.

The two new User columns are picked up automatically by the existing
schema-drift fix in `init_db()` -- no manual database changes needed
beyond redeploying (see the "Real bug found and fixed" section above for
how that mechanism works).

Tested: generate and reword pools are genuinely independent in BOTH
directions (maxing generate doesn't touch reword's count, and vice
versa) -- not just asserted, actually exercised as two separate test
cases. The anonymous trial still allows exactly 3 (re-verified at the
new limit) and still never resets, even 100 days later. Paid tier
confirmed unlimited on both pools independently. In-browser: Reword now
correctly blocks outright (no anonymous attempt at all) when logged out,
with a message explaining why; confirmed the X-Anonymous-Id header is
never sent on a reword request regardless of login state; and confirmed
/generate_puzzle's anonymous-trial behavior is completely unaffected by
this change (regression check).

## Real bug found and fixed: a grid-placement failure silently consumed a trial/daily use

Reported symptom: an anonymous trial (3 lifetime tries) only yielded 2
actual puzzles. Traced the cause: /generate_puzzle can fail at TWO
separate stages -- Claude's word-bank generation (a ValueError), or grid
placement afterward in build_puzzle_response() (an HTTPException, raised
when the generated words don't share enough letters to interlock into a
valid crossword). The commit-vs-rollback handling only covered the FIRST
failure point. If word-bank generation succeeded but grid placement then
failed, the usage increment had already been committed to the database
before that second failure was even reached -- silently charging a
trial/daily use for an attempt that produced no usable puzzle at all.

Fixed by moving both generate_word_bank() and build_puzzle_response()
inside the same try block, and only committing after BOTH succeed --
either failure point now correctly rolls back instead of charging the
quota. Verified with a control-flow simulation covering all three paths
(word-bank failure, grid-placement failure, full success) using a mock
database session -- confirmed the grid-placement failure path, the
specific one that was broken, now correctly rolls back rather than
committing.

**On a related note the same report raised:** /on_this_day was checked
directly and confirmed to never touch usage tracking at all -- it was
already fully separate from the custom-generation trial, architecturally,
before this fix. The "only got 2 of 3" symptom was caused entirely by the
bug above, not by On This Day consuming trial uses.

## Stats dashboard (paid feature)

`GET /stats` -- requires login AND `tier == "paid"` (returns 403 with an
upgrade message for logged-in free-tier users). Computes totals,
completion rate, average solve time/hints, favorite topics, difficulty
breakdown, fastest solve, recent activity, and solve streaks from the
user's own `SolveRecord` history.

The computation itself (`stats.py`) is deliberately database-free -- it
takes plain dicts, not SQLAlchemy model instances, so it can be tested
completely offline with zero setup. `main.py`'s job is just fetching the
records and handing them off as dicts.

**Streak definition, worth being explicit about:** a streak is a run of
consecutive calendar days with at least one completed solve. The current
streak counts backward from today, but stays "alive" if the user
completed a puzzle yesterday and hasn't played yet today -- it doesn't
zero out at midnight before they've had a chance to keep it going.

Tested thoroughly, since streak logic has real edge cases worth getting
right rather than assuming: 6 scenarios covering an empty history, a
single day, a streak ending today, a streak ending yesterday (still
alive), a broken streak with no recent activity (current resets to 0 but
longest is preserved), and the trickiest case -- an old streak that's
LONGER than the current one, confirming `longest_streak` correctly
reflects historical data even when the live streak is shorter. Also
verified the full aggregation (`build_stats`) against a hand-computed
5-record dataset -- every field (totals, completion rate, average solve
time, fastest solve, favorite-topic ordering, difficulty breakdown,
recent-activity ordering) checked against manually calculated expected
values, not just spot-checked.

Frontend: a stats dashboard section with four headline number cards
(solved, current streak, longest streak, completion rate) plus favorite
topics, difficulty breakdown, and recent activity. Tested in-browser:
blocks with a clear message when not logged in, and confirmed the
results panel is genuinely *visible* after loading (not just present in
the DOM but hidden by CSS -- a real bug class caught once already
earlier in this project, checked for again here rather than assumed
fixed by pattern-matching).

## Delete account and password reset

### `POST /delete_account` (requires login)
```
{"password": "your current password"}
```
Permanently deletes the account and ALL solve history. Requires
re-entering the password, not just a valid session token -- a deliberate
speed bump against a stolen/leaked token alone being enough to destroy an
account, same reasoning as requiring a password to change one.

Deleting a User now cascades to delete their SolveRecord rows too
(`cascade="all, delete-orphan"` added to the relationship in
database.py) -- without this, deletion would either leave orphaned rows
or fail outright against a foreign-key constraint, since SolveRecord.user_id
is NOT NULL.

### `POST /forgot_password` / `POST /reset_password`
Real, secure token-based reset flow: `/forgot_password` generates a
random 32-byte token, stores only its SHA-256 hash (never the raw token)
on the user's row with a 30-minute expiry, and emails a link containing
the raw token. `/reset_password` validates the token by hash, checks
expiry, and -- critically -- clears the stored token immediately after a
successful reset, making it single-use (a replayed link fails the lookup
since nothing matches the now-cleared hash).

Always returns the same generic message from `/forgot_password` whether
or not the email has an account, same principle as `/login`'s error
message -- don't let this endpoint be used to check which emails have
accounts.

**Now a real, working integration with Resend** (https://resend.com), via
a plain HTTP call using `requests` (already a dependency) rather than
adding the `resend` SDK package, since under the hood this is one simple
API call.

**A real limitation, confirmed directly against Resend's current docs,
not assumed from memory:** Resend's no-setup sender address
(`onboarding@resend.dev`) can ONLY deliver to the Resend account owner's
own verified email -- it returns a 403 for any other recipient. This
means, as shipped:
- You (the account owner) CAN test the full flow end-to-end by
  requesting a reset for your own account's email
- A real user signing up with a different email will NOT receive
  anything until a domain you own is verified with Resend (Domains ->
  Add Domain in their dashboard, then add the DNS records they give you
  at your domain's DNS provider)

This project doesn't own a custom domain yet as of this writing (it's on
GitHub Pages' default subdomain) -- buying and verifying one is a real,
separate decision (and small cost) from just adding an API key, and is
required before this is a genuinely working self-service flow for real
users, not just you.

**Setup once you have a verified domain (or for self-testing without
one):**
```
RESEND_API_KEY=<your key from resend.com>
RESEND_FROM_ADDRESS=noreply@yourdomain.com   (optional -- defaults to
                                               onboarding@resend.dev,
                                               which only reaches your
                                               own account email)
```
Without `RESEND_API_KEY` set at all, the code falls back to the same
log-only behavior as before -- this is unchanged and still exactly as
honest as it was.

`main.py`'s `/forgot_password` wraps the send in a try/except: a failed
real send (e.g. the 403 above) is logged server-side but does not crash
the request or change the generic user-facing response, which needs to
stay identical whether or not the email exists AND whether or not the
send itself succeeded -- letting a send failure leak through would be a
smaller version of the same information-leak problem the generic message
already guards against.

**Tested:** the log-only fallback still works unchanged (no regression);
the real-send path's HTTP request is correctly constructed (right URL,
auth header, recipient, reset link embedded in the email body, correct
default `from` address) verified against a mocked HTTP call, since I
can't reach Resend's real API from this sandbox; a rejected send (the
403 case) correctly raises rather than silently disappearing; and the
`main.py` wrapper correctly catches that failure, logs it, and still
returns the unchanged generic response.

The reset link points back to the app's own page with a `?reset_token=`
query parameter (`FRONTEND_URL` env var, defaults to the current known
GitHub Pages URL) -- the frontend detects this parameter on page load and
shows a "set new password" panel.

**Tested, all security-critical logic:**
- Reset token generation/hashing: distinct raw token and hash each call,
  deterministic hashing for lookup, tokens genuinely random (never
  reused), an incorrect/guessed token correctly fails to match
- Reset flow control logic (simulated against mock user rows): valid
  unexpired token succeeds, an expired token is correctly rejected, an
  unknown/wrong token is rejected, and -- the single-use guarantee --
  replaying an already-used token fails because its hash was cleared
- Delete-account password verification: correct password allows
  deletion, wrong password blocks it
- In-browser: both panels toggle correctly, both actions are blocked
  with clear messages when required fields are empty, the reset-password
  section correctly shows only when the URL has a `reset_token` parameter
  and stays hidden otherwise, and the reset form's length validation
  works

One test-writing note worth remembering: an early version of the
in-browser delete-account test used a text-based button selector that
ambiguously matched both the warning text ("permanently deletes your
account...") and the actual button ("Permanently Delete") -- Playwright
clicked the wrong element, and the test's failure was a test bug, not an
app bug, confirmed by calling the function directly first. Fixed by
selecting the button element specifically rather than by text alone.

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

## Suggested next steps

1. Confirm the live On This Day pipeline works for a few different real
   dates, not just the mocked test cases
2. Consider rate-limiting `/signup` and `/login` before this is public
3. Consider moving the on-this-day cache from in-memory to the database, so
   it survives restarts instead of recomputing after every redeploy or
   Render free-tier sleep cycle
