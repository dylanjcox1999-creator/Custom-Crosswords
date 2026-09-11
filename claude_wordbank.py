"""
Generates a crossword word bank (word + clue pairs) for an arbitrary
user-supplied topic, using the Claude API.

Requires: ANTHROPIC_API_KEY environment variable.
Install:  pip install anthropic
"""
import os
import json
import re
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

WORD_BANK_PROMPT = """Generate a crossword word bank for the topic "{topic}".

Return ONLY a JSON array (no markdown fences, no preamble, no commentary) of
exactly {n} objects. Each object must have:
  - "word": a single uppercase word, letters only (no spaces, hyphens, or
    punctuation), between 4 and 12 letters long
  - "clue": a concise, accurate, one-sentence crossword-style clue. The clue
    must NOT contain the word itself or an obvious root of it.
  - "hint": a SOFTER, more general version of the clue for a player who is
    stuck -- point them toward the answer more directly than "clue" does,
    without simply restating the word. This is shown as a "help" step before
    the player gives up and reveals the answer outright.

Requirements:
  - All {n} words must be distinct
  - All words must be genuinely and specifically relevant to "{topic}"
  - Prefer common, well-known terms over obscure ones so the puzzle is
    solvable by a general audience
  - Vary word length where possible (this helps the crossword grid interlock)

Return the JSON array only."""


def generate_word_bank(topic: str, n_words: int = 13):
    """
    Calls Claude to generate a word bank for `topic`.
    Returns (entries, hints) where:
      entries -- list of (WORD, clue) tuples, ready for the crossword generator
      hints   -- dict {WORD: hint_text} for the tiered hint system
    Raises ValueError if Claude's response can't be parsed as valid entries.
    """
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[{"role": "user", "content": WORD_BANK_PROMPT.format(topic=topic, n=n_words)}],
    )
    raw_text = "".join(block.text for block in response.content if hasattr(block, "text"))
    raw_text = re.sub(r"```json|```", "", raw_text).strip()

    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude did not return valid JSON: {e}\nRaw response: {raw_text[:500]}")

    cleaned = []
    hints = {}
    seen_words = set()
    for item in items:
        word = re.sub(r"[^A-Z]", "", str(item.get("word", "")).upper())
        clue = str(item.get("clue", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not word or not clue:
            continue
        if word in seen_words:
            continue
        if len(word) < 3:
            continue
        seen_words.add(word)
        cleaned.append((word, clue))
        hints[word] = hint if hint else clue  # fall back to the clue if Claude omitted a hint

    if len(cleaned) < 5:
        raise ValueError(
            f"Claude only returned {len(cleaned)} usable words for topic '{topic}' "
            f"(need at least 5 to build a reasonable grid). Raw response: {raw_text[:500]}"
        )

    return cleaned, hints
