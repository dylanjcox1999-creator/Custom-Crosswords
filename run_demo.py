"""
Demo run of the pipeline for three real long-tail SEO targets. The clue
data below is hand-written and clearly illustrative -- in production this
is the direct output of claude_wordbank.generate_word_bank() + grid
placement, not authored by hand. This script exists to prove the template
and sitemap generator actually produce correct, real output files.
"""
import sys
sys.path.insert(0, '/home/claude/seo_pipeline')
from seo_page_template import generate_seo_page
from generate_sitemap import generate_sitemap
import os

os.makedirs('/home/claude/seo_pipeline/topics', exist_ok=True)

# Illustrative example content -- factually reasonable dog trivia, but
# hand-written for this demo, not live-generated.
DOG_ENTRIES = [
    {"num": 1, "dir": "A", "word": "BEAGLE",   "clue": "Snoopy's breed, known for its keen sense of smell"},
    {"num": 3, "dir": "A", "word": "MUZZLE",   "clue": "The front part of a dog's face, including nose and jaw"},
    {"num": 5, "dir": "A", "word": "RETRIEVER","clue": "Golden or Labrador, a breed bred to fetch downed game"},
    {"num": 7, "dir": "A", "word": "KENNEL",   "clue": "A shelter or boarding facility for dogs"},
    {"num": 2, "dir": "D", "word": "WAG",      "clue": "What a happy tail does"},
    {"num": 4, "dir": "D", "word": "LEASH",    "clue": "Required for a walk in most public parks"},
    {"num": 6, "dir": "D", "word": "PUPPY",    "clue": "A dog under about one year old"},
    {"num": 8, "dir": "D", "word": "BARK",     "clue": "A dog's main vocalization"},
]

TEACHER_ENTRIES = [
    {"num": 1, "dir": "A", "word": "RUBRIC",   "clue": "A scoring guide laying out grading criteria in advance"},
    {"num": 3, "dir": "A", "word": "RECESS",   "clue": "The break students look forward to most"},
    {"num": 5, "dir": "A", "word": "SYLLABUS", "clue": "The document outlining a course's plan for the term"},
    {"num": 2, "dir": "D", "word": "CHALK",    "clue": "Classic classroom writing tool, still used on some boards"},
    {"num": 4, "dir": "D", "word": "TARDY",    "clue": "Word for arriving late to class"},
    {"num": 6, "dir": "D", "word": "QUIZ",     "clue": "A short, lower-stakes test"},
]

BIRTHDAY_ENTRIES = [
    {"num": 1, "dir": "A", "word": "CANDLES",  "clue": "You blow these out and make a wish"},
    {"num": 3, "dir": "A", "word": "CONFETTI", "clue": "Small bits of paper thrown to celebrate"},
    {"num": 2, "dir": "D", "word": "TOAST",    "clue": "A short speech raising a glass to the guest of honor"},
    {"num": 4, "dir": "D", "word": "STREAMER", "clue": "A long strip of decorative paper hung for a party"},
]

pages = [
    ("Dog Lovers", DOG_ENTRIES),
    ("Teachers", TEACHER_ENTRIES),
    ("80th Birthday", BIRTHDAY_ENTRIES),
]

for topic, entries in pages:
    slug, html_out = generate_seo_page(topic, entries)
    with open(f'/home/claude/seo_pipeline/topics/{slug}.html', 'w') as f:
        f.write(html_out)
    print(f"Generated: topics/{slug}.html")

count = generate_sitemap('/home/claude/seo_pipeline/topics', '/home/claude/seo_pipeline/sitemap.xml')
print(f"Sitemap generated with {count} topic pages.")
