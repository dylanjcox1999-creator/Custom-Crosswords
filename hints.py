"""
Three-tier hint system.

Tier 1 (soft):    a more direct, rephrased version of the clue
Tier 2 (letters): first letter + word length, no semantic help
Tier 3 (reveal):  the full answer

Design intent: this replaces the "pay coins to see your mistake" pattern
that was the single most-complained-about issue in the competitor research
this product is responding to. Tier 1 and 2 should be free or near-free;
Tier 3 is the only one that "costs" anything meaningful, and even that is
a choice the player makes, not a paywall blocking them mid-puzzle.
"""

VALID_TIERS = (1, 2, 3)


def get_hint(word: str, clue: str, soft_hint: str, tier: int) -> dict:
    """
    Returns {"tier": int, "text": str, "is_reveal": bool} for the requested
    hint tier. Raises ValueError for an invalid tier.
    """
    word = word.upper().strip()
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier}")

    if tier == 1:
        return {"tier": 1, "text": soft_hint or clue, "is_reveal": False}

    if tier == 2:
        return {
            "tier": 2,
            "text": f"Starts with \"{word[0]}\" — {len(word)} letters",
            "is_reveal": False,
        }

    # tier == 3
    return {"tier": 3, "text": word, "is_reveal": True}


def next_tier(current_tier: int) -> int | None:
    """Given the tier a player just used, returns the next tier up, or None
    if they've already reached the full reveal."""
    if current_tier is None:
        return 1
    if current_tier >= 3:
        return None
    return current_tier + 1
