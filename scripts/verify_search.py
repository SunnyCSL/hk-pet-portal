#!/usr/bin/env python3
"""Verify the hk-pet-portal restaurant search/browse behaviour.

Usage (REQUIRED python interpreter — has playwright + chromium):
    ~/.hermes-venv/bin/python3 scripts/verify_search.py [BASE_URL]

Default BASE_URL is http://localhost:4321 (astro preview served from dist/).

What it checks (zh + en):
  - Initial browse-all: result-count == 906, pager shows 1/19, next not disabled
  - Per-query match counts (casesensitive: lowercase only)
  - Multi-token AND search ("奧運 Outback" should yield 0 = same as single)
  - District pill filter (旺角區)
"""

import re
import sys
import json
import time
from urllib.parse import urlencode, quote
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4321"

# (query, expected_count) pairs from the main-brain spec.
ZH_QUERIES = [
    ("",                  906),   # browse all
    ("奧運",               16),
    ("奧海城",             4),
    ("海泓道",             2),
    ("嘉善街",             2),
    ("大角咀",             12),
    ("尖沙咀",             62),
    ("oliver",             8),
    ("yaki ana",           1),
    ("麥當勞",             2),
    ("outback",            0),    # data itself has no "outback" anywhere
    ("奧運 Outback",       0),    # AND must NOT throw / must equal single 0
]

# Same probes for the EN mirror — counts must mirror the underlying dataset
# (search key is shared so the only thing the EN page can differ on is which
# name is shown, not which rows match).
EN_QUERIES = list(ZH_QUERIES)


def run_queries(page, base_path, queries, total_label, count_pat, sample_n=0):
    """Run a list of (query, expected) pairs against `base_path`.

    Returns a dict mapping 'query' → actual_count (or 'ERR' string).
    """
    results = {}
    for q, _expected in queries:
        url = base_path
        if q:
            url += ("?q=" + quote(q)) if not url.endswith("?") else ("q=" + quote(q))
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        # wait for the first rebuildPage() to have run (count filled by JS)
        page.wait_for_function(
            "() => document.getElementById('result-count') !== null",
            timeout=5000,
        )
        # small grace period for client JS to settle
        page.wait_for_timeout(150)
        text = page.locator("#result-count").first.text_content() or ""
        m = count_pat.search(text)
        if not m:
            results[q] = ("ERR", text)
        else:
            results[q] = int(m.group(1))
    return results


def get_pager_state(page):
    cur = page.locator("#pg-current").first.text_content() or ""
    tot = page.locator("#pg-total").first.text_content() or ""
    try:
        nxt = page.evaluate("() => document.getElementById('pg-next').disabled")
    except Exception:
        nxt = None
    try:
        prv = page.evaluate("() => document.getElementById('pg-prev').disabled")
    except Exception:
        prv = None
    return {"cur": cur.strip(), "tot": tot.strip(), "next_disabled": nxt, "prev_disabled": prv}


def main():
    report_lines = []
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # ---- ZH ----
        report_lines.append("=" * 72)
        report_lines.append("ZH — http://localhost:4321/restaurants")
        report_lines.append("=" * 72)
        page.goto(BASE_URL + "/restaurants", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(400)
        pager0 = get_pager_state(page)
        count0 = page.locator("#result-count").first.text_content() or ""
        report_lines.append(f"  initial: count='{count0.strip()}' pager={pager0}")
        if count0.strip() != "906 間":
            failures += 1
            report_lines.append("  FAIL: result-count != '906 間' on initial load")
        if pager0["cur"] != "1" or pager0["tot"] != "19":
            failures += 1
            report_lines.append(f"  FAIL: pager expected 1/19, got {pager0['cur']}/{pager0['tot']}")
        if pager0["next_disabled"]:
            failures += 1
            report_lines.append("  FAIL: next button should be enabled on initial load")

        # Run all queries via URL
        results = {}
        for q, _exp in ZH_QUERIES:
            url = BASE_URL + "/restaurants"
            if q:
                url += "?q=" + quote(q)
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(250)
            t = page.locator("#result-count").first.text_content() or ""
            m = re.search(r"(\d+)\s*間", t)
            results[q] = int(m.group(1)) if m else -1

        report_lines.append("")
        report_lines.append("  ZH query | expected | actual")
        for q, expected in ZH_QUERIES:
            actual = results[q]
            ok = "OK " if actual == expected else "FAIL"
            report_lines.append(f"    {ok}  q='{q}' | exp={expected:>4} | got={actual:>4}")
            if actual != expected:
                failures += 1

        # District pill (旺角區)
        page.goto(BASE_URL + "/restaurants?district=" + quote("旺角區"), wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(300)
        t = page.locator("#result-count").first.text_content() or ""
        m = re.search(r"(\d+)\s*間", t)
        n = int(m.group(1)) if m else -1
        ok_n = (n == 70)  # 旺角 in name/addr+key alias expansion → 70; district '旺角區' has 67 + extras 3? But district==旺角區 exactly is 67 records
        # NOTE: requirement says district filtering should be working — not a hard count target.
        # We assert it returns > 0 and reasonable.
        report_lines.append("")
        report_lines.append(f"  district 旺角區 | actual={n} (district cols contain 67 entries with 旺角區 + alias '太子' expansion)")
        if n <= 0:
            failures += 1
            report_lines.append("    FAIL: district filter returned 0")

        # Clear-filter link should be visible (we have ?district)
        clear_vis = page.locator("#clear-filter").is_visible()
        report_lines.append(f"  clear-filter visible after district filter: {clear_vis}")

        # ---- EN ----
        report_lines.append("")
        report_lines.append("=" * 72)
        report_lines.append("EN — http://localhost:4321/en/restaurants")
        report_lines.append("=" * 72)
        page.goto(BASE_URL + "/en/restaurants", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(400)
        pager0 = get_pager_state(page)
        count0 = page.locator("#result-count").first.text_content() or ""
        report_lines.append(f"  initial: count='{count0.strip()}' pager={pager0}")
        if count0.strip() != "906 venues":
            failures += 1
            report_lines.append("  FAIL: result-count != '906 venues' on initial EN load")
        if pager0["cur"] != "1" or pager0["tot"] != "19":
            failures += 1
            report_lines.append(f"  FAIL: pager expected 1/19, got {pager0['cur']}/{pager0['tot']}")
        if pager0["next_disabled"]:
            failures += 1
            report_lines.append("  FAIL: next button should be enabled on initial EN load")

        en_results = {}
        for q, _exp in EN_QUERIES:
            url = BASE_URL + "/en/restaurants"
            if q:
                url += "?q=" + quote(q)
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(250)
            t = page.locator("#result-count").first.text_content() or ""
            m = re.search(r"(\d+)\s*venues", t)
            en_results[q] = int(m.group(1)) if m else -1

        report_lines.append("")
        report_lines.append("  EN query | expected | actual")
        for q, expected in EN_QUERIES:
            actual = en_results[q]
            ok = "OK " if actual == expected else "FAIL"
            report_lines.append(f"    {ok}  q='{q}' | exp={expected:>4} | got={actual:>4}")
            if actual != expected:
                failures += 1

        # Cross-page consistency: ZH counts and EN counts should match exactly
        report_lines.append("")
        report_lines.append("  ZH vs EN count consistency:")
        any_mismatch = False
        for q, _exp in ZH_QUERIES:
            z = results[q]
            e = en_results[q]
            ok = "OK " if z == e else "DIFF"
            if z != e:
                any_mismatch = True
                failures += 1
            report_lines.append(f"    {ok}  q='{q}'  zh={z}  en={e}")

        # Visibility sanity for the EN district pill filter
        page.goto(BASE_URL + "/en/restaurants?district=" + quote("旺角區"), wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(300)
        t = page.locator("#result-count").first.text_content() or ""
        m = re.search(r"(\d+)\s*venues", t)
        en_district_n = int(m.group(1)) if m else -1
        report_lines.append(f"\n  EN district 旺角區 filter → {en_district_n}")
        if en_district_n <= 0:
            failures += 1
            report_lines.append("    FAIL: EN district filter returned 0")

        browser.close()

    report_lines.append("")
    report_lines.append("=" * 72)
    report_lines.append(f"FAILURES: {failures}")
    report_lines.append("=" * 72)

    print("\n".join(report_lines))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
