#!/usr/bin/env python3
"""
build_restaurant_types.py

Reads src/data/restaurants.json and produces src/data/restaurant-types.json
mapping restaurant id (string) → { types: [<zh category>...], source: "name-infer" }
(or "osm" for records enriched from /tmp/overpass_hk.json).

Matching rules follow /tmp/cuisine_rules.md (父側規格, 2026-09-12):
  * Only use name_zh + name_en, lowercased substring match.
  * "寧缺勿錯" — pure-numeric names, generic place names, ambiguous
    single-character/short names → do NOT tag.
  * Each record: up to 2 categories, ordered by keyword specificity
    (longer/more-specific keywords win).
  * Records with no match are NOT written to the output file (keep file small).
  * If /tmp/overpass_hk.json exists, enrich matching OSM records with
    cuisine/opening_hours/website and source="osm". Never re-fetch.

This script is idempotent: rerunning it regenerates the file from scratch.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESTAURANTS_JSON = REPO / "src" / "data" / "restaurants.json"
TYPES_JSON = REPO / "src" / "data" / "restaurant-types.json"
OSM_PATH = Path("/tmp/overpass_hk.json")

# English display map (mirrors /tmp/cuisine_rules.md "類別英文對照")
EN_MAP: dict[str, str] = {
    "咖啡": "Coffee",
    "酒吧": "Bar",
    "茶飲": "Bubble tea",
    "茶餐廳": "Cha chaan teng",
    "港式大排檔": "Dai pai dong",
    "港式燒味": "Cantonese roast",
    "火鍋": "Hot pot",
    "點心": "Dim sum",
    "壽司／刺身": "Sushi & sashimi",
    "拉麵／烏冬": "Ramen & udon",
    "日式": "Japanese",
    "日式燒肉": "Yakiniku",
    "韓式": "Korean",
    "泰越星馬": "Thai / Viet / SEA",
    "西餐": "Western",
    "法式": "French",
    "中菜": "Chinese",
    "中式地方菜": "Regional Chinese",
    "粉麵": "Noodles",
    "粥品": "Congee",
    "海鮮": "Seafood",
    "串燒燒烤": "Skewers & BBQ",
    "素食": "Vegetarian",
    "甜品／烘焙": "Dessert & bakery",
    "印度尼泊爾": "Indian & Nepali",
    "台灣": "Taiwanese",
}

# Keyword → category map. Keywords are matched as case-insensitive substrings
# against `name_zh + " " + name_en` (lowercased). Each keyword carries an
# implicit "specificity" weight: longer keywords are more specific and beat
# shorter ones in the priority order so e.g. "拉麵" wins over "日式".
#
# Order in the dict doesn't matter; we sort at runtime by keyword length desc.
KEYWORD_RULES: list[tuple[str, str]] = [
    # 咖啡
    ("咖啡", "咖啡"), ("coffee", "咖啡"), ("cafe", "咖啡"), ("café", "咖啡"),
    ("espresso", "咖啡"), ("roaster", "咖啡"), ("brew", "咖啡"), ("brewery", "咖啡"),
    ("latte", "咖啡"), ("barista", "咖啡"), ("arabica", "咖啡"), ("starbucks", "咖啡"),
    ("%arabica", "咖啡"), ("% arabica", "咖啡"),
    # 酒吧
    ("酒吧", "酒吧"), ("pub", "酒吧"), ("lounge", "酒吧"), ("啤酒", "酒吧"),
    ("beer", "酒吧"), ("taproom", "酒吧"), ("wine", "酒吧"), ("whisky", "酒吧"),
    # 茶飲
    ("茶飲", "茶飲"), ("奶茶", "茶飲"), ("台式飲品", "茶飲"), ("bubble tea", "茶飲"),
    ("珍珠", "茶飲"), ("手搖", "茶飲"),
    # 茶餐廳
    ("茶餐廳", "茶餐廳"), ("冰室", "茶餐廳"), ("冰廳", "茶餐廳"),
    ("茶室", "茶餐廳"), ("cha chaan", "茶餐廳"),
    # 港式大排檔
    ("大排檔", "港式大排檔"), ("大牌檔", "港式大排檔"), ("茶檔", "港式大排檔"),
    # 港式燒味
    ("燒味", "港式燒味"), ("燒腊", "港式燒味"), ("燒臘", "港式燒味"),
    ("鹵味", "港式燒味"), ("滷味", "港式燒味"), ("燒鵝", "港式燒味"),
    ("乳豬", "港式燒味"), ("siu mei", "港式燒味"),
    # 火鍋
    ("火鍋", "火鍋"), ("hot pot", "火鍋"), ("打邊爐", "火鍋"),
    ("雞煲", "火鍋"), ("麻辣鍋", "火鍋"), ("shabu", "火鍋"),
    # 點心
    ("點心", "點心"), ("dim sum", "點心"), ("酒樓", "點心"),
    ("飲茶", "點心"), ("燒賣", "點心"), ("蝦餃", "點心"),
    # 壽司／刺身 (specific beats generic)
    ("壽司", "壽司／刺身"), ("sushi", "壽司／刺身"), ("刺身", "壽司／刺身"),
    ("sashimi", "壽司／刺身"), ("居酒屋", "壽司／刺身"), ("izakaya", "壽司／刺身"),
    # 拉麵／烏冬
    ("拉麵", "拉麵／烏冬"), ("ramen", "拉麵／烏冬"), ("沾麵", "拉麵／烏冬"),
    ("烏冬", "拉麵／烏冬"), ("udon", "拉麵／烏冬"),
    # 日式 (generic — must be ordered AFTER sushi/ramen/izakaya etc.)
    ("日本料理", "日式"), ("japanese", "日式"), ("鐵板", "日式"),
    ("天婦羅", "日式"), ("tempura", "日式"), ("丼", "日式"), ("donburi", "日式"),
    ("和食", "日式"),
    # 日式燒肉
    ("燒肉", "日式燒肉"), ("和牛", "日式燒肉"), ("壽喜燒", "日式燒肉"),
    ("yakiniku", "日式燒肉"), ("wagyu", "日式燒肉"),
    # 韓式
    ("韓", "韓式"), ("korean", "韓式"), ("kimchi", "韓式"),
    ("泡菜", "韓式"), ("部隊鍋", "韓式"),
    # 泰越星馬
    ("泰式", "泰越星馬"), ("泰國", "泰越星馬"), ("泰", "泰越星馬"), ("thai", "泰越星馬"),
    ("越南", "泰越星馬"), ("viet", "泰越星馬"), ("pho", "泰越星馬"),
    ("冬蔭", "泰越星馬"), ("星馬", "泰越星馬"), ("新加坡", "泰越星馬"),
    ("南洋", "泰越星馬"), ("海南雞", "泰越星馬"),
    # 西餐
    ("西餐", "西餐"), ("西式", "西餐"), ("扒房", "西餐"),
    ("steak", "西餐"), ("grill", "西餐"), ("bistro", "西餐"),
    ("western", "西餐"), ("pasta", "西餐"), ("意粉", "西餐"),
    ("意大利", "西餐"), ("pizza", "西餐"), ("薄餅", "西餐"),
    # 法式
    ("法國", "法式"), ("french", "法式"),
    # 中菜 (generic)
    ("小館", "中菜"), ("菜館", "中菜"), ("飯店", "中菜"),
    ("酒家", "中菜"), ("私房菜", "中菜"),
    # 中式地方菜 (specific beats generic 中菜)
    ("川菜", "中式地方菜"), ("四川", "中式地方菜"), ("湘菜", "中式地方菜"),
    ("上海菜", "中式地方菜"), ("京菜", "中式地方菜"), ("北京", "中式地方菜"),
    ("潮州", "中式地方菜"), ("潮式", "中式地方菜"), ("打冷", "中式地方菜"),
    ("順德", "中式地方菜"), ("客家", "中式地方菜"), ("雲南", "中式地方菜"),
    ("新疆", "中式地方菜"), ("東北", "中式地方菜"), ("澳門", "中式地方菜"),
    ("葡國", "中式地方菜"),
    # 粉麵 (specific beats generic)
    ("粉麵", "粉麵"), ("麵店", "粉麵"), ("麵家", "粉麵"), ("米線", "粉麵"),
    ("雲吞", "粉麵"), ("車仔麵", "粉麵"), ("魚蛋", "粉麵"),
    ("河粉", "粉麵"), ("noodle", "粉麵"),
    # 粥品
    ("粥", "粥品"), ("congee", "粥品"), ("porridge", "粥品"),
    # 海鮮
    ("海鮮", "海鮮"), ("seafood", "海鮮"),
    # 串燒燒烤
    ("串燒", "串燒燒烤"), ("燒烤", "串燒燒烤"), ("yakitori", "串燒燒烤"),
    ("skewer", "串燒燒烤"), ("bbq", "串燒燒烤"),
    # 素食
    ("素食", "素食"), ("齋", "素食"), ("vegetarian", "素食"), ("vegan", "素食"),
    # 甜品／烘焙
    ("甜品", "甜品／烘焙"), ("糖水", "甜品／烘焙"), ("dessert", "甜品／烘焙"),
    ("雪糕", "甜品／烘焙"), ("ice cream", "甜品／烘焙"), ("gelato", "甜品／烘焙"),
    ("蛋糕", "甜品／烘焙"), ("烘焙", "甜品／烘焙"), ("餅店", "甜品／烘焙"),
    ("餅家", "甜品／烘焙"), ("麵包", "甜品／烘焙"), ("bakery", "甜品／烘焙"),
    # 印度尼泊爾
    ("印度", "印度尼泊爾"), ("indian", "印度尼泊爾"), ("咖喱", "印度尼泊爾"),
    ("curry", "印度尼泊爾"), ("尼泊爾", "印度尼泊爾"), ("nepal", "印度尼泊爾"),
    # 台灣
    ("台式", "台灣"), ("taiwan", "台灣"), ("滷肉", "台灣"), ("鹹酥雞", "台灣"),
]

# Sort rules longest-keyword first so the most specific wins when a name has
# multiple matches (e.g. "日式拉麵" → "拉麵／烏冬" beats "日式").
KEYWORD_RULES_SORTED = sorted(KEYWORD_RULES, key=lambda kv: (-len(kv[0]), kv[0]))

# Generic / ambiguous terms that we will SKIP even if a category keyword
# happens to appear. e.g. "素" alone is too generic, "齋" alone is too generic.
# (We don't add anything that would block a real keyword; this list is a guard.)
GENERIC_BLACKLIST: set[str] = set()


# --- OSM cuisine → category mapping (only used when /tmp/overpass_hk.json exists) ---
# OSM cuisine tags are comma/semicolon separated, e.g. "chinese;hotpot".
# Map each OSM cuisine tag value to our category.
OSM_CUISINE_MAP: dict[str, str] = {
    "thai": "泰越星馬",
    "vietnamese": "泰越星馬",
    "indian": "印度尼泊爾",
    "nepalese": "印度尼泊爾",
    "chinese": "中菜",
    "cantonese": "中菜",
    "sichuan": "中式地方菜",
    "hunan": "中式地方菜",
    "shanghai": "中式地方菜",
    "beijing": "中式地方菜",
    "teochew": "中式地方菜",
    "taiwanese": "台灣",
    "korean": "韓式",
    "japanese": "日式",
    "sushi": "壽司／刺身",
    "ramen": "拉麵／烏冬",
    "udon": "拉麵／烏冬",
    "yakiniku": "日式燒肉",
    "hotpot": "火鍋",
    "hot_pot": "火鍋",
    "shabu-shabu": "火鍋",
    "barbecue": "串燒燒烤",
    "bbq": "串燒燒烤",
    "pizza": "西餐",
    "pasta": "西餐",
    "steak": "西餐",
    "french": "法式",
    "italian": "西餐",
    "seafood": "海鮮",
    "noodle": "粉麵",
    "congee": "粥品",
    "dim_sum": "點心",
    "bubble_tea": "茶飲",
    "bubble tea": "茶飲",
    "coffee": "咖啡",
    "coffee_shop": "咖啡",
    "cafe": "咖啡",
    "bakery": "甜品／烘焙",
    "dessert": "甜品／烘焙",
    "ice_cream": "甜品／烘焙",
    "vegetarian": "素食",
    "vegan": "素食",
    "regional": "中式地方菜",  # fallback only used if specific chinese region present
    "international": "",  # no good category; ignore
}


def _norm_name(s: str) -> str:
    return (s or "").strip().lower()


def _strip_punct(s: str) -> str:
    # Keep alnum + CJK + a few connector chars (／, -, &). Drop other punctuation
    # so "（大安）" → "大安" and "co., ltd." → "co ltd".
    return re.sub(r"[，。、！？：；（）「」『』·\.\,\?\!\:\;\(\)\[\]\"\'`]", " ", s or "")


def _is_ambiguous(name_zh: str, name_en: str) -> bool:
    """寧缺勿錯 gate: skip names we cannot reliably categorise."""
    zh = _strip_punct(name_zh).strip()
    en = _norm_name(name_en)
    combined = f"{zh} {en}".strip()
    if not combined:
        return True
    # Pure digits / year / "1987 plus"
    if re.fullmatch(r"[\d\s\-+&/]+", combined):
        return True
    # Single-char zh names are essentially always ambiguous (大安, 大龍鳳, ...)
    # unless they contain a category keyword (handled by the keyword stage).
    if len(zh) <= 1 and not en:
        return True
    # English-only single short word with no clear cuisine signal
    if not zh and len(en.split()) <= 1 and len(en) <= 3:
        return True
    return False


def _classify(name_zh: str, name_en: str) -> list[str]:
    """Return up to 2 category names (zh) ordered by specificity."""
    combined = f"{_strip_punct(name_zh)} {_norm_name(name_en)}".lower()
    if not combined.strip():
        return []
    hits: list[tuple[int, str, str]] = []  # (kw_len, kw, category)
    for kw, cat in KEYWORD_RULES_SORTED:
        if kw.lower() in combined:
            hits.append((len(kw), kw, cat))
    if not hits:
        return []
    # Sort: longest keyword first, then earliest occurrence in combined as
    # tiebreaker (gives stable, sensible order).
    hits.sort(key=lambda h: (-h[0], combined.find(h[1].lower())))
    cats: list[str] = []
    for _, _, cat in hits:
        if cat and cat not in cats:
            cats.append(cat)
        if len(cats) >= 2:
            break
    return cats


# ---------------------------------------------------------------------------
# OSM enrichment
# ---------------------------------------------------------------------------

def _osm_index(path: Path) -> dict[str, dict]:
    """Build name_zh → OSM-element index from the Overpass dump."""
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    out: dict[str, dict] = {}
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        names_to_index: list[str] = []
        for k in ("name:zh", "name"):
            n = tags.get(k)
            if n:
                names_to_index.append(n)
        for n in names_to_index:
            key = _norm_name(n)
            if key and key not in out:
                out[key] = {"tags": tags}
    return out


def _osm_cuisine_to_cats(cuisine_field: str) -> list[str]:
    cats: list[str] = []
    if not cuisine_field:
        return cats
    for piece in re.split(r"[;,]", cuisine_field):
        p = piece.strip().lower()
        if not p:
            continue
        # Try direct match, then normalized.
        cat = OSM_CUISINE_MAP.get(p) or OSM_CUISINE_MAP.get(p.replace(" ", "_"))
        if cat and cat not in cats:
            cats.append(cat)
        if len(cats) >= 2:
            break
    return cats


def _match_osm_for_restaurant(r: dict, osm_idx: dict[str, dict]) -> dict | None:
    """Return OSM enrichment dict (with 'types' resolved) or None."""
    if not osm_idx:
        return None
    # Try matching by name_zh first, then name_en.
    candidates = [_norm_name(r.get("name_zh", "")), _norm_name(r.get("name_en", ""))]
    for nm in candidates:
        if not nm:
            continue
        # Exact match first
        hit = osm_idx.get(nm)
        # Try removing trailing spaces / common suffixes
        if not hit:
            hit = osm_idx.get(nm.rstrip())
        if hit:
            tags = hit["tags"]
            cats = _osm_cuisine_to_cats(tags.get("cuisine", ""))
            if not cats:
                return None
            out: dict = {"types": cats[:2], "source": "osm"}
            if tags.get("opening_hours"):
                out["opening_hours"] = tags["opening_hours"]
            if tags.get("website"):
                out["website"] = tags["website"]
            return out
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not RESTAURANTS_JSON.exists():
        print(f"FATAL: {RESTAURANTS_JSON} not found", file=sys.stderr)
        return 1
    with RESTAURANTS_JSON.open() as f:
        restaurants = json.load(f)

    osm_idx = _osm_index(OSM_PATH)
    osm_used = 0
    osm_skipped = 0

    out: dict[str, dict] = {}
    coverage = 0
    multi = 0
    dist: dict[str, int] = {}

    for r in restaurants:
        rid = str(r["id"])
        # Ambiguous-name gate runs BEFORE any OSM enrichment too.
        if _is_ambiguous(r.get("name_zh", ""), r.get("name_en", "")):
            osm_skipped += 1
            continue
        cats = _classify(r.get("name_zh", ""), r.get("name_en", ""))
        osm_extra: dict | None = None
        if cats:
            entry: dict = {"types": cats, "source": "name-infer"}
            out[rid] = entry
            coverage += 1
            if len(cats) > 1:
                multi += 1
            for c in cats:
                dist[c] = dist.get(c, 0) + 1
        else:
            # No keyword hit — try OSM enrichment.
            osm_extra = _match_osm_for_restaurant(r, osm_idx)
            if osm_extra:
                out[rid] = osm_extra
                coverage += 1
                if len(osm_extra["types"]) > 1:
                    multi += 1
                for c in osm_extra["types"]:
                    dist[c] = dist.get(c, 0) + 1
                osm_used += 1
            else:
                # Truly nothing — skip per spec.
                continue

    TYPES_JSON.parent.mkdir(parents=True, exist_ok=True)
    with TYPES_JSON.open("w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)

    total = len(restaurants)
    print(f"wrote {TYPES_JSON.relative_to(REPO)}")
    print(f"  total records:     {total}")
    print(f"  tagged:            {coverage} ({coverage*100/total:.1f}%)")
    print(f"  multi-tag:         {multi}")
    print(f"  osm-enriched:      {osm_used}")
    print(f"  ambiguous skipped: {osm_skipped}")
    print(f"  category distribution:")
    for cat, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"    {n:>4}  {cat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
