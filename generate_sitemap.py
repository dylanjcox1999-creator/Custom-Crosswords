"""
Scans the topics/ output directory and builds a real sitemap.xml -- run
this after generate_seo_page() adds any new page, so the sitemap always
reflects exactly what's actually live, never manually maintained.
"""
import os
import datetime

SITEMAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://topicross.app/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
{entries}</urlset>
"""

ENTRY_TEMPLATE = """  <url>
    <loc>https://topicross.app/topics/{slug}.html</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
"""


def generate_sitemap(topics_dir: str, output_path: str):
    today = datetime.date.today().isoformat()
    slugs = sorted(
        f[:-5] for f in os.listdir(topics_dir)
        if f.endswith(".html")
    )
    entries = "".join(ENTRY_TEMPLATE.format(slug=slug, lastmod=today) for slug in slugs)
    sitemap = SITEMAP_TEMPLATE.format(entries=entries)
    with open(output_path, "w") as f:
        f.write(sitemap)
    return len(slugs)
