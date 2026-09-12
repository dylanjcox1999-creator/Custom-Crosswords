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

from entry_dedup import dedupe_overlapping_clues

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

WORD_BANK_PROMPT = """Generate a crossword word bank for the topic "{topic}" at {difficulty} difficulty.

Return ONLY a JSON array (no markdown fences, no preamble, no commentary) of
exactly {n} objects. Each object must have:
  - "word": a single uppercase word, letters only (no spaces, hyphens, or
    punctuation), between 4 and 12 letters long
  - "clue": a concise, accurate, one-sentence crossword-style clue. The clue
    must NOT contain the word itself or an obvious root of it.

Difficulty guidance for "{difficulty}":
{difficulty_guidance}

Requirements:
  - All {n} words must be distinct
  - All words must be genuinely and specifically relevant to "{topic}"
  - Vary word length where possible (this helps the crossword grid interlock)

Return the JSON array only."""

DIFFICULTY_GUIDANCE = {
    "easy": (
        "Use common, everyday words a general audience would recognize immediately. "
        "Clues should be direct and straightforward, minimal wordplay or ambiguity. "
        "Avoid obscure terminology, technical jargon, or words requiring specialized knowledge."
    ),
    "medium": (
        "Use a mix of common and moderately specific words related to the topic. "
        "Clues can require a bit of thought but shouldn't need expert knowledge."
    ),
    "hard": (
        "Use more specific, advanced, or less common vocabulary related to the topic -- "
        "the kind of terms someone knowledgeable about the subject would know. "
        "Clues can be more indirect, use wordplay, or require making a connection rather "
        "than stating the answer plainly."
    ),
}

VALID_DIFFICULTIES = ("easy", "medium", "hard")


def generate_word_bank(topic: str, n_words: int = 13, difficulty: str = "medium") -> list[tuple[str, str]]:
    """
    Calls Claude to generate a word bank for `topic` at the given `difficulty`.
    Returns a list of (WORD, clue) tuples, ready for the crossword generator.
    Raises ValueError if `difficulty` is invalid or Claude's response can't be
    parsed as valid entries.
    """
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}, got '{difficulty}'")

    prompt = WORD_BANK_PROMPT.format(
        topic=topic, n=n_words, difficulty=difficulty,
        difficulty_guidance=DIFFICULTY_GUIDANCE[difficulty],
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(block.text for block in response.content if hasattr(block, "text"))
    raw_text = re.sub(r"```json|```", "", raw_text).strip()

    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude did not return valid JSON: {e}\nRaw response: {raw_text[:500]}")

    cleaned = []
    seen_words = set()
    for item in items:
        word = re.sub(r"[^A-Z]", "", str(item.get("word", "")).upper())
        clue = str(item.get("clue", "")).strip()
        if not word or not clue:
            continue
        if word in seen_words:
            continue
        if len(word) < 3:
            continue
        seen_words.add(word)
        cleaned.append((word, clue))

    # Safety net: drop any entry whose clue overlaps too much with one
    # already kept (e.g. two words both clued from basically the same fact).
    cleaned = dedupe_overlapping_clues(cleaned)

    if len(cleaned) < 5:
        raise ValueError(
            f"Claude only returned {len(cleaned)} usable words for topic '{topic}' "
            f"(need at least 5 to build a reasonable grid). Raw response: {raw_text[:500]}"
        )

    return cleaned
