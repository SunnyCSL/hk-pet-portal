"""Playwright smoke test for the new area pages.

Verifies:
  1. Pages return 200 and render expected structural elements (H1, stats, list, map).
  2. JS island renders the full list when "Show all" is clicked.
  3. Mini map markers are added.
  4. NO forbidden content (rating, price, editorial review, shop descriptions).
  5. JSON-LD is valid and contains Place + ItemList.
"""
import re
import sys
import json
from playwright.sync_api import sync_playwright

BASE = "http://localhost:4321"

# Sample areas: high density, mid, low density, islet, edge case.
SAMPLES = [
    "central",       # 123 in 2km
    "mong-kok",      # 138 in 2km
    "ma-on-shan",    # 14 in 2km
    "clear-water-bay",  # fallback 5km
    "fanling",       # 6 in 2km (boundary case)
    "lamma-island",  # 6 in 2km
]

FORBIDDEN_KEYWORDS = [
    "評分", "★", "星級", "推薦", "必試", "人氣", "排隊", "CP值", "抵食",
    "編輯推介", "推介", "點評", "顧客評價", "好評", "差評", "味道", "服務態度",
    "人氣餐廳", "熱門", "5星", "4星", "3星", "2星", "1星",
    "$", "HK$", "MOP", "人均", "價位", "套餐價", "午市價", "晚市價",
    "★", "☆", "❤", "👍",  # rating emojis
    "寵物餐牌", "狗餐牌", "狗糧", "狗蛋糕",  # service descriptions
]


def check_page(page, slug: str, errors: list) -> None:
    url = f"{BASE}/restaurants/area/{slug}/"
    print(f"\n=== {slug} → {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=15000)
    if not resp or resp.status != 200:
        errors.append(f"{slug}: HTTP {resp.status if resp else 'no resp'}")
        return

    # Title
    title = page.title()
    if "HK Pet Portal" not in title:
        errors.append(f"{slug}: title missing site name: {title!r}")

    # H1 contains the area name
    h1 = page.locator("h1").first.text_content() or ""
    print(f"  H1: {h1.strip()[:80]}")

    # Meta description present
    desc = page.locator('meta[name="description"]').get_attribute("content") or ""
    if len(desc) < 30:
        errors.append(f"{slug}: description too short: {desc!r}")
    print(f"  desc: {desc[:120]}...")

    # Canonical
    canonical = page.locator('link[rel="canonical"]').get_attribute("href") or ""
    if f"/restaurants/area/{slug}" not in canonical:
        errors.append(f"{slug}: canonical wrong: {canonical}")

    # Hreflang: should have zh-HK + x-default; no en (noEnAlternate)
    hreflangs = page.locator('link[rel="alternate"][hreflang]').all()
    langs = [(l.get_attribute("hreflang") or "") for l in hreflangs]
    if "zh-HK" not in langs:
        errors.append(f"{slug}: no zh-HK hreflang: {langs}")
    if any(l == "en" for l in langs):
        errors.append(f"{slug}: unexpected en hreflang: {langs}")

    # Stats grid present (2km/radius + 500m + 1km + total area)
    stats_count = page.locator('section[aria-label="地區統計"] .text-2xl').count()
    if stats_count != 4:
        errors.append(f"{slug}: expected 4 stat tiles, got {stats_count}")

    # Nearby list
    nearby_items = page.locator("#nearby-list .nearby-item")
    item_count = nearby_items.count()
    print(f"  nearby items: {item_count}")
    if item_count == 0:
        errors.append(f"{slug}: nearby list empty")

    # Mini map
    map_el = page.locator("#area-map")
    if not map_el.is_visible():
        errors.append(f"{slug}: map not visible")

    # Neighbouring areas section
    neighbours = page.locator('section[aria-label="相鄰地區導覽"] a')
    n_count = neighbours.count()
    print(f"  neighbours: {n_count}")
    if n_count == 0:
        errors.append(f"{slug}: no neighbouring areas")

    # JSON-LD
    scripts = page.locator('script[type="application/ld+json"]').all()
    types_found = []
    for s in scripts:
        try:
            d = json.loads(s.text_content() or "{}")
            t = d.get("@type")
            if t: types_found.append(t)
        except json.JSONDecodeError as e:
            errors.append(f"{slug}: bad JSON-LD: {e}")
    print(f"  JSON-LD types: {types_found[:6]}")
    if "ItemList" not in types_found:
        errors.append(f"{slug}: no ItemList JSON-LD")
    if "Place" not in types_found:
        errors.append(f"{slug}: no Place JSON-LD")

    # Forbidden content scan
    body_text = page.locator("body").inner_text()
    body_lower = body_text
    bad_found = [k for k in FORBIDDEN_KEYWORDS if k in body_lower]
    if bad_found:
        errors.append(f"{slug}: forbidden keywords found: {bad_found}")

    # No "shop description" markers — distinct from generic 'desc' / meta-desc.
    # Look for content like "X 餐廳係一間..." or "店內有..." style phrases.
    if re.search(r"[店餐廳舖].{0,15}(環境|裝修|氣氛|風格|招牌菜)", body_text):
        errors.append(f"{slug}: editorial description phrase detected")

    # Show-all button test (only if island rows exist)
    show_btn = page.locator("#show-all")
    if show_btn.count() > 0 and show_btn.is_visible():
        before = page.locator("#nearby-list .nearby-item").count()
        show_btn.click()
        page.wait_for_timeout(300)
        after = page.locator("#nearby-list .nearby-item").count()
        print(f"  show-all: {before} → {after}")
        if after <= before:
            errors.append(f"{slug}: show-all did not expand list ({before} → {after})")
        if after > 200:
            errors.append(f"{slug}: show-all expanded too much ({after} > 200 cap)")
    else:
        print(f"  show-all: not shown (no island rows)")

    # Map markers — wait for Leaflet to attach
    page.wait_for_timeout(500)
    markers = page.locator(".leaflet-marker-icon").count()
    print(f"  map markers: {markers}")
    if markers < 2:  # at least area-centre + 1 nearby
        errors.append(f"{slug}: expected ≥2 map markers, got {markers}")


def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844})  # mobile viewport
        page = ctx.new_page()
        for slug in SAMPLES:
            try:
                check_page(page, slug, errors)
            except Exception as e:
                errors.append(f"{slug}: exception {type(e).__name__}: {e}")
        browser.close()

    print(f"\n\n=== SUMMARY ===")
    print(f"Pages tested: {len(SAMPLES)}")
    print(f"Errors: {len(errors)}")
    for e in errors:
        print(f"  - {e}")
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()