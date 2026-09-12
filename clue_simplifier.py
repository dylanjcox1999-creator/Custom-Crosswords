"""
Rephrases a clue to be more accessible -- removing assumed cultural
references, era-specific slang, or niche terminology a player might not
recognize -- WITHOUT making the puzzle any easier to solve.

This is deliberately distinct from the hint system: a hint is meant to
help a stuck player get closer to the answer. Simplification is meant to
help a player who understands the *concept* but is tripped up by *how the
clue is worded* -- e.g. a clue built around a decades-old celebrity
nickname, or slang a younger or non-native-English-speaking player might
not know. The simplified clue should require the same amount of actual
knowledge/reasoning to solve, just expressed in more universally
understood language.

This is a real, direct answer to one of the accessibility gaps identified
early in this project: the original competitor app explicitly markets
itself as "designed for seniors," but offers no way to handle a clue that
assumes cultural context a given player might not have.
"""
import os
import json
import re

from anthropic import Anthropic

_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SIMPLIFY_PROMPT = """Here is a crossword clue and its answer:

Clue: "{clue}"
Answer: {word}

Rewrite this clue in plainer, more universally accessible language -- assume the player may not recognize specific cultural references, era-specific slang, celebrity nicknames, or niche terminology, even ones that seem common to you. Replace them with more widely understood phrasing or add brief context.

You must produce a genuinely different rewrite, not the original clue restated. Do not simply return the input unchanged -- there is almost always a way to phrase something more plainly, even if it's a small change.

Requirements the rewrite must still follow:
- Requires the SAME amount of knowledge/reasoning to solve as the original -- do not make it easier or more revealing
- Does not include the answer word (or an obvious variant of it)
- A single, natural sentence, roughly similar length to the original

Return ONLY the rewritten clue text, nothing else -- no quotes, no explanation, no JSON."""


def simplify_clue(word: str, clue: str) -> dict:
    """Returns {"original": clue, "simplified": str, "changed": bool}.
    On any failure, returns the original clue unchanged (changed=False)
    rather than erroring -- worse to break clue display than to just not
    simplify it this time."""
    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": SIMPLIFY_PROMPT.format(clue=clue, word=word),
            }],
        )
        raw_text = "".join(b.text for b in response.content if hasattr(b, "text"))
        simplified = raw_text.strip().strip('"')

        # Basic sanity checks -- if Claude's output looks broken, fall back
        # to the original rather than show something worse than what we had.
        if not simplified or len(simplified) < 10:
            return {"original": clue, "simplified": clue, "changed": False}
        if word.upper() in simplified.upper():
            return {"original": clue, "simplified": clue, "changed": False}

        return {
            "original": clue,
            "simplified": simplified,
            "changed": simplified.strip() != clue.strip(),
        }
    except Exception:
        return {"original": clue, "simplified": clue, "changed": False}
