"""
Three-tier hint system.

Tier 1 (letters): first letter only
Tier 2 (letters): first letter + last letter (cumulative -- builds on tier 1
                   rather than replacing it, so a player who already used
                   tier 1 doesn't lose that information)
Tier 3 (reveal):  the full answer

Rebuilt from an earlier version where tier 1 was a softer, rephrased
version of the clue -- that overlapped too much in function with the
separate "Reword" feature (clue_rewriter.py), which also rephrases the
clue. This version keeps hints purely letter-based, with zero dependency
on clue text or an LLM call -- entirely deterministic, entirely free to
compute, no API cost per hint.

Design intent (unchanged from the original version): this replaces the
"pay coins to see your mistake" pattern that was the single
most-complained-about issue in the competitor research this product is
responding to. Tier 1 and 2 should be free or near-free; Tier 3 is the
only one that "costs" anything meaningful, and even that is a choice the
player makes, not a paywall blocking them mid-puzzle.
"""

VALID_TIERS = (1, 2, 3)


def get_hint(word: str, tier: int) -> dict:
    """
    Returns {"tier": int, "text": str, "is_reveal": bool} for the requested
    hint tier. Raises ValueError for an invalid tier or an empty word.
    """
    word = word.upper().strip()
    if not word:
        raise ValueError("word cannot be empty")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier}")

    if tier == 1:
        return {"tier": 1, "text": f"Starts with \"{word[0]}\"", "is_reveal": False}

    if tier == 2:
        return {
            "tier": 2,
            "text": f"Starts with \"{word[0]}\", ends with \"{word[-1]}\"",
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
