"""
Daily usage cap for free-tier accounts, plus a small anonymous trial
allowance for visitors who haven't signed up yet.

Free tier: 3 combined /generate_puzzle + /reword_clue calls per day, shared
across both -- these are the only two endpoints with a real per-call cost
(a Claude API call each). Everything else (On This Day, hints, accounts,
solve tracking, difficulty/topic recommendations) stays free and uncapped,
since those cost nothing or next-to-nothing marginally per user.

Anonymous trial: a smaller allowance (1/day) for visitors trying the app
before creating an account, tracked by a random ID generated client-side
and stored in the browser's localStorage -- deliberately NOT by IP
address. IP-based tracking was considered and rejected: shared IPs (home
wifi, offices, schools) would punish unrelated people sharing one address,
mobile carrier-grade NAT makes IPs unreliable identifiers, and it's
trivially bypassed by switching networks -- which defeats the actual
purpose of a cost control. A localStorage ID has the same "can be reset"
property (clearing browser data resets it), but that's a meaningfully
higher-friction bypass, and an honest tradeoff for a try-before-signup
flow rather than a security boundary.

Paid tier ("tier" == "paid" on the user row): never limited. Nothing here
processes payment -- this only enforces a limit based on whatever `tier`
value is already stored on the user, same as a real billing integration
would set it.
"""
import datetime

FREE_TIER_DAILY_LIMIT = 3
ANONYMOUS_TRIAL_DAILY_LIMIT = 1


class UsageLimitExceeded(Exception):
    """Raised when a free-tier user (or anonymous visitor) has hit their
    daily cap."""
    def __init__(self, limit: int, is_anonymous: bool = False):
        self.limit = limit
        self.is_anonymous = is_anonymous
        if is_anonymous:
            msg = (
                f"You've used your {limit} free trial generation(s) for today. "
                f"Sign up for a free account to get {FREE_TIER_DAILY_LIMIT} per day, "
                f"or try again tomorrow."
            )
        else:
            msg = (
                f"Free tier limit reached: {limit} custom topic generations/rewords "
                f"per day. Upgrade for unlimited access, or try again tomorrow."
            )
        super().__init__(msg)


def check_and_increment_usage(user) -> int:
    """
    Call this before performing a metered action (generate_puzzle or
    reword_clue) for a LOGGED-IN user. Resets the daily counter if the
    stored date isn't today, then either increments and allows the
    action, or raises UsageLimitExceeded if the free-tier cap is already
    hit.

    Mutates `user` in place (caller is responsible for committing the
    session afterward) and returns the number of free actions remaining
    today AFTER this action, for surfacing to the frontend.
    """
    if user.tier == "paid":
        return -1  # sentinel meaning "unlimited", not a real count

    today = datetime.date.today()
    if user.daily_premium_actions_date != today:
        user.daily_premium_actions_used = 0
        user.daily_premium_actions_date = today

    if user.daily_premium_actions_used >= FREE_TIER_DAILY_LIMIT:
        raise UsageLimitExceeded(FREE_TIER_DAILY_LIMIT)

    user.daily_premium_actions_used += 1
    return FREE_TIER_DAILY_LIMIT - user.daily_premium_actions_used


def check_and_increment_anonymous_usage(anon_usage) -> int:
    """
    Same idea as check_and_increment_usage, but for an AnonymousUsage row
    (no `tier` field -- anonymous visitors are always on the trial
    allowance, never "paid"). Mutates `anon_usage` in place and returns
    remaining trial actions today.
    """
    today = datetime.date.today()
    if anon_usage.daily_actions_date != today:
        anon_usage.daily_actions_used = 0
        anon_usage.daily_actions_date = today

    if anon_usage.daily_actions_used >= ANONYMOUS_TRIAL_DAILY_LIMIT:
        raise UsageLimitExceeded(ANONYMOUS_TRIAL_DAILY_LIMIT, is_anonymous=True)

    anon_usage.daily_actions_used += 1
    return ANONYMOUS_TRIAL_DAILY_LIMIT - anon_usage.daily_actions_used
