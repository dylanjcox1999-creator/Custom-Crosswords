"""
Rewrites a clue in plainer, more universally accessible language --
removing assumed cultural references, era-specific slang, or niche
terminology a player might not recognize -- WITHOUT making the puzzle any
easier to solve.

Named "reword" rather than "simplify": the feature offers an alternate
phrasing of the same difficulty, not an easier clue. "Simplify" implied a
difficulty reduction it was never meant to deliver, which is exactly what
made it feel broken in testing even once it was working as designed.

This is deliberately distinct from the hint system: a hint is meant to
help a stuck player get closer to the answer. Rewording is meant to help
a player who understands the *concept* but is tripped up by *how the clue
is worded* -- e.g. a clue built around a decades-old celebrity nickname,
or slang a younger or non-native-English-speaking player might not know.
The reworded clue requires the same amount of actual knowledge/reasoning
to solve, just expressed in more universally understood language.

Deliberately kept separate from the hint tiers rather than folded into
them: a hint tier is supposed to give genuine solving help (that's what
fixed the original "punitive coin-gated hints" complaint this project
started from). A same-difficulty reword doesn't help you solve the puzzle
faster, so merging it into hint tier 1 would make that first hint tier
less useful, not more -- these are two different needs (understand the
wording vs. get help solving) that happen to use a similar mechanism.

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

REWORD_PROMPT = """Here is a crossword clue and its answer:

Clue: "{clue}"
Answer: {word}

Rewrite this clue in plainer, more universally accessible language -- assume the player may not recognize specific cultural references, era-specific slang, celebrity nicknames, or niche terminology, even ones that seem common to you. Replace them with more widely understood phrasing or add brief context.

You must produce a genuinely different rewrite, not the original clue restated. Do not simply return the input unchanged -- there is almost always a way to phrase something more plainly, even if it's a small change.

Requirements the rewrite must still follow:
- Requires the SAME amount of knowledge/reasoning to solve as the original -- do not make it easier or more revealing
- Does not include the answer word (or an obvious variant of it)
- A single, natural sentence, roughly similar length to the original

Return ONLY the rewritten clue text, nothing else -- no quotes, no explanation, no JSON."""


def reword_clue(word: str, clue: str) -> dict:
    """Returns {"original": clue, "reworded": str, "changed": bool}.
    On any failure, returns the original clue unchanged (changed=False)
    rather than erroring -- worse to break clue display than to just not
    reword it this time."""
    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": REWORD_PROMPT.format(clue=clue, word=word),
            }],
        )
        raw_text = "".join(b.text for b in response.content if hasattr(b, "text"))
        reworded = raw_text.strip().strip('"')

        # Basic sanity checks -- if Claude's output looks broken, fall back
        # to the original rather than show something worse than what we had.
        if not reworded or len(reworded) < 10:
            return {"original": clue, "reworded": clue, "changed": False}
        if word.upper() in reworded.upper():
            return {"original": clue, "reworded": clue, "changed": False}

        return {
            "original": clue,
            "reworded": reworded,
            "changed": reworded.strip() != clue.strip(),
        }
    except Exception:
        return {"original": clue, "reworded": clue, "changed": False}
