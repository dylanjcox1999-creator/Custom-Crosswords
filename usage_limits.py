"""
Usage caps across three tiers of access:

  Anonymous (no account): /generate_puzzle only, 3 tries, ONE TIME EVER
    (lifetime cap, not daily -- see below). NO access to /reword_clue at
    all -- reword requires an account, full stop.

  Free account: /generate_puzzle capped at 1/day, /reword_clue capped at
    3/day -- two INDEPENDENT pools, not shared. Both reset daily.

  Paid account ("tier" == "paid" on the user row): a much higher daily
    cap than free (see PAID_TIER_* below), not truly infinite. This
    isn't a marketing "unlimited" walked back -- see the note below the
    constants for why a real, generous ceiling still matters even on a
    paid plan.

Why paid isn't truly uncapped: each generation/reword call costs real
money (a Claude API call). At the free-tier cost per call, a genuinely
engaged subscriber's realistic monthly usage costs pennies -- pricing a
subscription against that is easy. What's NOT bounded without a real cap
is a compromised paid account, a scripted/automated abuser, or someone
stress-testing the API key itself: with a literal -1-means-infinite
check, nothing stops thousands of calls in a day. The caps below
(PAID_TIER_GENERATE_DAILY_LIMIT / PAID_TIER_REWORD_DAILY_LIMIT) are set
far above any plausible real usage -- a real subscriber generating one
puzzle every 30-45 minutes non-stop, all day, every day, still wouldn't
hit them -- so this is a background abuse safeguard, not a feature
anyone should ever see a countdown for. The success path deliberately
still returns the same -1 "unlimited" sentinel to the frontend for paid
users (see check_and_increment_usage below) specifically so normal
subscribers never see any counter or "X remaining" messaging -- only
someone who actually hits this ceiling sees anything different, and the
message they get explicitly says so rather than showing the standard
"upgrade" prompt a free user would see.

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

# Fair-use ceiling for paid accounts -- see the module docstring above for
# why this exists despite paid being marketed as "unlimited". Deliberately
# generous: 25 generations/day is one roughly every 30-45 minutes of a
# waking day, every single day, with zero rest days -- no real subscriber
# should ever come close to this.
PAID_TIER_GENERATE_DAILY_LIMIT = 25
PAID_TIER_REWORD_DAILY_LIMIT = 60


class UsageLimitExceeded(Exception):
    """Raised when a user (free, paid, or anonymous) has hit their cap
    for the action they're attempting."""
    def __init__(self, limit: int, is_anonymous: bool = False, action: str = "generation", is_paid_fair_use: bool = False):
        self.limit = limit
        self.is_anonymous = is_anonymous
        self.is_paid_fair_use = is_paid_fair_use
        if is_anonymous:
            msg = (
                f"You've used all {limit} of your free trial generations. "
                f"Sign up for a free account to get a fresh generation every "
                f"day, plus access to Reword -- unlike the trial, a free "
                f"account's allowance actually renews."
            )
        elif is_paid_fair_use:
            # Deliberately NOT the same message as the free-tier cap --
            # this user is already paying, so "upgrade" would be a
            # confusing, wrong thing to tell them.
            msg = (
                f"You've hit today's fair-use limit of {limit} {action}s for "
                f"paid accounts -- this is a high ceiling meant to catch "
                f"automated/unusual activity, not normal use. It resets at "
                f"midnight; if you're hitting this during genuine everyday "
                f"use, contact support, this limit is meant to be raised "
                f"for a real case like that, not to cap you."
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
    increments and allows the action, or raises UsageLimitExceeded if
    this user's tier-appropriate generate cap is already hit.

    Mutates `user` in place (caller commits the session afterward) and
    returns the number of generations remaining today AFTER this action
    for a free user, or -1 (the "effectively unlimited" sentinel the
    frontend already expects) for a paid user who's still under the
    fair-use ceiling -- paid users only ever see a real number if they
    actually hit that ceiling, via the exception message above, not via
    this return value.
    """
    is_paid = user.tier == "paid"
    limit = PAID_TIER_GENERATE_DAILY_LIMIT if is_paid else FREE_TIER_GENERATE_DAILY_LIMIT

    today = datetime.date.today()
    if user.daily_premium_actions_date != today:
        user.daily_premium_actions_used = 0
        user.daily_premium_actions_date = today

    if user.daily_premium_actions_used >= limit:
        raise UsageLimitExceeded(limit, action="generation", is_paid_fair_use=is_paid)

    user.daily_premium_actions_used += 1

    if is_paid:
        return -1
    return limit - user.daily_premium_actions_used


def check_and_increment_reword_usage(user) -> int:
    """
    Same idea as check_and_increment_usage, but for /reword_clue -- a
    SEPARATE daily pool from generation, only ever called for a logged-in
    user (there is no anonymous path for reword at all; main.py enforces
    that by requiring login on this endpoint, not by calling this
    function with no user).
    """
    is_paid = user.tier == "paid"
    limit = PAID_TIER_REWORD_DAILY_LIMIT if is_paid else FREE_TIER_REWORD_DAILY_LIMIT

    today = datetime.date.today()
    if user.daily_reword_date != today:
        user.daily_reword_used = 0
        user.daily_reword_date = today

    if user.daily_reword_used >= limit:
        raise UsageLimitExceeded(limit, action="reword", is_paid_fair_use=is_paid)

    user.daily_reword_used += 1

    if is_paid:
        return -1
    return limit - user.daily_reword_used


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
