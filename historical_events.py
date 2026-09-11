"""
Historical events data source for the "On This Day" feature.

IMPORTANT / HONEST LIMITATION:
This module currently contains a small, manually-verified sample dataset
(seeded via web search, not AI-generated) for a couple of demonstration
dates. It is NOT a complete, year-round historical events database.

For production, replace `get_events_for_date()` with a call to a real,
maintained historical-events source -- for example:
  - Wikipedia's "On this day" REST API
  - A licensed history/almanac data provider
  - A curated internal database you build and fact-check over time

Do NOT generate "on this day" facts purely from an LLM with no grounding
source -- historical dates and facts are exactly the kind of content
where an ungrounded model can confidently hallucinate plausible-sounding
but wrong events, which is a real risk for a product like this.
"""
import datetime

# Verified via direct web search (History.com, Britannica, AP wire
# "Today in History" archives), not AI-generated.
_SAMPLE_EVENTS = {
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


def get_events_for_date(date: datetime.date) -> list[dict]:
    """Returns a list of {"word": ..., "clue": ..., "hint": ...} dicts for the
    given date, or an empty list if no data is available for that date.

    Replace this function body with a real API/database call for production.
    """
    return _SAMPLE_EVENTS.get((date.month, date.day), [])
