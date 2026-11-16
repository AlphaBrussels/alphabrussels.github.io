#!/usr/bin/env python3
"""Alpha Brussels weekly newsletter builder.

Usage:
    python3 build_issue.py <issues_dir> <YYYY-MM-DD>            build + update issues.json
    python3 build_issue.py <issues_dir> <YYYY-MM-DD> --draft    build a preview for approval
    python3 build_issue.py <issues_dir> <YYYY-MM-DD> --check    verify only, write nothing
    add --verbose to list the checks skipped for a legacy issue

Reads   <issues_dir>/<date>.md          the text of the issue (edit this freely)
        <issues_dir>/<date>.data.json   prices and the list of sources
Writes  <issues_dir>/<date>.html        the finished issue, in the site design
        <issues_dir>/issues.json        the list the website reads (newest first)
        <issues_dir>/<date>.substack.html   the short email version for Substack: the
                                        "## Email brief" bullets, a picture of the
                                        week's changes and a button to the full issue
        <issues_dir>/<date>.card.html       that picture as a page (run render_images.py
                                        afterwards to turn it into <date>-card.png)
With --draft it writes none of these. It puts a self-contained preview, plus copies of
the two source files, in a "drafts" folder next to <issues_dir>. The website does
not read that folder, so nothing changes for visitors until a normal build.

What it guarantees before it writes anything:
  * every weekly change is calculated here from two closing prices, never typed in
  * every price has a primary source and a second, independent source that agrees
  * this week's "previous close" matches the close published in last week's issue
  * every paragraph, bullet and calendar line ends with a citation (the email
    brief too: its facts are checked like the rest, the email just hides the numbers)
  * every citation points at a source that exists, from an approved outlet
  * every number in the text appears in a quote stored from the source it cites
  * citations are numbered in reading order and the source list is rebuilt, so
    editing, moving or deleting text renumbers everything automatically

An issue marked "legacy": true in its data file (issue 1 only) reports the
second-source, quote and outlet checks as warnings instead of errors.
"""
import base64
import datetime
import html
import json
import os
import re
import sys
from urllib.parse import urlparse

# ---------------------------------------------------------------- source policy
DATA_DOMAINS = [  # price and official data
    "finance.yahoo.com", "stoxx.com", "euronext.com", "nasdaq.com", "nyse.com",
    "spglobal.com", "cboe.com", "cmegroup.com", "lseg.com", "londonstockexchange.com",
    "deutsche-boerse.com", "boerse-frankfurt.de", "jpx.co.jp", "hkex.com.hk",
    "twse.com.tw", "krx.co.kr", "investing.com", "stockanalysis.com", "marketwatch.com",
    "federalreserve.gov", "treasury.gov", "bls.gov", "bea.gov", "sec.gov", "eia.gov",
    "ecb.europa.eu", "ec.europa.eu", "europa.eu", "nbb.be", "statbel.fgov.be",
    "bankofengland.co.uk", "ons.gov.uk", "imf.org", "oecd.org", "bis.org",
]
NEWS_DOMAINS = [  # established newsrooms
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
    "economist.com", "nytimes.com", "bbc.com", "bbc.co.uk", "theguardian.com",
    "barrons.com", "cnn.com", "euronews.com", "politico.eu", "lecho.be", "tijd.be",
    "lalibre.be", "lesoir.be", "standaard.be", "rtbf.be", "vrt.be", "nikkei.com",
    "scmp.com", "handelsblatt.com", "lesechos.fr", "lemonde.fr", "bnnbloomberg.ca",
]
WIRES = ["Associated Press", "Reuters", "AFP", "Bloomberg", "Belga"]

NAVY, GOLD, UP, DOWN = "#1F3A5F", "#E2A82B", "#1E8A4C", "#C0392B"
SITE_URL = "https://alphabrussels.github.io"
MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
TERMS = ["S&P 500", "S&P 100", "STOXX Europe 600", "STOXX 600", "BEL 20", "CAC 40",
         "FTSE 100", "FTSE 250", "Nikkei 225", "Russell 2000", "Nasdaq 100",
         "Euro Stoxx 50", "DAX 40", "CSI 300", "10-year", "2-year", "30-year",
         "5-year", "G7", "G20", "COP31", "Q1", "Q2", "Q3", "Q4"]
CITE = re.compile(r"\[@([a-z0-9][a-z0-9-]*)\]")
CITE_RUN = re.compile(r"((?:\[@[a-z0-9][a-z0-9-]*\]\s*)+)")
NUM = re.compile(r"(?<![A-Za-z\d.,])\d[\d,]*(?:\.\d+)?")


def host_of(url):
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def in_list(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


class Report:
    def __init__(self, legacy):
        self.legacy, self.errors, self.warnings, self.skipped = legacy, [], [], []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def strict(self, msg):
        """A check that is an error for every issue except a legacy one."""
        target = self.skipped if self.legacy else self.errors
        if msg not in target:
            target.append(msg)


# ---------------------------------------------------------------- parsing
def parse_md(text):
    m = re.match(r"\s*---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        raise SystemExit("The .md file must start with a --- header block.")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    sections, cur, spot = [], None, None
    for raw in re.split(r"\n\s*\n", m.group(2).strip()):
        blk = raw.strip()
        if not blk:
            continue
        if blk.startswith("## "):
            cur = {"title": blk[3:].strip(), "blocks": []}
            sections.append(cur)
            spot = None
            continue
        if cur is None:
            raise SystemExit("Text found before the first '## ' section heading.")
        target = spot["blocks"] if spot else cur["blocks"]
        sm = re.match(r"\[\[spotlight:\s*(.+?)\]\]$", blk)
        lines = [l.strip() for l in blk.splitlines()]
        if blk in ("[[table]]", "[[macro]]"):
            target.append({"type": blk[2:-2]})
        elif sm:
            spot = {"type": "spotlight", "title": sm.group(1), "blocks": []}
            cur["blocks"].append(spot)
        elif blk == "[[/spotlight]]":
            spot = None
        elif lines[0].startswith("- "):
            items = []
            for l in lines:
                if l.startswith("- "):
                    items.append(l[2:])
                else:
                    items[-1] += " " + l
            if all(" | " in i for i in items):
                target.append({"type": "rows", "rows": [[p.strip() for p in i.split(" | ")] for i in items]})
            else:
                target.append({"type": "bullets", "items": items})
        else:
            joined = " ".join(lines)
            for prefix, kind in (("> ", "callout"), ("note: ", "note"), ("plain: ", "plain")):
                if joined.startswith(prefix):
                    target.append({"type": kind, "text": joined[len(prefix):].strip()})
                    break
            else:
                target.append({"type": "para", "text": joined})
    return meta, sections


def walk_text(sections):
    """Yield (where, text) for every piece of prose that must carry a citation."""
    def blocks(bs, where):
        for b in bs:
            t = b["type"]
            if t in ("para", "callout", "note"):
                yield where, b["text"]
            elif t == "bullets":
                for i in b["items"]:
                    yield where, i
            elif t == "rows":
                for r in b["rows"]:
                    yield where + " / " + r[0], " ".join(r[1:])
            elif t == "spotlight":
                yield from blocks(b["blocks"], where + " / " + b["title"])
    for s in sections:
        yield from blocks(s["blocks"], s["title"])


# ---------------------------------------------------------------- numbers
def fnum(x, decimals=2, prefix=""):
    return prefix + f"{x:,.{decimals}f}"


def fpct(p):
    return ("+" if p >= 0 else "−") + f"{abs(p):.1f}%"


def numbers_in(text):
    out = set()
    for m in NUM.finditer(text):
        try:
            out.add(round(float(m.group(0).replace(",", "")), 6))
        except ValueError:
            pass
    return out


def claim_numbers(text):
    """Numbers in a piece of text that a source has to back up (dates and index names excluded)."""
    t = text.replace("**", "")
    for term in TERMS:
        t = t.replace(term, " ")
    t = re.sub(r"\b\d{1,2}(?:\s*[–-]\s*\d{1,2})?\s+(?:%s)\b" % MONTHS, " ", t)      # 13 November, 18–19 Nov
    t = re.sub(r"\b(?:%s)\.?\s+\d{1,2}\b" % MONTHS, " ", t)                          # Nov 13
    t = re.sub(r"\b(?:19|20)\d\d\b", " ", t)                                         # years
    return numbers_in(t)


# ---------------------------------------------------------------- checks
def check_prices(data, issue_date, issues_dir, rep):
    close_d = datetime.date.fromisoformat(data["close_date"])
    prev_d = datetime.date.fromisoformat(data["prev_date"])
    if close_d.weekday() != 4:
        rep.warn(f"close_date {close_d} is not a Friday.")
    if not (0 <= (issue_date - close_d).days <= 3):
        rep.error(f"close_date {close_d} is not the Friday before the issue date {issue_date}.")
    if not (5 <= (close_d - prev_d).days <= 9):
        rep.error(f"prev_date {prev_d} is not about one week before close_date {close_d}.")
    sources = data["sources"]
    last = previous_data(issues_dir, issue_date)
    last_close = {}
    if last:
        for g in last.get("groups", []):
            for r in g["rows"]:
                last_close[r["name"]] = r["close"]
        for r in last.get("macro", []):
            last_close[r["name"]] = r["close"]
    table_numbers, table_keys = set(), set()
    rows = [r for g in data["groups"] for r in g["rows"]] + data.get("macro", [])
    for r in rows:
        name = r["name"]
        for f in ("close", "prev"):
            if not isinstance(r.get(f), (int, float)) or r[f] <= 0:
                rep.error(f"{name}: '{f}' must be a positive number.")
                r[f] = r.get(f) if isinstance(r.get(f), (int, float)) and r.get(f) > 0 else 1.0
        r["pct"] = (r["close"] / r["prev"] - 1) * 100
        r["bp"] = round((r["close"] - r["prev"]) * 100)
        keys = r.get("sources") or []
        if not keys:
            rep.error(f"{name}: no source given for the price.")
        for k in keys:
            if k not in sources:
                rep.error(f"{name}: price source '{k}' is not in the source list.")
            table_keys.add(k)
        if keys and keys[0] in sources and not in_list(host_of(sources[keys[0]]["url"]), DATA_DOMAINS):
            rep.strict(f"{name}: primary price source '{keys[0]}' is not an approved data site.")
        chk = r.get("check")
        tol = r.get("tolerance_pct", 0.05)
        if not chk:
            rep.strict(f"{name}: no second source confirms the close.")
        else:
            ck = chk.get("source")
            if ck not in sources:
                rep.error(f"{name}: check source '{ck}' is not in the source list.")
            else:
                table_keys.add(ck)
                if keys and keys[0] in sources and host_of(sources[ck]["url"]) == host_of(sources[keys[0]]["url"]):
                    rep.strict(f"{name}: the second source must be a different site from the first.")
            diff = abs(chk.get("close", 0) / r["close"] - 1) * 100
            if diff > tol:
                rep.error(f"{name}: sources disagree on the close ({r['close']} vs {chk.get('close')}, {diff:.2f}% apart).")
            if "prev" in chk and abs(chk["prev"] / r["prev"] - 1) * 100 > tol:
                rep.error(f"{name}: sources disagree on the previous close ({r['prev']} vs {chk['prev']}).")
        if name in last_close and abs(last_close[name] / r["prev"] - 1) * 100 > tol and not r.get("prev_note"):
            rep.strict(f"{name}: previous close {r['prev']} does not match last issue's close {last_close[name]}. "
                       f"Fix it, or add a 'prev_note' explaining why (split, index change).")
        if abs(r["pct"]) > (40 if r.get("kind") in ("stock", "crypto") else 15):
            rep.warn(f"{name}: weekly move of {fpct(r['pct'])} is unusually large. Double-check both closes.")
        table_numbers |= {round(r["close"], 6), round(r["prev"], 6), round(abs(r["pct"]), 1),
                          float(round(r["close"])), float(abs(r["bp"]))}
        table_numbers |= numbers_in(fnum(r["close"], r.get("decimals", 2)))
    return table_numbers, table_keys


def previous_data(issues_dir, issue_date):
    try:
        listing = json.load(open(os.path.join(issues_dir, "issues.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    older = sorted((i["date"] for i in listing if i["date"] < issue_date.isoformat()), reverse=True)
    for d in older:
        p = os.path.join(issues_dir, d + ".data.json")
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return None


def check_sources(data, issue_date, rep):
    for key, s in data["sources"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", key):
            rep.error(f"Source key '{key}' may only use lowercase letters, digits and hyphens.")
        for f in ("publisher", "title", "url"):
            if not s.get(f):
                rep.error(f"Source '{key}' is missing '{f}'.")
        url = s.get("url", "")
        if not url.startswith("https://"):
            rep.error(f"Source '{key}': the link must start with https://")
        host = host_of(url)
        approved = in_list(host, DATA_DOMAINS + NEWS_DOMAINS) or s.get("wire") in WIRES
        if not approved:
            rep.strict(f"Source '{key}' ({host}) is not an approved outlet. Replace it, or cite the wire story it carries.")
        if s.get("date"):
            d = datetime.date.fromisoformat(s["date"])
            if d > issue_date + datetime.timedelta(days=1):
                rep.error(f"Source '{key}' is dated after the issue.")
            if d < issue_date - datetime.timedelta(days=16) and not s.get("data"):
                rep.warn(f"Source '{key}' is more than two weeks old ({d}).")
        elif not s.get("data"):
            rep.strict(f"Source '{key}' has no publication date.")


def check_text(sections, data, table_numbers, table_keys, rep):
    sources = data["sources"]
    for where, text in walk_text(sections):
        short = re.sub(r"\s+", " ", CITE.sub("", text))[:70]
        keys_here = CITE.findall(text)
        if not keys_here:
            rep.error(f"[{where}] no citation: “{short}…”")
            continue
        for k in keys_here:
            if k not in sources:
                rep.error(f"[{where}] citation [@{k}] is not in the source list.")
        parts = CITE_RUN.split(text)
        tail = re.sub(r"[\s.,;:)”’\"']", "", parts[-1])
        if tail:
            rep.error(f"[{where}] the last sentence has no citation: “…{parts[-1].strip()[-70:]}”")
        for i in range(0, len(parts) - 1, 2):
            span, keys = parts[i], [k for k in CITE.findall(parts[i + 1]) if k in sources]
            pool = set()
            for k in keys:
                for q in sources[k].get("quotes", []) + sources[k].get("derived", []):
                    pool |= numbers_in(q)
                if k in table_keys:
                    pool |= table_numbers
                if sources[k].get("quotes") in (None, []) and not sources[k].get("data"):
                    rep.strict(f"Source '{k}' has no stored quote to check the text against.")
            missing = sorted(n for n in claim_numbers(span) if n not in pool)
            if missing:
                shown = ", ".join(f"{n:g}" for n in missing)
                rep.strict(f"[{where}] {shown} not found in the quotes of {keys}: “{span.strip()[-80:]}”")
    for b in (b for s in sections for b in s["blocks"] if b["type"] == "plain"):
        if CITE.search(b["text"]) or NUM.search(b["text"]):
            rep.error("A 'plain:' line may not contain numbers or citations. Make it a normal paragraph.")


# ---------------------------------------------------------------- rendering
class Cites:
    def __init__(self, sources):
        self.sources, self.order = sources, []

    def number(self, key):
        if key not in self.order:
            self.order.append(key)
        return self.order.index(key) + 1

    def sup(self, keys, dark=False):
        nums = []
        for k in keys:
            if k in self.sources:
                n = self.number(k)
                if n not in nums:
                    nums.append(n)
        style = ' style="color:#E2A82B;"' if dark else ""
        nums.sort()
        groups = []                      # runs of three or more become "4–9"
        for n in nums:
            if groups and n == groups[-1][-1] + 1:
                groups[-1].append(n)
            else:
                groups.append([n])
        labels = []
        for g in groups:
            labels += [(g[0], f"{g[0]}–{g[-1]}")] if len(g) >= 3 else [(n, str(n)) for n in g]
        return "".join(f'<sup><a href="#s{n}"{style}>{t}</a>{"," if i < len(labels) - 1 else ""}</sup>'
                       for i, (n, t) in enumerate(labels))


def inline(text, cites, dark=False):
    out = html.escape(text, quote=False)
    strong = "#EDE9DD" if dark else NAVY
    out = re.sub(r"\*\*(.+?)\*\*", rf'<strong style="color:{strong};">\1</strong>', out)
    out = CITE_RUN.sub(lambda m: cites.sup(CITE.findall(m.group(1)), dark) + (" " if m.group(1).endswith(" ") else ""), out)
    return re.sub(r"\s+(<sup>)", r"\1", out)


def heading(title):
    return (f'<div style="width:44px;height:3px;line-height:3px;font-size:0;background:{GOLD};">&nbsp;</div>'
            f'<div class="h" style="font-size:29px;line-height:36px;color:{NAVY};font-weight:700;padding:14px 0 14px 0;">{html.escape(title)}</div>')


def bar(p, scale):
    w = min(100, round(abs(p) / scale * 100))
    c = UP if p >= 0 else DOWN
    fill = f'<div style="height:10px;width:{w}px;background:{c};font-size:0;line-height:0;%s">&nbsp;</div>'
    neg = fill % "margin-left:auto;" if p < 0 else "&nbsp;"
    pos = fill % "" if p >= 0 else "&nbsp;"
    return ('<table role="presentation" cellpadding="0" cellspacing="0" width="201"><tr>'
            f'<td width="100" align="right" style="font-size:0;line-height:0;">{neg}</td>'
            f'<td width="100" style="font-size:0;line-height:0;border-left:1px solid #8794A8;padding:5px 0;">{pos}</td></tr></table>')


def render_table(data, cites):
    rows_all = [r for g in data["groups"] for r in g["rows"]]
    top = max(abs(r["pct"]) for r in rows_all)
    scale = max(10, 5 * -(-top // 5))
    line = "border-top:1px solid #E3E8EF;"
    out = ['<div id="x-table" style="background:#FFFFFF;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="b" style="font-size:16px;line-height:22px;color:#1B1F27;">']
    for gi, g in enumerate(data["groups"]):
        out.append(f'<tr><td colspan="4" style="padding:{"0" if gi == 0 else "22px"} 0 7px 0;font-size:14px;font-weight:700;color:{NAVY};border-bottom:2px solid {NAVY};">{html.escape(g["name"])}</td></tr>')
        for r in g["rows"]:
            col = UP if r["pct"] >= 0 else DOWN
            out.append(
                f'<tr><td style="padding:9px 0;{line}font-weight:600;">{html.escape(r["name"])}{html.escape(r.get("mark", ""))}</td>'
                f'<td align="right" style="padding:9px 14px 9px 0;{line}color:#4B5563;">{fnum(r["close"], r.get("decimals", 2), r.get("prefix", ""))}</td>'
                f'<td class="bar" width="201" style="padding:0;{line}">{bar(r["pct"], scale)}</td>'
                f'<td align="right" width="66" style="padding:9px 0;{line}font-weight:700;color:{col};">{fpct(r["pct"])}</td></tr>')
    out.append("</table></div>")
    primary, second = [], []
    for r in rows_all:
        primary += [k for k in r.get("sources", []) if k not in primary]
        if r.get("check") and r["check"].get("source") not in second:
            second.append(r["check"]["source"])
    d1 = datetime.date.fromisoformat(data["prev_date"])
    d2 = datetime.date.fromisoformat(data["close_date"])
    note = (f'Closing prices for {d1.day} {d1:%B} and {d2.day} {d2:%B}.{cites.sup(primary)}'
            f' Each weekly change is calculated from those two closes.')
    if second:
        note += f' Closes were checked against a second source.{cites.sup(second)}'
    out.append(f'<div class="b" style="font-size:13px;line-height:20px;color:#4B5563;padding-top:12px;">{note}</div>')
    return "".join(out)


def render_macro(data, cites):
    cells, keys = [], []
    for i, r in enumerate(data.get("macro", [])):
        mode = r.get("mode", "pct")
        if mode == "bp":
            chg = ("up " if r["bp"] >= 0 else "down ") + f'{abs(r["bp"])} basis points'
        else:
            chg = fpct(r["pct"]) + " on the week"
        val = fnum(r["close"], r.get("decimals", 2), r.get("prefix", "")) + r.get("suffix", "")
        keys += [k for k in r.get("sources", []) if k not in keys]
        if r.get("check") and r["check"].get("source") not in keys:
            keys.append(r["check"]["source"])
        cells.append(
            f'<td width="25%" class="stack" valign="top" style="padding:14px 12px 14px {"0" if i == 0 else "14px"};'
            f'{"" if i == 0 else "border-left:1px solid #D4DCE8;"}"><div style="font-size:13px;color:#4B5563;">{html.escape(r.get("label", r["name"]))}</div>'
            f'<div style="font-size:23px;line-height:30px;font-weight:700;color:{NAVY};">{val}</div>'
            f'<div style="font-size:13px;color:#1B1F27;font-weight:600;">{chg}</div></td>')
    if not cells:
        return ""
    return (f'<div id="x-macro" style="margin-top:28px;background:#FFFFFF;border-top:2px solid {NAVY};border-bottom:1px solid #D4DCE8;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="b"><tr>{"".join(cells)}</tr></table></div>'
            f'<div class="b" style="font-size:13px;line-height:20px;color:#4B5563;padding-top:10px;">Friday closes and the change since the Friday before.{cites.sup(keys)}</div>')


def pct_cell(txt, dark):
    neg = txt.strip().startswith(("-", "−"))
    col = ("#FF9C8F" if neg else "#7ED87A") if dark else (DOWN if neg else UP)
    return html.escape(txt.replace("-", "−")), col


def render_blocks(blocks, data, cites, dark=False):
    out = []
    ink = "#DCE4F0" if dark else "#1B1F27"
    rule = "#35527A" if dark else "#D4DCE8"
    for b in blocks:
        t = b["type"]
        if t == "table":
            out.append(render_table(data, cites))
        elif t == "macro":
            out.append(render_macro(data, cites))
        elif t == "plain":
            out.append(f'<div class="b" style="font-size:15px;line-height:22px;color:#4B5563;padding-bottom:20px;">{inline(b["text"], cites)}</div>')
        elif t == "note":
            out.append(f'<div class="b" style="font-size:13px;line-height:20px;color:#4B5563;padding-top:8px;">{inline(b["text"], cites)}</div>')
        elif t == "para":
            size = "15px;line-height:23px" if dark else "17px;line-height:27px"
            out.append(f'<p class="b" style="margin:0 0 16px 0;font-size:{size};color:{ink};">{inline(b["text"], cites, dark)}</p>')
        elif t == "callout":
            out.append(f'<div class="b" style="background:#EEF2F7;border-left:4px solid {GOLD};margin:8px 0 16px 0;padding:18px 22px;font-size:16px;line-height:24px;color:#1B1F27;">{inline(b["text"], cites)}</div>')
        elif t == "bullets":
            rows = "".join(f'<tr><td width="22" valign="top" style="color:{GOLD};font-size:20px;">■</td><td style="padding-bottom:12px;">{inline(i, cites, dark)}</td></tr>' for i in b["items"])
            out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="b" style="font-size:17px;line-height:26px;color:{ink};">{rows}</table>')
        elif t == "rows":
            trs = []
            for r in b["rows"]:
                label, hot = r[0].rstrip("!"), r[0].endswith("!")
                cell = f"padding:10px 0;border-top:1px solid {rule};"
                bg = "background:#FBF6E9;" if hot and not dark else ""
                lab = f'<td width="66" valign="top" style="{cell}font-weight:700;color:{GOLD if dark else NAVY};">{html.escape(label)}</td>'
                if len(r) >= 3:
                    txt, col = pct_cell(r[1], dark)
                    trs.append(f'<tr>{lab}<td valign="top" style="{cell}padding-right:12px;{bg}">{inline(r[2], cites, dark)}</td>'
                               f'<td width="62" valign="top" align="right" style="{cell}font-weight:700;color:{col};">{txt}</td></tr>')
                else:
                    trs.append(f'<tr>{lab}<td valign="top" style="{cell}{bg}">{inline(r[1], cites, dark)}</td></tr>')
            size = "15px;line-height:22px" if dark else "16px;line-height:23px"
            out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="b" style="font-size:{size};color:{ink};border-bottom:1px solid {rule};margin-bottom:16px;">{"".join(trs)}</table>')
        elif t == "spotlight":
            inner = render_blocks(b["blocks"], data, cites, dark=True)
            out.append(f'<div style="background:{NAVY};margin:34px 0 8px 0;padding:28px 28px 12px 28px;" class="b">'
                       f'<div class="h" style="font-size:26px;line-height:32px;color:#EDE9DD;font-weight:700;padding-bottom:12px;">{html.escape(b["title"])}</div>{inner}</div>')
    return "".join(out)


def render(meta, sections, data, cites):
    d = datetime.date.fromisoformat(meta["date"])
    nice = f"{d.day} {d:%B %Y}"
    headline = "<br>".join(html.escape(p.strip()) for p in meta["headline"].split("|"))
    body = []
    for i, s in enumerate(sections):
        body.append(f'<tr><td class="pad" style="padding:{44 if i == 0 else 36}px 40px 8px 40px;">{heading(s["title"])}{render_blocks(s["blocks"], data, cites)}</td></tr>')
    srcs = []
    for n, k in enumerate(cites.order, 1):
        s = data["sources"][k]
        when = ""
        if s.get("date"):
            sd = datetime.date.fromisoformat(s["date"])
            when = f", {sd.day} {sd:%B %Y}"
        via = f' ({html.escape(s["wire"])})' if s.get("wire") and s["wire"] != s["publisher"] else ""
        srcs.append(f'<li id="s{n}">{html.escape(s["publisher"])}{via}, “{html.escape(s["title"])}”{when} – '
                    f'<a href="{html.escape(s["url"], quote=True)}">{html.escape(host_of(s["url"]))}</a></li>')
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alpha Brussels – Weekly Finance Newsletter, {html.escape(meta["week"])}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body{{margin:0;padding:0;background:#E6EDF5;}}
  a{{color:#1F3A5F;}}
  sup{{line-height:0;}}
  sup a{{color:#B8861B;text-decoration:none;font-weight:700;font-size:11px;}}
  .h{{font-family:'Playfair Display',Georgia,'Times New Roman',serif;}}
  .b{{font-family:'Source Sans 3',Helvetica,Arial,sans-serif;}}
  @media (max-width:620px){{
    .wrap{{width:100%!important;}}
    .pad{{padding-left:20px!important;padding-right:20px!important;}}
    .stack{{display:block!important;width:auto!important;border-left:0!important;padding-left:0!important;}}
    .bar{{display:none!important;}}
    .hero{{font-size:38px!important;line-height:42px!important;}}
  }}
</style>
</head>
<body class="b" style="margin:0;padding:0;background:#E6EDF5;">
<div style="display:none;max-height:0;overflow:hidden;color:#E6EDF5;">{html.escape(meta["summary"])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#E6EDF5;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" class="wrap" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:100%;background:#FFFFFF;">
<tr><td class="pad" style="background:{NAVY};padding:30px 40px 46px 40px;border-bottom:6px solid {GOLD};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
    <td valign="middle"><img src="alpha-logo-reversed.png" width="96" alt="Alpha Brussels" style="display:block;border:0;"></td>
    <td valign="middle" align="right" class="b" style="font-size:14px;color:#C9D4E4;line-height:21px;">Weekly finance newsletter<br>Issue {int(meta["issue"])}, {nice}</td>
  </tr></table>
  <div class="b" style="font-size:15px;color:{GOLD};font-weight:700;padding-top:44px;">Week of {html.escape(meta["week"])}</div>
  <div class="h hero" style="font-size:54px;line-height:58px;color:#EDE9DD;font-weight:800;padding-top:8px;letter-spacing:-0.5px;">{headline}</div>
  <div class="b" style="font-size:18px;line-height:28px;color:#C9D4E4;padding-top:18px;max-width:500px;">{html.escape(meta["summary"])}</div>
</td></tr>
{"".join(body)}
<tr><td class="pad" style="padding:20px 40px 40px 40px;">
  <table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="background:#7ED87A;border-radius:6px;"><a class="b" href="#" style="display:block;padding:14px 28px;font-size:15px;letter-spacing:2px;font-weight:700;color:#1B1F27;text-decoration:none;">READ PAST ISSUES</a></td></tr></table>
</td></tr>
<tr><td class="pad" style="background:#F4F2ED;padding:28px 40px;">
  <div class="b" style="font-size:15px;color:{NAVY};font-weight:700;padding-bottom:10px;">Sources</div>
  <ol class="b" style="margin:0;padding-left:20px;font-size:12px;line-height:19px;color:#4B5563;">
    {"".join(srcs)}
  </ol>
</td></tr>
<tr><td class="pad" align="center" style="background:{NAVY};padding:28px 40px;">
  <div class="b" style="font-size:13px;letter-spacing:3px;color:#EDE9DD;font-weight:700;">ALPHA <span style="color:{GOLD};">BRUSSELS</span></div>
  <div class="b" style="font-size:11px;letter-spacing:2px;color:#C9D4E4;padding-top:4px;">FINANCE &amp; ECONOMICS CLUB</div>
  <div class="b" style="font-size:12px;line-height:18px;color:#9FB0C8;padding-top:16px;">For education and information only, not investment advice. Prices are Friday closes; every weekly change is calculated from the two closes shown in the sources.</div>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
'''


# ---------------------------------------------------------------- email (Substack) version
def issue_link(date):
    return f"{SITE_URL}/?issue={date}#newsletter"


def brief_items(brief):
    return [i for b in brief["blocks"] if b["type"] == "bullets" for i in b["items"]] if brief else []


def check_brief(brief, rep):
    if not brief:
        rep.strict("The text has no '## Email brief' section (three to five short bullets for the email).")
        return
    items = brief_items(brief)
    if not 3 <= len(items) <= 5 or any(b["type"] != "bullets" for b in brief["blocks"]):
        rep.error("'## Email brief' must be one list of three to five bullets and nothing else.")
    for i in items:
        plain = CITE.sub("", i).replace("**", "").strip()
        if len(plain) > 230:
            rep.error(f"Email brief bullet is too long ({len(plain)} characters, limit 230): “{plain[:60]}…”")


def render_card(meta, data):
    """A compact picture of every weekly change, sized to stay readable on a phone."""
    groups = [(g["name"], [(r.get("short", r["name"]), fpct(r["pct"]), r["pct"] >= 0) for r in g["rows"]]) for g in data["groups"]]
    macro = []
    for r in data.get("macro", []):
        if r.get("mode") == "bp":
            macro.append((r.get("short", r["name"]), ("+" if r["bp"] >= 0 else "−") + f'{abs(r["bp"])} bp', None))
        else:
            macro.append((r.get("short", r["name"]), fpct(r["pct"]), None))
    if macro:
        groups.append(("Oil, gold, rates", macro))
    cols, sizes = [[], []], [0, 0]
    for g in groups:
        i = 0 if sizes[0] <= sizes[1] else 1
        cols[i].append(g)
        sizes[i] += len(g[1]) + 1.4

    def col(gs):
        out = []
        for name, rows in gs:
            out.append(f'<div class="g">{html.escape(name)}</div>')
            for label, chg, up in rows:
                colr = "#1B1F27" if up is None else (UP if up else DOWN)
                out.append(f'<div class="r"><span>{html.escape(label)}</span><b style="color:{colr}">{chg}</b></div>')
        return "".join(out)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#fff}}
#card{{width:440px;background:#fff;font-family:'Source Sans 3',Helvetica,Arial,sans-serif;color:#1B1F27}}
.top{{background:{NAVY};border-bottom:4px solid {GOLD};padding:14px 18px 12px}}
.top h1{{margin:0;font:700 21px/1.2 'Playfair Display',Georgia,serif;color:#EDE9DD}}
.top p{{margin:3px 0 0;font-size:13px;color:#C9D4E4}}
.cols{{display:flex;gap:22px;padding:4px 18px 16px}}
.cols>div{{flex:1;min-width:0}}
.g{{font-size:12.5px;font-weight:700;color:{NAVY};border-bottom:2px solid {NAVY};padding:12px 0 4px}}
.r{{display:flex;justify-content:space-between;gap:8px;font-size:14.5px;line-height:1.2;padding:6px 0;border-bottom:1px solid #E3E8EF}}
.r span{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.r b{{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}}
</style></head><body><div id="card">
<div class="top"><h1>The week’s moves</h1><p>{html.escape(meta["week"])}. Change since the Friday before.</p></div>
<div class="cols"><div>{col(cols[0])}</div><div>{col(cols[1])}</div></div>
</div></body></html>
"""


def render_substack(meta, brief, data):
    date = meta["date"]
    link = issue_link(date)
    rows = {r["name"]: r for g in data["groups"] for r in g["rows"]}
    alt = "This week’s moves: " + ", ".join(f'{rows[n].get("short", n)} {fpct(rows[n]["pct"])}' for n in data.get("board", []) if n in rows) + ". Full table in the issue on the website."

    def clean(t):
        t = html.escape(CITE.sub("", t), quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s{2,}", " ", t)).strip()
    bullets = "".join(f"<li>{clean(i)}</li>" for i in brief_items(brief))
    attrs = json.dumps({"url": link, "text": "Read the full issue", "action": None, "class": None}).replace("'", "&#39;")
    button = (f'<p class="button-wrapper" data-attrs=\'{attrs}\' data-component-name="ButtonCreateButton">'
              f'<a class="button primary" href="{link}"><span>Read the full issue</span></a></p>')
    # The button comes first so readers can click through straight away, and again after the picture.
    body = (button
            + f'<ul>{bullets}</ul>'
            + f'<p><img src="{SITE_URL}/issues/{date}-card.png" width="440" alt="{html.escape(alt, quote=True)}"></p>'
            + button
            + f'<p><em>The full issue explains why prices moved, the other news that mattered and what to expect next week, '
              f'with every source listed. For education and information only, not investment advice.</em></p>')
    nodes = "button,bulletList,captionedImage,button,paragraph"
    title = html.escape(meta["headline"].replace(" | ", " ").replace("|", " "))
    summary = html.escape(meta["summary"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email version, issue {int(meta["issue"])}</title>
<style>
body{{margin:0;background:#E6EDF5;color:#1B1F27;font:17px/1.6 Georgia,serif}}
.page{{max-width:640px;margin:0 auto;padding:24px 16px 60px}}
.how{{background:#1F3A5F;color:#EDE9DD;padding:20px 22px;font:15px/1.5 Helvetica,Arial,sans-serif}}
.how ol{{margin:8px 0 0;padding-left:20px}}
.field{{background:#fff;border:1px solid #C2CEDF;padding:14px 16px;margin-top:14px}}
.field small{{display:block;font:700 12px/1.4 Helvetica,Arial,sans-serif;color:#55627D;margin-bottom:4px}}
button{{font:700 14px/1 Helvetica,Arial,sans-serif;background:#E2A82B;color:#1B1F27;border:0;border-radius:4px;padding:10px 16px;cursor:pointer;margin-top:10px}}
#body{{background:#fff;border:1px solid #C2CEDF;padding:8px 24px 24px;margin-top:14px}}
#body img{{max-width:100%;height:auto}}
#body .button{{display:inline-block;background:#1F3A5F;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;font:700 15px/1 Helvetica,Arial,sans-serif}}
</style></head><body><div class="page">
<div class="how"><strong>Email version of issue {int(meta["issue"])}.</strong> This page is a helper and is not sent to anyone.
<ol><li>In Substack, start a new post.</li><li>Copy the title and subtitle into their boxes.</li>
<li>Press “Copy the post” and paste into the body of the Substack post.</li><li>Check the button is at the top and the picture appears, then send.</li></ol></div>
<div class="field"><small>Title</small><div id="title">{title}</div><button data-copy="title">Copy the title</button></div>
<div class="field"><small>Subtitle</small><div id="subtitle">{summary}</div><button data-copy="subtitle">Copy the subtitle</button></div>
<button data-copy="body">Copy the post</button>
<div id="body" data-nodes="{nodes}">{body}</div>
</div>
<script>
document.addEventListener('click', function (e) {{
  var b = e.target.closest('button[data-copy]'); if (!b) return;
  var el = document.getElementById(b.getAttribute('data-copy'));
  var done = function () {{ var t = b.textContent; b.textContent = 'Copied'; setTimeout(function () {{ b.textContent = t; }}, 1500); }};
  var fallback = function () {{ var r = document.createRange(); r.selectNodeContents(el); var s = getSelection(); s.removeAllRanges(); s.addRange(r); try {{ document.execCommand('copy'); done(); }} catch (err) {{}} }};
  try {{
    navigator.clipboard.write([new ClipboardItem({{
      'text/html': new Blob([el.innerHTML], {{type: 'text/html'}}),
      'text/plain': new Blob([el.innerText], {{type: 'text/plain'}})
    }})]).then(done, fallback);
  }} catch (err) {{ fallback(); }}
}});
</script></body></html>
"""


# ---------------------------------------------------------------- main
def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    issues_dir, date = argv[1], argv[2]
    check_only = "--check" in argv
    draft = "--draft" in argv
    issue_date = datetime.date.fromisoformat(date)
    base = os.path.join(issues_dir, date)
    meta, sections = parse_md(open(base + ".md", encoding="utf-8").read())
    data = json.load(open(base + ".data.json", encoding="utf-8"))
    rep = Report(bool(data.get("legacy")))

    for f in ("issue", "date", "week", "headline", "summary"):
        if not meta.get(f):
            rep.error(f"The header of the .md file is missing '{f}'.")
    if meta.get("date") != date:
        rep.error(f"The date in the .md header ({meta.get('date')}) does not match the file name ({date}).")
    if rep.errors:
        return finish(rep, None)

    table_numbers, table_keys = check_prices(data, issue_date, issues_dir, rep)
    check_sources(data, issue_date, rep)
    check_text(sections, data, table_numbers, table_keys, rep)
    brief = next((s for s in sections if s["title"].strip().lower() == "email brief"), None)
    check_brief(brief, rep)
    sections = [s for s in sections if s is not brief]      # the brief is for the email only
    kinds = [b["type"] for s in sections for b in s["blocks"]]
    if "table" not in kinds:
        rep.error("The text never places the price table. Add a line with [[table]].")

    cites = Cites(data["sources"])
    page = render(meta, sections, data, cites)
    unused = [k for k in data["sources"] if k not in cites.order]
    if unused:
        rep.warn("Sources no longer cited, left out of the list: " + ", ".join(unused))

    rows = {r["name"]: r for g in data["groups"] for r in g["rows"]}
    board = []
    for name in data.get("board", []):
        if name not in rows:
            rep.error(f"Board entry '{name}' is not a row in the price table.")
            continue
        r = rows[name]
        board.append([r.get("short", name), fnum(r["close"], r.get("decimals", 2), r.get("prefix", "")), fpct(r["pct"])])
    entry = {"file": date + ".html", "issue": int(meta["issue"]), "date": date, "week": meta["week"],
             "title": meta["headline"].replace(" | ", " ").replace("|", " "), "summary": meta["summary"], "board": board}

    listing_path = os.path.join(issues_dir, "issues.json")
    try:
        listing = json.load(open(listing_path, encoding="utf-8"))
    except (OSError, ValueError):
        listing = []
    others = [i for i in listing if i["file"] != entry["file"]]
    if any(i["issue"] == entry["issue"] for i in others):
        rep.error(f"Issue number {entry['issue']} is already used by another issue.")
    older = [i["issue"] for i in others if i["date"] < date]
    if older and entry["issue"] != max(older) + 1:
        rep.warn(f"Issue number {entry['issue']} does not follow the previous issue ({max(older)}).")
    listing = sorted(others + [entry], key=lambda i: i["date"], reverse=True)

    if rep.errors or check_only:
        return finish(rep, None)
    if draft:
        ddir = os.path.join(os.path.dirname(os.path.abspath(issues_dir)), "drafts")
        os.makedirs(ddir, exist_ok=True)
        logo = os.path.join(issues_dir, "alpha-logo-reversed.png")
        if os.path.exists(logo):
            b64 = base64.b64encode(open(logo, "rb").read()).decode()
            page = page.replace('src="alpha-logo-reversed.png"', f'src="data:image/png;base64,{b64}"')
        banner = (f'<tr><td class="b" align="center" style="background:{GOLD};color:#1B1F27;font-size:14px;font-weight:700;'
                  f'padding:10px 16px;">Draft for approval. Not on the website yet.</td></tr>\n<tr><td class="pad" style="background:{NAVY};padding:30px')
        page = page.replace(f'<tr><td class="pad" style="background:{NAVY};padding:30px', banner, 1)
        open(os.path.join(ddir, date + ".html"), "w", encoding="utf-8").write(page)
        for ext in (".md", ".data.json"):
            open(os.path.join(ddir, date + ext), "w", encoding="utf-8").write(open(base + ext, encoding="utf-8").read())
        return finish(rep, f"Draft preview written to {os.path.join(ddir, date + '.html')} with {len(cites.order)} numbered sources. "
                           f"The website files were not touched.")
    open(base + ".html", "w", encoding="utf-8").write(page)
    open(base + ".substack.html", "w", encoding="utf-8").write(render_substack(meta, brief, data))
    open(base + ".card.html", "w", encoding="utf-8").write(render_card(meta, data))
    json.dump(listing, open(listing_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return finish(rep, f"Built {base}.html with {len(cites.order)} numbered sources. issues.json now lists {len(listing)} issue(s); "
                       f"the newest is issue {listing[0]['issue']}.")


def finish(rep, done):
    for w in rep.warnings:
        print("WARNING  " + w)
    if rep.skipped:
        if "--verbose" in sys.argv:
            for w in rep.skipped:
                print("LEGACY   " + w)
        print(f"LEGACY   {len(rep.skipped)} second-source, quote and outlet checks were not enforced for this "
              f"legacy issue (add --verbose to list them).")
    for e in rep.errors:
        print("ERROR    " + e)
    print(f"\n{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)" + (" [legacy issue]" if rep.legacy else ""))
    if rep.errors:
        print("NOT BUILT. Fix the errors above and run again.")
        return 1
    print(done or "Checks passed. Nothing written (--check).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
