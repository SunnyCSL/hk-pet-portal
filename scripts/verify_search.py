"""verify_search.py — Playwright + terminal-based smoke for hk-pet-portal
area-nearby-search implementation. Validates A–F groups from the brief.

Prereqs: `~/.hermes-venv/bin/python3` with playwright + chromium (headless).
Usage:  start preview server first, then run this script.

    cd /Users/nexi/Projects/hk-pet-portal
    npx astro preview --port 4321   # background
    ~/.hermes-venv/bin/python3 scripts/verify_search.py
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
ZH_URL = "http://127.0.0.1:4321/restaurants"
EN_URL = "http://127.0.0.1:4321/en/restaurants"


def _print(section: str, msg: str) -> None:
    print(f"[{section}] {msg}", flush=True)


def _close(group: str, expected: Any, actual: Any) -> bool:
    return expected == actual


async def _new_page(browser):
    context = await browser.new_context(viewport={"width": 420, "height": 900})
    page = await context.new_page()
    console_errors: list[str] = []
    page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
    page.on(
        "console",
        lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}")
        if msg.type == "error"
        and "/_vercel/" not in (msg.text or "")
        and "/_vercel/" not in ((msg.location or {}).get("url", "") if isinstance(msg.location, dict) else (getattr(msg.location, "url", "") or ""))
        else None,
    )
    return page, console_errors


async def _set_query(page, q: str) -> None:
    await page.fill("#search-input", "")
    if q:
        await page.fill("#search-input", q)
    # Trigger native input event so the listener fires
    await page.evaluate(
        "(q) => { const i = document.getElementById('search-input'); i.value = q; i.dispatchEvent(new Event('input', {bubbles:true})); }",
        q,
    )
    # Give the JS rebuildPage a tick
    await page.wait_for_timeout(350)


async def _click_chip(page, radius: int) -> None:
    await page.evaluate(
        "(r) => { const c = document.querySelector('.radius-chip[data-radius=\"' + r + '\"]'); if (c) { setRadius(r); } }",
        radius,
    )
    await page.wait_for_timeout(350)


async def _read_results(page) -> dict:
    """Read the live state of the search page after a query. Counts every
    restaurant-item id present in #restaurant-list, regardless of pagination /
    display state, so it matches the full total."""
    href_re = r"/restaurants/(\d+)"
    return await page.evaluate(
        """(hrefRe) => {
            const hrefRe2 = new RegExp(hrefRe);
            const countEl = document.getElementById('result-count');
            const cur = document.getElementById('pg-current');
            const tot = document.getElementById('pg-total');
            const header = document.getElementById('area-header');
            const labelEl = document.getElementById('area-header-label');
            const metaEl = document.getElementById('area-header-meta');
            const chipsEl = document.getElementById('area-radius-chips');
            const chipsVisible = chipsEl ? (chipsEl.offsetParent !== null && chipsEl.style.display !== 'none') : false;
            const headerVisible = header ? !header.classList.contains('hidden') : false;
            // Dedupe by id across SSR + island cards.
            const ids = new Set();
            document.querySelectorAll('#restaurant-list .restaurant-item').forEach(el => {
              const m = (el.getAttribute('href') || '').match(hrefRe2);
              if (m) ids.add(Number(m[1]));
            });
            const visibleIds = Array.from(ids);
            // First 5 ids in the rendered DOM order (i.e. what the user sees on
            // page 1). In area-mode SSR cards are hidden and island cards are
            // appended in runFilter order, so iterating children captures the
            // actual displayed order.
            const first5 = [];
            document.querySelectorAll('#restaurant-list .restaurant-item').forEach(el => {
              if (first5.length >= 5) return;
              if (el.offsetParent === null) return;  // hidden card
              const m = (el.getAttribute('href') || '').match(hrefRe2);
              if (m) first5.push(Number(m[1]));
            });
            const badges = Array.from(document.querySelectorAll('#restaurant-list .dist-badge'))
              .filter(el => el.offsetParent !== null)
              .map(el => el.textContent.trim());
            return {
              countText: countEl ? countEl.textContent.trim() : null,
              pgCurrent: cur ? cur.textContent.trim() : null,
              pgTotal: tot ? tot.textContent.trim() : null,
              headerVisible,
              headerLabel: labelEl ? labelEl.textContent.trim() : null,
              headerMeta: metaEl ? metaEl.textContent.trim() : null,
              chipsVisible,
              visibleIds,
              first5,
              distBadges: badges,
            };
        }""",
        href_re,
    )


def _parse_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else None


def _count_from_text(s: str | None) -> int | None:
    """Extract the leading integer from a label like '32 間' / '32 venues'."""
    if not s:
        return None
    m = re.match(r"\s*(\d+)", s)
    return int(m.group(1)) if m else None


async def _expect_count(page, section: str, q: str, expected: int) -> tuple[int, str | None]:
    await _set_query(page, q)
    res = await _read_results(page)
    # Prefer the countText (e.g. '32 間' / '32 venues') — that's the source of
    # truth for total results, independent of pagination.
    text_count = _count_from_text(res["countText"])
    actual = text_count if text_count is not None else len(res["visibleIds"])
    ok = "✓" if actual == expected else "✗"
    _print(
        section,
        f"{ok} q={q!r} expected={expected} actual={actual} (text={res['countText']!r}) pg={res['pgCurrent']}/{res['pgTotal']}",
    )
    return actual, res["countText"]


async def _expect_first_ids(page, section: str, q: str, expected_first5: list[int]) -> list[int]:
    await _set_query(page, q)
    res = await _read_results(page)
    first5 = res["first5"]
    ok = "✓" if first5 == expected_first5 else "✗"
    _print(
        section,
        f"{ok} q={q!r} expected first5={expected_first5} actual first5={first5}",
    )
    return first5


async def _check_zh(browser) -> dict:
    page, console_errors = await _new_page(browser)
    await page.goto(ZH_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(300)
    out: dict[str, Any] = {"console_errors": list(console_errors)}

    # === A. non-area mode (must not change) ===
    _print("A", "Non-area mode counts (must equal prior baseline)")
    expected_a = {
        "": 906,
        "oliver": 8,
        "yaki ana": 1,
        "麥當勞": 2,
        "海泓道": 2,
        "奧海城": 4,
        "outback": 0,
    }
    out["A"] = {}
    for q, exp in expected_a.items():
        actual, txt = await _expect_count(page, "A", q, exp)
        out["A"][q] = {"expected": exp, "actual": actual, "countText": txt}

    # pager total when q=""
    await _set_query(page, "")
    res0 = await _read_results(page)
    pager_ok = res0["pgTotal"] == "19"
    _print("A", f"{'✓' if pager_ok else '✗'} q='' pager total expected=19 actual={res0['pgTotal']}")
    out["A"]["pager_total"] = res0["pgTotal"]

    # 旺角 district pill = 67
    await _set_query(page, "")
    await page.evaluate("() => setDistrict('旺角區')")
    await page.wait_for_timeout(400)
    res_mk = await _read_results(page)
    text_count = _count_from_text(res_mk["countText"])
    actual_mk = text_count if text_count is not None else len(res_mk["visibleIds"])
    _print("A", f"{'✓' if actual_mk==67 else '✗'} 旺角區 district expected=67 actual={actual_mk} (text={res_mk['countText']!r})")
    out["A"]["mongkok"] = actual_mk
    await page.evaluate("() => setDistrict('')")
    await page.wait_for_timeout(400)

    # === B. area-mode default 1km ===
    _print("B", "Area-mode (default 1km)")
    area_cases = {
        "奧運": {"1km": 32, "500m": 19, "2km": 123, "all": 906,
                 "first5": [384, 599, 97, 695, 878]},
        "大角咀": {"1km": 71, "500m": 16, "all": 906,
                   "first5": [226, 407, 870, 97, 695]},
        "尖沙咀": {"1km": 82, "500m": 66, "all": 906,
                   "first5": [337, 489, 793, 829, 468]},
        "太古":   {"1km": 11, "500m": 9,
                   "first5": [146, 857, 177, 342, 333]},
        "將軍澳": {"1km": 26,
                   "first5": [188, 548, 123, 598, 854]},
        # NOTE on 將軍澳 first5: the 4 area-prec cards in the result are now
        # physically pushed to the end of the list (bucket 4 "位置約略"), so
        # the first 5 ids are all building-prec records ~920–954 m from the
        # centre. The last 4 ids (sorted same direction) are area-prec with
        # "位置約略" badge instead of "約 N 米".
    }
    out["B"] = {}
    for area, exp in area_cases.items():
        out["B"][area] = {}
        # 1km default
        actual_1km, _ = await _expect_count(page, "B", area, exp["1km"])
        out["B"][area]["1km"] = actual_1km
        first5 = await _expect_first_ids(page, "B", area, exp["first5"])
        out["B"][area]["first5"] = first5
        # chips visible for pure area query
        res = await _read_results(page)
        chips_ok = res["chipsVisible"]
        _print("B", f"{'✓' if chips_ok else '✗'} {area} chipsVisible expected=True actual={chips_ok}")
        out["B"][area]["chips"] = chips_ok
        # 500m
        if "500m" in exp:
            await _click_chip(page, 500)
            res500 = await _read_results(page)
            text_count = _count_from_text(res500["countText"])
            actual500 = text_count if text_count is not None else len(res500["visibleIds"])
            ok500 = "✓" if actual500 == exp["500m"] else "✗"
            _print("B", f"{ok500} {area} 500m expected={exp['500m']} actual={actual500} (text={res500['countText']!r})")
            out["B"][area]["500m"] = actual500
            # reset
            await _click_chip(page, 1000)
            await page.wait_for_timeout(120)
        # 2km
        if "2km" in exp:
            await _click_chip(page, 2000)
            res2k = await _read_results(page)
            text_count = _count_from_text(res2k["countText"])
            actual2k = text_count if text_count is not None else len(res2k["visibleIds"])
            ok2k = "✓" if actual2k == exp["2km"] else "✗"
            _print("B", f"{ok2k} {area} 2km expected={exp['2km']} actual={actual2k} (text={res2k['countText']!r})")
            out["B"][area]["2km"] = actual2k
            # all
            if "all" in exp:
                await _click_chip(page, 0)
                resA = await _read_results(page)
                text_count = _count_from_text(resA["countText"])
                actualA = text_count if text_count is not None else len(resA["visibleIds"])
                okA = "✓" if actualA == exp["all"] else "✗"
                _print("B", f"{okA} {area} all expected={exp['all']} actual={actualA} (text={resA['countText']!r})")
                out["B"][area]["all"] = actualA
            # back to 1km default
            await _click_chip(page, 1000)
            await page.wait_for_timeout(120)

    # === C. FilterTokens non-empty branch (chip hidden) ===
    _print("C", "filterTokens non-empty (chip hidden, no radius union)")
    for q, exp_n in [("奧運 Outback", 0), ("大角咀 咖啡", 16)]:
        actual, _ = await _expect_count(page, "C", q, exp_n)
        res = await _read_results(page)
        chips_ok = res["chipsVisible"] is False
        _print("C", f"{'✓' if chips_ok else '✗'} {q!r} chipsVisible expected=False actual={res['chipsVisible']}")
        out["C"] = out.get("C", {})
        out["C"][q] = {"count": actual, "chipsHidden": chips_ok}

    # === D. dist badges + bucket header + non-decreasing distances ===
    # D-rules after the area-nearby-search v2 fix:
    #   D1. 奧運 1km cards — first 30 cards' numeric distances are non-decreasing.
    #   D2. 奧運 1km has no "約" prefix anywhere (all 奧運 cards are precise).
    #   D3. 將軍澳 1km cards in the last "位置約略" bucket ALL show
    #       "位置約略" badge (no fake "約 N 米").
    #   D4. The "位置約略" group header is visible in 將軍澳 mode.
    _print("D", "badge format / monotonic / area-only fix")

    # --- D1 + D2: 奧運 ---
    await _set_query(page, "奧運")
    await page.wait_for_timeout(120)
    oly = await _read_results(page)
    oly_badges = oly["distBadges"][:30]
    oly_with_num = []
    for b in oly_badges:
        m = re.match(r"(\d+)\s*米", b) or re.match(r"([\d.]+)\s*公里", b)
        if m:
            val = float(m.group(1))
            oly_with_num.append(val * 1000 if "公里" in b else val)
    monotonic = all(oly_with_num[i] <= oly_with_num[i+1] for i in range(len(oly_with_num)-1))
    oly_no_approx = not any(b.startswith("約 ") for b in oly_badges)
    _print("D", f"奧運 badges[:5]={oly_badges[:5]} oly_no_approx={oly_no_approx} monotonic={monotonic} (n={len(oly_with_num)})")
    _print("D", f"{'✓' if oly_no_approx else '✗'} 奧運 no '約' prefix anywhere (got {oly_no_approx})")
    _print("D", f"{'✓' if monotonic   else '✗'} 奧運 first30 distances non-decreasing")

    # --- D3 + D4: 將軍澳 ---
    await _set_query(page, "將軍澳")
    await page.wait_for_timeout(120)
    tko = await _read_results(page)
    tko_badges = tko["distBadges"]
    tko_count = len(tko["visibleIds"])
    # Identify area-prec cards: their badges should be exactly "位置約略".
    # For 將軍澳 1km results there are 4 area-prec records; they appear
    # physically last.
    area_badge_exact = "位置約略"
    # Find where bucket-4 header appears in DOM and slice from there.
    # headers are #area-group-* divs with text label. read via JS.
    tko_groups = await page.evaluate(
        """() => {
            const groups = document.querySelectorAll('.area-group-header');
            return Array.from(groups).map(g => ({
              label: (g.textContent || '').trim(),
              visible: g.offsetParent !== null,
            }));
        }"""
    )
    area_group_present = any(g["visible"] and g["label"] == "位置約略" for g in tko_groups)
    _print("D", f"將軍澳 group headers={tko_groups}  area_group_present={area_group_present}")

    # Find the index of the "位置約略" group header in the rendered card stream
    # by re-reading list, and the badges that come AFTER it.
    cards_after = await page.evaluate(
        """() => {
            const list = document.getElementById('restaurant-list');
            if (!list) return [];
            const out = [];
            for (const child of list.children) {
              if (child.classList.contains('area-group-header')) {
                out.push({ kind: 'group', label: (child.textContent || '').trim() });
              } else if (child.classList.contains('restaurant-item')) {
                const m = (child.getAttribute('href') || '').match(/\\/restaurants\\/(\\d+)/);
                if (m) out.push({ kind: 'card', id: Number(m[1]) });
              }
            }
            return out;
        }"""
    )
    # Find every card-id that comes after the first "位置約略" group header.
    cards_in_bucket4 = []
    seen_header = False
    for n in cards_after:
        if n["kind"] == "group":
            if n["label"] == "位置約略":
                seen_header = True
            else:
                # next group means we left bucket 4
                if seen_header:
                    break
            continue
        if seen_header:
            cards_in_bucket4.append(n["id"])
    _print("D", f"將軍澳 cards in bucket '位置約略' (ids) = {cards_in_bucket4}")

    # For each bucket-4 card, its visible badge must be exactly "位置約略"
    # (not "約 N 米" / "米 · 步行 ...").
    tko_res = await _read_results(page)
    tko_badge_by_id = {}
    tko_dom = await page.evaluate(
        """() => {
            const list = document.getElementById('restaurant-list');
            if (!list) return [];
            const out = [];
            for (const child of list.children) {
              if (!child.classList.contains('restaurant-item')) continue;
              const m = (child.getAttribute('href') || '').match(/\\/restaurants\\/(\\d+)/);
              if (!m) continue;
              const badge = child.querySelector('.dist-badge');
              out.push({
                id: Number(m[1]),
                badge: badge ? (badge.textContent || '').trim() : null,
              });
            }
            return out;
        }"""
    )
    tko_badge_by_id = {row["id"]: row["badge"] for row in tko_dom}
    bucket4_badges = [tko_badge_by_id.get(cid) for cid in cards_in_bucket4]
    all_bucket4_area = all(b == area_badge_exact for b in bucket4_badges if b)
    _print("D", f"bucket4 badges={bucket4_badges} all ='{area_badge_exact}'? {all_bucket4_area}")
    _print("D", f"{'✓' if area_group_present else '✗'} 將軍澳 '位置約略' group header present")
    _print("D", f"{'✓' if all_bucket4_area else '✗'} 將軍澳 bucket4 cards all show '{area_badge_exact}' (got {len([b for b in bucket4_badges if b == area_badge_exact])}/{len(bucket4_badges)})")

    out["D"] = {
        "oly_badges_first5": oly_badges[:5],
        "oly_no_approx": oly_no_approx,
        "oly_monotonic": monotonic,
        "tko_group_headers": tko_groups,
        "tko_bucket4_ids": cards_in_bucket4,
        "tko_bucket4_badges": bucket4_badges,
        "all_bucket4_area": all_bucket4_area,
        "area_group_present": area_group_present,
        "tko_count": tko_count,
    }

    out["zh_console_errors"] = list(console_errors)
    return out


async def _check_en(browser, zh_out: dict) -> dict:
    page, console_errors = await _new_page(browser)
    await page.goto(EN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(300)
    out: dict[str, Any] = {"console_errors": list(console_errors)}

    # A: zh EN number parity for non-area
    expected_a = {"": 906, "oliver": 8, "麥當勞": 2, "海泓道": 2, "奧海城": 4, "outback": 0}
    out["A"] = {}
    for q, exp in expected_a.items():
        await _set_query(page, q)
        res = await _read_results(page)
        text_count = _count_from_text(res["countText"])
        actual = text_count if text_count is not None else len(res["visibleIds"])
        ok = "✓" if actual == exp else "✗"
        _print("E", f"{ok} EN q={q!r} expected={exp} actual={actual} (text={res['countText']!r})")
        out["A"][q] = actual

    # B: area-mode parity
    expected_b = {
        "Olympic": 32,
        "Tai Kok Tsui": 71,
        "Tsim Sha Tsui": 82,
        "Taikoo": 11,
        "Tseung Kwan O": 26,
    }
    # English user can type either English alias (mapped in ALIAS_GROUPS) or the
    # CJK area key directly. We test by typing the Chinese area key (the area
    # detection runs on the raw query regardless of language).
    cjk_for = {
        "Olympic": "奧運",
        "Tai Kok Tsui": "大角咀",
        "Tsim Sha Tsui": "尖沙咀",
        "Taikoo": "太古",
        "Tseung Kwan O": "將軍澳",
    }
    out["B"] = {}
    for label, q_zh in cjk_for.items():
        await _set_query(page, q_zh)
        res = await _read_results(page)
        text_count = _count_from_text(res["countText"])
        actual = text_count if text_count is not None else len(res["visibleIds"])
        ok = "✓" if actual == expected_b[label] else "✗"
        # Header label should be the English alias (since we typed CJK)
        label_text = res["headerLabel"]
        _print("E", f"{ok} EN {label} ({q_zh}) expected={expected_b[label]} actual={actual} headerLabel={label_text!r}")
        out["B"][label] = {"q": q_zh, "count": actual, "headerLabel": label_text}

    # chips visible on EN pure area query
    await _set_query(page, "奧運")
    res = await _read_results(page)
    _print("E", f"{'✓' if res['chipsVisible'] else '✗'} EN 奧運 chips visible={res['chipsVisible']}")
    out["B"]["chipsVisible_Olympic"] = res["chipsVisible"]
    # meta text check
    _print("E", f"EN 奧運 header meta={res['headerMeta']!r} (expect '32 venues (nearest first)')")
    out["B"]["Olympic_meta"] = res["headerMeta"]

    # 500m chip on EN: should give same number as zh
    await _click_chip(page, 500)
    res500 = await _read_results(page)
    text_count = _count_from_text(res500["countText"])
    actual500 = text_count if text_count is not None else len(res500["visibleIds"])
    _print("E", f"{'✓' if actual500==19 else '✗'} EN 奧運 500m expected=19 actual={actual500} (text={res500['countText']!r})")
    out["B"]["Olympic_500m"] = actual500
    # back to 1km
    await _click_chip(page, 1000)
    await page.wait_for_timeout(120)

    # C: FilterTokens non-empty in EN
    await _set_query(page, "Olympic Outback")
    res = await _read_results(page)
    text_count = _count_from_text(res["countText"])
    actual = text_count if text_count is not None else len(res["visibleIds"])
    _print("E", f"{'✓' if actual==0 else '✗'} EN 'Olympic Outback' expected=0 actual={actual} chipsHidden={not res['chipsVisible']}")
    out["C_en"] = {"Olympic Outback": actual}

    # EN dist badges + monotonic + bucket header
    # EN mirrors zh: precise records first with numeric "N m · N-min walk";
    # area-prec records show "Approximate" badge and live under group
    # header "Approximate location".
    import re as _re_en2  # local alias to keep D-section independent
    _print("E", "EN dist badges + monotonic + area-only fix")

    await _set_query(page, "奧運")
    await page.wait_for_timeout(120)
    oly = await _read_results(page)
    oly_badges = oly["distBadges"][:30]
    oly_with_num = []
    for b in oly_badges:
        m = _re_en2.match(r"([\d.]+)\s*(m|km)\b", b)
        if m:
            val = float(m.group(1))
            oly_with_num.append(val if m.group(2) == "m" else val * 1000)
    monotonic = all(oly_with_num[i] <= oly_with_num[i+1] for i in range(len(oly_with_num)-1))
    oly_no_approx = not any(b.startswith("~") for b in oly_badges)
    _print("E", f"EN 奧運 badges[:5]={oly_badges[:5]} oly_no_approx={oly_no_approx} monotonic={monotonic} (n={len(oly_with_num)})")
    _print("E", f"{'✓' if oly_no_approx else '✗'} EN 奧運 no '~' prefix anywhere")
    _print("E", f"{'✓' if monotonic   else '✗'} EN 奧運 first30 distances non-decreasing")

    # 將軍澳 (EN: queries via CJK, area detection is language-independent)
    await _set_query(page, "將軍澳")
    await page.wait_for_timeout(120)
    tko_groups = await page.evaluate(
        """() => {
            const groups = document.querySelectorAll('.area-group-header');
            return Array.from(groups).map(g => ({
              label: (g.textContent || '').trim(),
              visible: g.offsetParent !== null,
            }));
        }"""
    )
    area_group_present = any(g["visible"] and g["label"] == "Approximate location" for g in tko_groups)
    _print("E", f"EN 將軍澳 group headers={tko_groups}  area_group_present={area_group_present}")

    cards_after = await page.evaluate(
        """() => {
            const list = document.getElementById('restaurant-list');
            if (!list) return [];
            const out = [];
            for (const child of list.children) {
              if (child.classList.contains('area-group-header')) {
                out.push({ kind: 'group', label: (child.textContent || '').trim() });
              } else if (child.classList.contains('restaurant-item')) {
                const m = (child.getAttribute('href') || '').match(/\\/restaurants\\/(\\d+)/);
                if (m) out.push({ kind: 'card', id: Number(m[1]) });
              }
            }
            return out;
        }"""
    )
    cards_in_bucket4 = []
    seen_header = False
    for n in cards_after:
        if n["kind"] == "group":
            if n["label"] == "Approximate location":
                seen_header = True
            else:
                if seen_header:
                    break
            continue
        if seen_header:
            cards_in_bucket4.append(n["id"])
    _print("E", f"EN 將軍澳 cards in bucket 'Approximate location' (ids) = {cards_in_bucket4}")

    tko_dom = await page.evaluate(
        """() => {
            const list = document.getElementById('restaurant-list');
            if (!list) return [];
            const out = [];
            for (const child of list.children) {
              if (!child.classList.contains('restaurant-item')) continue;
              const m = (child.getAttribute('href') || '').match(/\\/restaurants\\/(\\d+)/);
              if (!m) continue;
              const badge = child.querySelector('.dist-badge');
              out.push({
                id: Number(m[1]),
                badge: badge ? (badge.textContent || '').trim() : null,
              });
            }
            return out;
        }"""
    )
    tko_badge_by_id = {row["id"]: row["badge"] for row in tko_dom}
    bucket4_badges = [tko_badge_by_id.get(cid) for cid in cards_in_bucket4]
    all_bucket4_area = all(b == "Approximate" for b in bucket4_badges if b)
    _print("E", f"EN bucket4 badges={bucket4_badges} all ='Approximate'? {all_bucket4_area}")
    _print("E", f"{'✓' if area_group_present else '✗'} EN 將軍澳 'Approximate location' group header present")
    _print("E", f"{'✓' if all_bucket4_area else '✗'} EN 將軍澳 bucket4 cards all show 'Approximate' ({len([b for b in bucket4_badges if b == 'Approximate'])}/{len(bucket4_badges)})")
    out["D_en"] = {
        "oly_badges_first5": oly_badges[:5],
        "oly_no_approx": oly_no_approx,
        "oly_monotonic": monotonic,
        "tko_group_headers": tko_groups,
        "tko_bucket4_ids": cards_in_bucket4,
        "tko_bucket4_badges": bucket4_badges,
        "all_bucket4_area": all_bucket4_area,
        "area_group_present": area_group_present,
    }

    out["en_console_errors"] = list(console_errors)
    return out


def _check_dist_sizes() -> dict:
    out = {}
    for label, path in [
        ("zh_raw_gz", ROOT / "dist/restaurants/index.html"),
        ("en_raw_gz", ROOT / "dist/en/restaurants/index.html"),
    ]:
        raw = path.stat().st_size
        gz = len(gzip.compress(path.read_bytes()))
        out[label] = {"raw": raw, "gzip": gz}
        _print("F", f"{path.name} raw={raw} gzip={gz}")
    return out


async def _run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4321")
    args = parser.parse_args()

    # Lazy import — playwright is heavy and may not be present in some envs.
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            zh_out = await _check_zh(browser)
            en_out = await _check_en(browser, zh_out)
        finally:
            await browser.close()
    fs_out = _check_dist_sizes()
    summary = {
        "zh": zh_out,
        "en": en_out,
        "dist": fs_out,
    }
    out_path = ROOT / "scripts/verify_search_report.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    _print("summary", f"report written to {out_path}")
    # Console error gate
    ce_zh = zh_out.get("zh_console_errors", [])
    ce_en = en_out.get("en_console_errors", [])
    if ce_zh or ce_en:
        _print("ERRORS", f"zh={len(ce_zh)} en={len(ce_en)}")
        for e in ce_zh[:10]:
            _print("ERRORS-zh", e)
        for e in ce_en[:10]:
            _print("ERRORS-en", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
