#!/usr/bin/env python3
"""RETIRED on 19 November 2026: do not run this on the new index.html. The new page already has its
title, description, icons, sharing tags and the real Substack box. Kept for reference only.

Turn the preview page (the Claude artifact's index.html) into the page for the real website.

Usage: python3 make_host_page.py <artifact_index.html> <output_index.html>

The two pages are the same design. The live one differs in four ways: it has a proper
page title, description, icon and sharing preview (social-card.png) for browsers, search
engines and chat apps, the real Substack subscribe box replaces the preview placeholder,
the preview-only tag is removed, and a link ending in ?issue=<date>#newsletter opens that issue.
Run this again whenever the design of the preview page changes.
"""
import re
import sys
from urllib.parse import quote

SITE = "https://alphabrussels.github.io"
SUBSTACK = "https://alphabrussels.substack.com/embed"
TITLE = "Alpha Brussels – Finance & Economics Club"
DESCRIPTION = ("Alpha Brussels is a student finance and economics club in Brussels: talks, workshops, "
               "competitions and a free weekly newsletter on the week in markets.")
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-48 -48 96 96"><rect x="-48" y="-48" width="96" height="96" rx="20" fill="#fff"/>'
        '<polyline points="-30,35 0,-35 30,35" fill="none" stroke="#1F3A5F" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
        '<polyline points="-22,21 -6,7 4,15 22,-7" fill="none" stroke="#E2A82B" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
        '<polyline points="13,-7 23,-8 22,2" fill="none" stroke="#E2A82B" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def main(src, dst):
    page = open(src, encoding="utf-8").read()
    page, n = re.subn(r"<title>.*?</title>\s*", "", page, count=1, flags=re.S)
    assert n == 1, "no <title> found"
    page = re.sub(r'<meta name="claude:viewport-fit-sides"[^>]*>\s*', "", page)
    box = (f'<iframe src="{SUBSTACK}" title="Subscribe to the Alpha Brussels newsletter" loading="lazy" scrolling="no"></iframe>')
    page, n = re.subn(r'<div class="mock">.*?</small></div>', box, page, flags=re.S)
    assert n >= 1, "no subscribe placeholder found"
    # Let a link such as /?issue=2026-11-14#newsletter open that issue (the emails link this way).
    old = "if (!PREVIEW) { try { want = new URLSearchParams(location.search).get('issue'); } catch (err) {} }"
    assert old in page, "issue-link code not found; the site script changed"
    page = page.replace(old, "try { want = new URLSearchParams(location.search).get('issue'); } catch (err) {}")
    esc = TITLE.replace("&", "&amp;")
    head = (f'<title>{esc}</title><meta name="description" content="{DESCRIPTION}">'
            f'<meta property="og:title" content="{esc}"><meta property="og:description" content="{DESCRIPTION}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="Alpha Brussels">'
            f'<meta property="og:url" content="{SITE}/"><link rel="canonical" href="{SITE}/">'
            f'<meta property="og:image" content="{SITE}/social-card.png"><meta property="og:image:width" content="1200">'
            f'<meta property="og:image:height" content="630"><meta property="og:image:alt" content="Alpha Brussels, Finance &amp; Economics Club, Brussels">'
            f'<meta name="twitter:card" content="summary_large_image">'
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(ICON)}">')
    assert "</head>" in page
    # The preview page repeats the charset and viewport tags the page skeleton already has.
    for tag in (r"<meta charset=utf8>\s*", r"<meta name=viewport [^>]*>\s*"):
        first = re.search(tag, page)
        if first:
            page = page[:first.end()] + re.sub(tag, "", page[first.end():])
    page = page.replace("</head>", head + "</head>", 1).replace("<html>", '<html lang="en">', 1)
    open(dst, "w", encoding="utf-8").write(page)
    print(f"Wrote {dst}: {n} subscribe box(es) replaced.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
