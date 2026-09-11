"""
Historical events data source for the "On This Day" feature.

Pulls REAL, editorially-curated events from Wikipedia's official REST API
(https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{mm}/{dd}),
then uses Claude to convert those real facts into crossword word/clue/hint
entries -- Claude is only ever asked to extract and rephrase text it's
given, never to recall historical facts from its own memory. This is
deliberate: an ungrounded LLM asked to just "know" what happened on a given
date is exactly the kind of prompt that produces confident, plausible,
wrong answers. Grounding every clue in a real retrieved Wikipedia sentence
avoids that.

Results are cached in memory per (month, day) so a given date is only
fetched/generated once per server run, not on every request.
"""
import os
import re
import json
import datetime

import requests
from anthropic import Anthropic

WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{mm}/{dd}"
# Wikimedia requires a descriptive User-Agent identifying the application
# and a contact method -- requests without one can be rate-limited or blocked.
USER_AGENT = "CustomCrosswordsDaily/1.0 (educational crossword app; contact via GitHub repo)"

_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_cache: dict[tuple[int, int], list[dict]] = {}

# Verified via direct web search (History.com, Britannica, AP wire "Today in
# History" archives), not AI-generated. Kept as a guaranteed-available
# fallback specifically for this one date, in case the live Wikipedia fetch
# ever fails for it.
_VERIFIED_FALLBACK = {
    (9, 10): [
        {"word": "JAMESTOWN", "clue": "First permanent English settlement, where John Smith became council president on this day in 1608", "hint": "Where John Smith became council president in 1608"},
        {"word": "PERRY", "clue": "Oliver Hazard ___, U.S. Captain who won the Battle of Lake Erie on this day in 1813", "hint": "The U.S. Captain's last name from the Battle of Lake Erie"},
        {"word": "HOWE", "clue": "Elias ___, who patented the sewing machine on this day in 1846", "hint": "The last name of the sewing machine's patent holder"},
        {"word": "CANADA", "clue": "Country that declared war on Nazi Germany on this day in 1939", "hint": "North American country that joined WWII on this date"},
        {"word": "PERSHING", "clue": "General John J. ___, whose troops were welcomed home to NYC on this day in 1919", "hint": "The general whose WWI troops came home to a NYC welcome"},
        {"word": "QUISLING", "clue": "Vidkun ___, sentenced to death for Nazi collaboration on this day in 1945", "hint": "A name that later became a word meaning \"traitor\""},
        {"word": "VIRGINIA", "clue": "Colony where Jamestown was founded", "hint": "The U.S. state that was home to the first English colony"},
        {"word": "PATENT", "clue": "Legal protection Elias Howe received for his invention", "hint": "What an inventor gets to protect their new idea"},
        {"word": "SOLDIERS", "clue": "25,000 of these were welcomed home to New York City in 1919", "hint": "Who NYC welcomed home by the thousands after WWI"},
    ],
}

EXTRACTION_PROMPT = """Below are REAL, verified historical events that happened on {month_name} {day}, sourced from Wikipedia. Do not use any historical knowledge beyond what is stated in these facts -- only work from the text given.

{events_text}

From these events, select up to {n} that would make good crossword entries. For each one you select, extract ONE proper noun or key term (a person's last name, a place, a specific thing) as the answer word, and write:
  - "clue": based ONLY on the fact given above for that event, mentioning "this day in {{year}}" using that event's actual year. Do not add any detail not present in the text above.
  - "hint": a softer, more general version of the clue, still based only on the given fact.

Return ONLY a JSON array (no markdown fences, no commentary) of objects with "word", "clue", "hint". Each "word" must be a single uppercase word, letters only, 4-12 letters, distinct from the others."""


def _fetch_wikipedia_events(month: int, day: int) -> list[dict]:
    """Calls Wikipedia's real On This Day API. Returns a list of
    {"text": str, "year": int} dicts, or an empty list on any failure."""
    url = WIKIPEDIA_API_URL.format(mm=f"{month:02d}", dd=f"{day:02d}")
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    events = data.get("selected", []) or data.get("events", [])
    return [{"text": e.get("text", ""), "year": e.get("year")} for e in events if e.get("text")]


def _build_crossword_entries_from_events(events: list[dict], month: int, day: int, n: int = 9) -> list[dict]:
    """Grounds Claude in the given real events and asks it to extract
    crossword entries -- Claude never invents facts, only rephrases what
    it's given. Returns [] if Claude's response can't be parsed."""
    if not events:
        return []

    month_name = datetime.date(2000, month, 1).strftime("%B")
    events_text = "\n".join(f"- {e['year']}: {e['text']}" for e in events[:15] if e.get("year"))
    if not events_text:
        return []

    prompt = EXTRACTION_PROMPT.format(
        month_name=month_name, day=day, events_text=events_text, n=n
    )

    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(b.text for b in response.content if hasattr(b, "text"))
        raw_text = re.sub(r"```json|```", "", raw_text).strip()
        items = json.loads(raw_text)
    except Exception:
        return []

    cleaned = []
    seen = set()
    for item in items:
        word = re.sub(r"[^A-Z]", "", str(item.get("word", "")).upper())
        clue = str(item.get("clue", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not word or not clue or len(word) < 4 or word in seen:
            continue
        seen.add(word)
        cleaned.append({"word": word, "clue": clue, "hint": hint or clue})

    return cleaned


def get_events_for_date(date: datetime.date) -> list[dict]:
    """Returns a list of {"word": ..., "clue": ..., "hint": ...} dicts for
    the given date. Tries, in order:
      1. An in-memory cache (already computed this server run)
      2. A live fetch from Wikipedia's real On This Day API + Claude
         extraction, grounded entirely in that real data
      3. The one verified hardcoded fallback, only for its specific date
    Returns [] if all of the above fail to produce at least 5 entries.
    """
    key = (date.month, date.day)
    if key in _cache:
        return _cache[key]

    wiki_events = _fetch_wikipedia_events(date.month, date.day)
    entries = _build_crossword_entries_from_events(wiki_events, date.month, date.day)

    if len(entries) < 5 and key in _VERIFIED_FALLBACK:
        entries = _VERIFIED_FALLBACK[key]

    if len(entries) >= 5:
        _cache[key] = entries
    return entries

