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

# Used when the user supplies their own must-include words/clues (e.g. a
# name, a year, an inside joke for a gift puzzle) and Claude's job is only
# to fill in the REST of the grid around them -- not generate everything.
# See generate_word_bank's `required_entries` param below for the full
# reasoning on why this exists as a hybrid rather than either pure mode.
HYBRID_FILL_PROMPT = """You're helping fill out the rest of a crossword puzzle. \
These entries are ALREADY DECIDED and must not be duplicated or altered -- \
someone chose them deliberately (often something personal: a name, a date, \
an inside joke) and they're already locked into the grid:

{required_list}

{theme_line}

Generate exactly {n_fill} ADDITIONAL word+clue entries to fill out the rest \
of the puzzle, at {difficulty} difficulty ({difficulty_guidance}).

Each additional entry:
  - "word": a single uppercase word, letters only, between 3 and 12 letters
  - "clue": a concise, accurate, one-sentence crossword-style clue that does
    NOT contain the word itself or an obvious root of it
  - Must NOT duplicate any of the required words listed above
  - Should fit the same theme as the required entries and/or the topic given
  - Where possible, share some letters with the required words above (this
    helps them actually interlock into one connected grid, rather than the
    required words sitting isolated with nothing crossing them)

Return ONLY a JSON array (no markdown fences, no preamble, no commentary) of
exactly {n_fill} objects with "word" and "clue" keys."""

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


def _clean_entries(items) -> list[tuple[str, str]]:
    """Shared normalization for both Claude's output and user-supplied
    entries: uppercase letters-only words, non-empty clues, de-duplicated,
    minimum 3 letters. Used so a user-typed word ("Fluffy!") and Claude's
    JSON output both end up in the exact same shape before either touches
    the grid-placement engine, which doesn't know or care which source a
    given entry came from."""
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
    return cleaned


def generate_word_bank(
    topic: str,
    n_words: int = 13,
    difficulty: str = "medium",
    required_entries: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """
    Calls Claude to generate a word bank for `topic` at the given `difficulty`.
    Returns a list of (WORD, clue) tuples, ready for the crossword generator.
    Raises ValueError if `difficulty` is invalid or Claude's response can't be
    parsed as valid entries.

    `required_entries`: optional user-supplied (word, clue) pairs that MUST
    appear in the final puzzle -- e.g. a name, a year, a personal in-joke for
    a gift puzzle. When given, Claude's job changes from "generate everything"
    to "fill in the rest around what's already decided": it's told exactly
    what's locked in and asked only for the remaining words needed to reach
    a full puzzle, ideally ones that share letters with the required words so
    they actually interlock rather than sitting isolated in the grid.

    `topic` may be empty when required_entries covers enough of the puzzle on
    its own -- if there's nothing left to generate (required_entries alone
    already meets the target word count), Claude is never called at all, and
    if there IS something to generate but no topic was given, Claude is asked
    to infer a fitting theme from the required entries themselves rather than
    requiring a separately-typed topic.
    """
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}, got '{difficulty}'")

    required_clean = _clean_entries(
        [{"word": w, "clue": c} for w, c in (required_entries or [])]
    )
    required_words = {w for w, _ in required_clean}

    # Same floor the pure-AI path already enforces (at least 5 usable
    # entries to build a reasonable grid) -- a hybrid puzzle shouldn't be
    # held to a lower bar just because some entries came from the user.
    target_total = max(n_words, 5)
    n_fill = max(0, target_total - len(required_clean))

    if n_fill == 0:
        # The user's own words already cover the puzzle -- skip Claude
        # entirely. Zero marginal generation cost on this path, and it
        # means a fully custom, no-AI puzzle is a real option, not just a
        # theoretical one.
        return required_clean

    if required_clean:
        required_list = "\n".join(f'  - "{w}": {c}' for w, c in required_clean)
        theme_line = (
            f'The overall topic is "{topic}".' if topic and topic.strip()
            else "No explicit topic was given -- infer a fitting theme from "
                 "the required entries above and generate words consistent with it."
        )
        prompt = HYBRID_FILL_PROMPT.format(
            required_list=required_list,
            theme_line=theme_line,
            n_fill=n_fill,
            difficulty=difficulty,
            difficulty_guidance=DIFFICULTY_GUIDANCE[difficulty],
        )
    else:
        if not topic or not topic.strip():
            raise ValueError("topic is required when no required_entries are supplied.")
        prompt = WORD_BANK_PROMPT.format(
            topic=topic, n=n_fill, difficulty=difficulty,
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

    generated = [
        (w, c) for w, c in _clean_entries(items)
        if w not in required_words  # belt-and-suspenders on top of the prompt's own instruction
    ]

    # Required entries first and untouched -- they're what the user
    # actually cares about, so they should never be the ones silently
    # dropped if something downstream (e.g. grid placement) has to trim
    # the list. Overlapping-clue dedup only applies to the generated fill
    # words; the user's own clues are never second-guessed or removed.
    combined = required_clean + dedupe_overlapping_clues(generated)

    if len(combined) < 5:
        raise ValueError(
            f"Only {len(combined)} usable words after generation "
            f"(need at least 5 to build a reasonable grid). Raw response: {raw_text[:500]}"
        )

    return combined
