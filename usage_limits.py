"""
Usage caps across three tiers of access:

  Anonymous (no account): /generate_puzzle only, 3 tries, ONE TIME EVER
    (lifetime cap, not daily -- see below). NO access to /reword_clue at
    all -- reword requires an account, full stop.

  Free account: /generate_puzzle capped at 1/day, /reword_clue capped at
    3/day -- two INDEPENDENT pools, not shared. Both reset daily.

  Paid account ("tier" == "paid" on the user row): unlimited on both.
    Nothing here processes payment -- this only enforces a limit based on
    whatever `tier` value is already stored on the user, same as a real
    billing integration would set it.

Why reword has no anonymous access and a separate, more generous free
allowance than generation: generation is the core, expensive, headline
feature this app is built around -- reword is a smaller, cheaper
accessibility nice-to-have (see clue_rewriter.py). Gating it entirely
behind an account (rather than offering it anonymously too) keeps the
trial experience focused on the one thing that actually needs
demonstrating, and giving free accounts a separate 3/day pool for it
(rather than making it compete with generation for the same 1/day slot)
means using Reword doesn't eat into someone's one daily custom puzzle.

Why the anonymous trial is a LIFETIME cap, not a daily one: previously it
reset every day, which meant it never created real pressure to actually
create an account -- "just wait a day" was a free, zero-friction bypass.
Making it lifetime-per-anonymous-ID means the only ways to get a fresh
trial are clearing browser storage (wipes the localStorage-stored
anonymous ID) or switching browsers/devices -- both meaningfully
higher-friction than waiting for midnight. Raised from 1 try to 3 on a
separate product decision: a single trial rests someone's whole first
impression on one topic choice; 3 tries lets them actually explore before
deciding whether to sign up.

Anonymous IDs are tracked by a random UUID generated client-side and
stored in the browser's localStorage -- deliberately NOT by IP address.
IP-based tracking was considered and rejected: shared IPs (home wifi,
offices, schools) would punish unrelated people sharing one address,
mobile carrier-grade NAT makes IPs unreliable identifiers, and it's
trivially bypassed by switching networks, which would defeat the point of
a cost control even more than a resettable daily trial did.
"""
import datetime

FREE_TIER_GENERATE_DAILY_LIMIT = 1
FREE_TIER_REWORD_DAILY_LIMIT = 3
ANONYMOUS_TRIAL_LIFETIME_LIMIT = 3


class UsageLimitExceeded(Exception):
    """Raised when a free-tier user (or anonymous visitor) has hit their
    cap for the action they're attempting."""
    def __init__(self, limit: int, is_anonymous: bool = False, action: str = "generation"):
        self.limit = limit
        self.is_anonymous = is_anonymous
        if is_anonymous:
            msg = (
                f"You've used all {limit} of your free trial generations. "
                f"Sign up for a free account to get a fresh generation every "
                f"day, plus access to Reword -- unlike the trial, a free "
                f"account's allowance actually renews."
            )
        else:
            msg = (
                f"You've used today's free {action}. Upgrade for unlimited "
                f"access, or try again tomorrow."
            )
        super().__init__(msg)


def check_and_increment_usage(user) -> int:
    """
    Call this before performing /generate_puzzle for a LOGGED-IN user.
    Resets the daily counter if the stored date isn't today, then either
    increments and allows the action, or raises UsageLimitExceeded if the
    free-tier generate cap is already hit.

    Mutates `user` in place (caller commits the session afterward) and
    returns the number of free generations remaining today AFTER this
    action.
    """
    if user.tier == "paid":
        return -1  # sentinel meaning "unlimited", not a real count

    today = datetime.date.today()
    if user.daily_premium_actions_date != today:
        user.daily_premium_actions_used = 0
        user.daily_premium_actions_date = today

    if user.daily_premium_actions_used >= FREE_TIER_GENERATE_DAILY_LIMIT:
        raise UsageLimitExceeded(FREE_TIER_GENERATE_DAILY_LIMIT, action="generation")

    user.daily_premium_actions_used += 1
    return FREE_TIER_GENERATE_DAILY_LIMIT - user.daily_premium_actions_used


def check_and_increment_reword_usage(user) -> int:
    """
    Same idea as check_and_increment_usage, but for /reword_clue -- a
    SEPARATE daily pool from generation, only ever called for a logged-in
    user (there is no anonymous path for reword at all; main.py enforces
    that by requiring login on this endpoint, not by calling this
    function with no user).
    """
    if user.tier == "paid":
        return -1

    today = datetime.date.today()
    if user.daily_reword_date != today:
        user.daily_reword_used = 0
        user.daily_reword_date = today

    if user.daily_reword_used >= FREE_TIER_REWORD_DAILY_LIMIT:
        raise UsageLimitExceeded(FREE_TIER_REWORD_DAILY_LIMIT, action="reword")

    user.daily_reword_used += 1
    return FREE_TIER_REWORD_DAILY_LIMIT - user.daily_reword_used


def check_and_increment_anonymous_usage(anon_usage) -> int:
    """
    Lifetime (NOT daily) cap for an AnonymousUsage row, used ONLY for
    /generate_puzzle -- there is no anonymous path for reword at all.
    Deliberately does NOT reset based on date: once `daily_actions_used`
    (kept as the field name for schema stability, but functioning as a
    lifetime counter here, not a daily one) reaches the limit, it stays
    blocked forever for that anonymous ID. `daily_actions_date` is still
    recorded for auditing (when the trial was last used) but is never
    read to decide whether to reset -- there is no reset.
    """
    if anon_usage.daily_actions_used >= ANONYMOUS_TRIAL_LIFETIME_LIMIT:
        raise UsageLimitExceeded(ANONYMOUS_TRIAL_LIFETIME_LIMIT, is_anonymous=True)

    anon_usage.daily_actions_used += 1
    anon_usage.daily_actions_date = datetime.date.today()  # audit timestamp only
    return ANONYMOUS_TRIAL_LIFETIME_LIMIT - anon_usage.daily_actions_used
