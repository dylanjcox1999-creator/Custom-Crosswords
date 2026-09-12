"""
Detects and removes crossword entries whose clues overlap too much with an
already-accepted entry -- specifically the case where two different answer
words both got pulled from the same underlying fact/event, producing two
clues that read almost identically but point to different answers. That's
confusing in a real crossword and shouldn't ship.

Two entries are considered overlapping if either:
  1. Their clue text is a near-exact match after normalizing whitespace/
     punctuation/case, or
  2. They mention the same 4-digit year AND their clue text is otherwise
     highly similar (a strong signal they're describing the same event).
"""
import re
import difflib

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})s?\b")  # also matches decade forms like "1850s"

_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "at",
    "this", "day", "was", "is", "who", "which", "that", "its", "his",
    "her", "with", "by", "as", "from",
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)  # strip punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_year(text: str) -> str | None:
    m = _YEAR_RE.search(text)
    return m.group(0).rstrip("s") if m else None  # normalize "1850s" and "1850" to the same key


def _content_word_overlap(norm_a: str, norm_b: str) -> float:
    """Fraction of the smaller clue's meaningful (non-stopword) words that
    also appear in the other clue -- catches reworded-but-same-fact clues
    that character-level diffing can miss. Strips a trailing 's' for a
    crude singular/plural match (e.g. "island" / "islands")."""
    def stem(w):
        return w[:-1] if w.endswith("s") and len(w) > 3 else w

    words_a = {stem(w) for w in norm_a.split() if w not in _STOPWORDS and len(w) > 2}
    words_b = {stem(w) for w in norm_b.split() if w not in _STOPWORDS and len(w) > 2}
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / min(len(words_a), len(words_b))


def _clues_overlap(clue_a: str, clue_b: str) -> bool:
    norm_a, norm_b = _normalize(clue_a), _normalize(clue_b)
    if norm_a == norm_b:
        return True

    char_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    if char_ratio >= 0.85:
        return True

    word_overlap = _content_word_overlap(norm_a, norm_b)
    year_a, year_b = _extract_year(clue_a), _extract_year(clue_b)
    same_year = bool(year_a) and year_a == year_b

    # Two different signals, either is enough on its own:
    #   - same year mentioned + meaningfully overlapping vocabulary
    #   - no year info available, but heavy shared vocabulary regardless
    #     (catches cases where neither clue happens to state a year)
    if same_year and word_overlap >= 0.35:
        return True
    if word_overlap >= 0.7:
        return True

    return False


def dedupe_overlapping_clues(entries: list[dict]) -> list[dict]:
    """Takes a list of {"word", "clue", "hint"} dicts (or (word, clue) tuples
    -- both are handled) and returns a filtered list with no two entries
    whose clues overlap per _clues_overlap(). Keeps the first occurrence,
    drops later ones that overlap with an already-kept entry."""
    kept = []
    for entry in entries:
        clue = entry["clue"] if isinstance(entry, dict) else entry[1]
        if any(_clues_overlap(clue, (k["clue"] if isinstance(k, dict) else k[1])) for k in kept):
            continue
        kept.append(entry)
    return kept
