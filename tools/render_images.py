#!/usr/bin/env python3
"""Make the picture the email version of an issue needs.

Usage: python3 render_images.py <issues_dir> <YYYY-MM-DD> [fonts_dir]

Opens <issues_dir>/<date>.card.html in a headless browser and saves
<issues_dir>/<date>-card.png, a compact list of the week's changes.
Needs Playwright for Python with Chromium. If the site fonts cannot be downloaded,
pass a folder holding the @fontsource packages (npm i @fontsource/newsreader @fontsource/inter
@fontsource/ibm-plex-mono, then give node_modules/@fontsource) so the picture matches the site.
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

FACES = [("Newsreader", 600, "normal", "newsreader/files/newsreader-latin-600-normal.woff2"),
         ("Newsreader", 500, "italic", "newsreader/files/newsreader-latin-500-italic.woff2"),
         ("Inter", 400, "normal", "inter/files/inter-latin-400-normal.woff2"),
         ("Inter", 600, "normal", "inter/files/inter-latin-600-normal.woff2"),
         ("Inter", 700, "normal", "inter/files/inter-latin-700-normal.woff2"),
         ("IBM Plex Mono", 500, "normal", "ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2")]


def font_css(fonts_dir):
    css = ""
    for family, weight, style, rel in FACES:
        path = os.path.join(fonts_dir, rel)
        if os.path.exists(path):
            b64 = base64.b64encode(open(path, "rb").read()).decode()
            css += f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
    return css


def main(issues_dir, date, fonts_dir=None):
    src = os.path.abspath(os.path.join(issues_dir, date + ".card.html"))
    out = os.path.join(issues_dir, date + "-card.png")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 440, "height": 600}, device_scale_factor=2)
        page.goto("file://" + src)
        if fonts_dir:
            css = font_css(fonts_dir)
            if css:
                page.add_style_tag(content=css)
        page.wait_for_timeout(1200)
        page.locator("#card").screenshot(path=out)
        browser.close()
    print("Wrote", out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:4])
