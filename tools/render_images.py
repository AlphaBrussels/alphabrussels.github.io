#!/usr/bin/env python3
"""Make the two pictures the Substack version of an issue needs.

Usage: python3 render_images.py <issues_dir> <YYYY-MM-DD> [fonts_dir]

Opens <issues_dir>/<date>.html in a headless browser and saves
    <issues_dir>/<date>-table.png   the price table with its bars
    <issues_dir>/<date>-macro.png   the oil, gold, yield and VIX strip
Needs Playwright for Python with Chromium. If the site fonts cannot be downloaded,
pass a folder holding the @fontsource packages (npm i @fontsource/playfair-display
@fontsource/source-sans-3, then give node_modules/@fontsource) so the pictures match the site.
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

FACES = [("Playfair Display", 700, "playfair-display/files/playfair-display-latin-700-normal.woff2"),
         ("Playfair Display", 800, "playfair-display/files/playfair-display-latin-800-normal.woff2"),
         ("Source Sans 3", 400, "source-sans-3/files/source-sans-3-latin-400-normal.woff2"),
         ("Source Sans 3", 600, "source-sans-3/files/source-sans-3-latin-600-normal.woff2"),
         ("Source Sans 3", 700, "source-sans-3/files/source-sans-3-latin-700-normal.woff2")]


def font_css(fonts_dir):
    css = ""
    for family, weight, rel in FACES:
        path = os.path.join(fonts_dir, rel)
        if os.path.exists(path):
            b64 = base64.b64encode(open(path, "rb").read()).decode()
            css += f"@font-face{{font-family:'{family}';font-weight:{weight};src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
    return css


def main(issues_dir, date, fonts_dir=None):
    src = os.path.abspath(os.path.join(issues_dir, date + ".html"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 700, "height": 900}, device_scale_factor=2)
        page.goto("file://" + src)
        if fonts_dir:
            css = font_css(fonts_dir)
            if css:
                page.add_style_tag(content=css)
        page.wait_for_timeout(1200)
        for name in ("table", "macro"):
            box = page.locator("#x-" + name).bounding_box()
            if not box:
                raise SystemExit(f"The issue has no {name} block to picture.")
            pad = 16
            out = os.path.join(issues_dir, f"{date}-{name}.png")
            page.screenshot(path=out, full_page=True, clip={"x": box["x"] - pad, "y": box["y"] - pad,
                                                           "width": box["width"] + 2 * pad, "height": box["height"] + pad + 6})
            print("Wrote", out)
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:4])
