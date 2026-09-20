"""
Generates a static, indexable landing page for a single crossword topic.

WHY THIS EXISTS: TopiCross is a single-page app -- every topic anyone could
ever search for ("crossword about dogs", "birthday crossword maker") lives
behind the exact same URL (index.html), with content that only appears
after a JS fetch() call. Google has nothing distinct to index per topic.
This script produces a REAL, separate, crawlable HTML file per topic --
real clue text in the HTML itself, a unique URL, unique meta tags -- so
each one can actually rank for its own search terms.

This is the CORE of the pipeline; generate_sitemap.py builds the sitemap
from whatever pages exist in the output directory, and a scheduled job
(not included here -- see the accompanying writeup) would call this
automatically for new topics over time, using the real puzzle-generation
engine (claude_wordbank.generate_word_bank) as the `entries` input instead
of hand-written example data.
"""
import re
import html as html_lib

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{meta_description}">
<link rel="canonical" href="https://topicross.app/topics/{slug}.html">

<meta property="og:type" content="website">
<meta property="og:site_name" content="TopiCross">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{meta_description}">
<meta property="og:url" content="https://topicross.app/topics/{slug}.html">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{meta_description}">

<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&display=swap" rel="stylesheet">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Game",
  "name": "{schema_name}",
  "description": "{meta_description}",
  "genre": "Crossword Puzzle",
  "url": "https://topicross.app/topics/{slug}.html",
  "publisher": {{
    "@type": "Organization",
    "name": "TopiCross",
    "url": "https://topicross.app"
  }}
}}
</script>

<style>
  :root {{ --navy:#152A47; --gold:#B08D57; --cream:#F5F1E8; --ink:#1C1C1A; --paper:#FBF9F4; --rule:rgba(176,141,87,0.35); }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: var(--cream); color: var(--ink); margin:0; padding: 24px 20px 60px; max-width: 720px; margin: 0 auto; }}
  h1 {{ font-family: 'Fraunces', Georgia, serif; font-weight: 600; color: var(--navy); font-size: 1.9em; margin: 4px 0 8px; }}
  .intro {{ color: #6b6558; font-size: 0.95em; margin-bottom: 24px; line-height: 1.5; }}
  .section {{ background: var(--paper); border-radius: 3px; border-top: 3px solid var(--gold); padding: 20px 18px; margin-bottom: 22px; }}
  .section h2 {{ font-family: 'Fraunces', Georgia, serif; font-weight: 600; color: var(--navy); font-size: 1.15em; margin-top: 0; border-bottom: 1px solid var(--rule); padding-bottom: 10px; margin-bottom: 14px; }}
  .clue-col {{ margin-bottom: 18px; }}
  .clue-col h3 {{ font-family: 'Fraunces', Georgia, serif; color: var(--gold); font-size: 1em; margin-bottom: 8px; }}
  .clue-row {{ font-size: 0.92em; margin-bottom: 6px; line-height: 1.4; }}
  .clue-row b {{ color: var(--navy); }}
  .cta {{ text-align: center; padding: 28px 18px; }}
  .cta a {{ display: inline-block; background: var(--navy); color: white; text-decoration: none; padding: 12px 28px; border-radius: 4px; font-weight: 600; }}
  .cta p {{ color: #6b6558; font-size: 0.88em; margin-top: 10px; }}
</style>
</head>
<body>

<h1>{h1}</h1>
<p class="intro">{intro}</p>

<div class="section">
  <h2>Sample clues</h2>
  <div class="clue-col">
    <h3>Across</h3>
    {across_html}
  </div>
  <div class="clue-col">
    <h3>Down</h3>
    {down_html}
  </div>
</div>

<div class="cta">
  <a href="https://topicross.app/?topic={topic_url_encoded}">Generate your own {topic} puzzle</a>
  <p>Every TopiCross puzzle is freshly generated -- yours won't be identical to this one, but it'll be just as real.</p>
</div>

</body>
</html>
"""


def slugify(topic: str) -> str:
    slug = topic.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def render_clue_rows(entries: list[dict]) -> str:
    rows = []
    for e in entries:
        rows.append(
            f'<div class="clue-row"><b>{e["num"]}.</b> {html_lib.escape(e["clue"])} '
            f'<span style="color:#a5a096;">({len(e["word"])} letters)</span></div>'
        )
    return "\n    ".join(rows)


def generate_seo_page(topic: str, entries: list[dict], meta_description: str | None = None) -> tuple[str, str]:
    """
    entries: list of {"num": int, "dir": "A"|"D", "word": str, "clue": str}
    -- in production, this is exactly the output shape of
    claude_wordbank.generate_word_bank() + the grid placement step, not
    hand-written data. Returns (slug, full_html).
    """
    slug = slugify(topic)
    across = [e for e in entries if e["dir"] == "A"]
    down = [e for e in entries if e["dir"] == "D"]

    meta_description = meta_description or (
        f"Generate a free crossword puzzle about {topic} in seconds. "
        f"Real, solvable puzzles on any topic you want -- powered by AI, playable instantly."
    )

    html_out = PAGE_TEMPLATE.format(
        title=f"{topic} Crossword Puzzle — Generate One Free | TopiCross",
        meta_description=meta_description,
        schema_name=f"{topic} Crossword Puzzle",
        slug=slug,
        h1=f"{topic} Crossword Puzzle Generator",
        intro=(
            f"Want a crossword puzzle about {topic.lower()}? TopiCross generates one for you in seconds -- "
            f"not a pre-made puzzle from a fixed library, a real one built specifically around your topic. "
            f"Here's a sample of the kind of clues you'd get:"
        ),
        across_html=render_clue_rows(across),
        down_html=render_clue_rows(down),
        topic=html_lib.escape(topic),
        topic_url_encoded=topic.replace(" ", "+"),
    )
    return slug, html_out
