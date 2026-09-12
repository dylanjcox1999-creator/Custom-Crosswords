"""
Suggests crossword topics to a user based on their play history -- or a
diverse starter set if they have none yet.

Unlike the original competitor app's approach (recommend from a fixed
catalog of ~200 pre-built topic packs), this app lets users type ANY
topic, so there's no catalog to recommend from. Instead, Claude looks at
patterns in what the user has actually played (and, as a rough proxy for
"did they enjoy it", how few hints they needed and whether they finished)
and suggests new, related topic ideas -- not identical to what they've
already played.
"""
import os
import json
import re

from anthropic import Anthropic

_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Shown to a user with no play history yet, or if the live recommendation
# call fails for any reason -- deliberately diverse across very different
# subject areas so there's a reasonable chance something appeals.
COLD_START_TOPICS = [
    "national parks",
    "classic rock bands",
    "ancient Rome",
    "coffee and tea",
    "board games",
    "world capitals",
    "jazz music",
    "dinosaurs",
]

RECOMMEND_PROMPT = """A crossword app player has this play history (topic, and roughly how well they did):

{history_text}

Based on patterns in what they've played -- genres, subjects, or themes they seem drawn to -- suggest {n} NEW topic ideas they haven't played yet that they would likely enjoy. Prefer topics that are genuinely related to their history but not identical or near-identical to any topic already listed above.

Return ONLY a JSON array of {n} short topic strings (2-4 words each, lowercase, no explanation), for example: ["topic one", "topic two"]."""


def _format_history(records: list[dict]) -> str:
    lines = []
    for r in records:
        if r.get("hints_used", 0) <= 1 and r.get("completed", True):
            performance = "enjoyed, did well"
        elif r.get("hints_used", 0) > 2 or not r.get("completed", True):
            performance = "struggled a bit"
        else:
            performance = "moderate"
        lines.append(f"- {r['topic']} ({performance})")
    return "\n".join(lines)


def recommend_topics(play_history: list[dict], n: int = 5) -> list[str]:
    """
    play_history: list of {"topic": str, "hints_used": int, "completed": bool},
    ideally one representative entry per topic already played.

    Returns a list of up to `n` suggested topic strings. Falls back to a
    fixed diverse starter set if there's no history yet, or if the live
    call fails or its response can't be parsed into at least 3 usable
    topics -- this always returns *something* usable, never an error.
    """
    if not play_history:
        return COLD_START_TOPICS[:n]

    history_text = _format_history(play_history)
    prompt = RECOMMEND_PROMPT.format(history_text=history_text, n=n)

    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(b.text for b in response.content if hasattr(b, "text"))
        raw_text = re.sub(r"```json|```", "", raw_text).strip()
        topics = json.loads(raw_text)
        cleaned = [str(t).strip() for t in topics if str(t).strip()]
        if len(cleaned) >= 3:
            return cleaned[:n]
    except Exception:
        pass

    return COLD_START_TOPICS[:n]
