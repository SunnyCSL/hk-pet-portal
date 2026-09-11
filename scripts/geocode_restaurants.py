#!/usr/bin/env python3
"""
Geocode hk-pet-portal restaurants using HK Government CSDI Location Search API.

Scoring-based selection (NOT result[0]) — for each candidate query we score
every returned CSDI hit, then take the best-scoring hit that satisfies the
acceptance gate. Cached raw responses live in scripts/.geocode_cache.json so
reruns don't burn API quota.

Outputs:
  - src/data/restaurant-coords.json    (per-row: lat/lng/prec/src/q/score/alt)
  - src/data/area-centres.json         (area name -> best centre coord)

Usage:
    ~/.hermes-venv/bin/python3 scripts/geocode_restaurants.py
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pyproj import Transformer

# ---------- paths ----------
REPO = Path(__file__).resolve().parents[1]
RESTAURANTS_JSON = REPO / "src" / "data" / "restaurants.json"
COORDS_OUT = REPO / "src" / "data" / "restaurant-coords.json"
AREA_OUT = REPO / "src" / "data" / "area-centres.json"
CACHE_PATH = REPO / "scripts" / ".geocode_cache.json"

# ---------- API ----------
CSDI_URL = "https://www.map.gov.hk/gs/api/v1.0.0/locationSearch"
UA = "Mozilla/5.0"
SLEEP_BETWEEN = 0.2  # sec between *network* calls (cache hits don't sleep)
WORKERS = 4  # concurrent records
MAX_RETRIES = 3

# ---------- HK bbox (hard filter on every candidate) ----------
LAT_MIN, LAT_MAX = 22.13, 22.60
LNG_MIN, LNG_MAX = 113.80, 114.45

# ---------- proj transformer ----------
transformer = Transformer.from_crs("EPSG:2326", "EPSG:4326", always_xy=True)


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    """HK1980 Grid -> WGS84 (lng, lat)."""
    lng, lat = transformer.transform(x, y)
    return lat, lng


# ---------- cache ----------
def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


_CACHE_LOCK = threading.Lock()
_CACHE_DIRTY = {"n": 0}


def save_cache(cache: dict, force: bool = False) -> None:
    """Persist raw-response cache. Flushed every ~10 new queries (and at the end)
    so a run that gets killed still resumes without re-hitting the API."""
    with _CACHE_LOCK:
        if not force and _CACHE_DIRTY["n"] < 10:
            return
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        _CACHE_DIRTY["n"] = 0


def note_cache_write(cache: dict) -> None:
    with _CACHE_LOCK:
        _CACHE_DIRTY["n"] += 1
    save_cache(cache)


# ---------- API call ----------
def csdi_search(query: str, cache: dict) -> list:
    """Return list of raw CSDI result dicts. Empty list if no hit.
    Caches by query string. Retries 3x on 5xx/timeout with exponential backoff.
    """
    if not query or not query.strip():
        return []
    q = query.strip()
    if q in cache:
        return cache[q]

    url = CSDI_URL + "?q=" + urllib.parse.quote(q)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            if not isinstance(data, list):
                data = []
            cache[q] = data
            note_cache_write(cache)
            return data
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if 500 <= e.code < 600:
                time.sleep(0.5 * (2 ** attempt))
                continue
            cache[q] = []
            note_cache_write(cache)
            return []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = repr(e)
            time.sleep(0.5 * (2 ** attempt))
            continue

    print(f"  WARN csdi fail q={q!r} err={last_err}", file=sys.stderr)
    cache[q] = []
    note_cache_write(cache)
    return []


def fetch_with_sleep(query: str, cache: dict) -> list:
    hit = bool(query) and query.strip() in cache
    res = csdi_search(query, cache)
    if not hit:
        time.sleep(SLEEP_BETWEEN)
    return res


# ---------- area centres (loaded lazily) ----------
def load_area_centres() -> dict:
    if AREA_OUT.exists():
        try:
            return json.loads(AREA_OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


AREAS = load_area_centres()
# Sort area names by length DESC so longer ("香港仔") beats shorter ("中環") in longest-match.
AREA_KEYS_SORTED = sorted(AREAS.keys(), key=lambda s: (-len(s), s))

# FEHD district name -> CSDI district name mapping (handles 油尖區/旺角區 -> 油尖旺區)
DISTRICT_FEHD_TO_CSDI = {
    "油尖區": "油尖旺區",
    "旺角區": "油尖旺區",
}


def csdi_district_for(fehd_district: str) -> str:
    return DISTRICT_FEHD_TO_CSDI.get(fehd_district, fehd_district)


# ---------- address cleaning ----------
_LEADING_REGION = re.compile(r"^(香港|九龍|新界|大嶼山)\s*")

# Tokens (regex) to strip — shop, floor, lot, etc. We replace with space.
DROP_TOKENS_RE = re.compile(
    r"(?:"
    r"短期租約[A-Z0-9-]*號?|"
    r"地下高層|高層地下|地庫|高層|閣樓|一樓|二樓|三樓|四樓|五樓|六樓|七樓|八樓|九樓|十樓|樓下|樓上|平臺|平台|"
    r"[A-Z一-鿿]/?F|"
    r"G層|G/?F|U/F|"
    r"[A-Z]座|"
    r"及[A-Z一二三四五六七八九十]部份|及[A-Z]部份|"
    r"A部份|B部份|C部份|D部份|"
    r"地下高層|地下低層|地下|"
    r"號鋪|號舖|號店|"
    r"[A-Za-z0-9]+室|"
    r"舖|鋪|室|"
    r"及鋪後露天座位|及鋪前露天座位|及露天座位|露天茶座|側露天茶座|"
    r"及餐廳|"
    r"主要部份|其餘部份|"
    r"丈量約份\s*\d+\s*段|丈量約份\s*\d+\s*段第[\u4e00-\u9fff\d]+段|"
    r"地段第[\u4e00-\u9fff\d]+號|"
    r"沙田市地段[\u4e00-\u9fff\d]+號|"
    r"短期租約[\u4e00-\u9fff\d]+號|"
    # unit-like suffix AFTER door number (e.g. "2號1B號鋪" -> "2號")
    r"\d+號\s*[A-Z]\d*號|\d+號\s*[A-Z]號"
    r")"
)


def clean(addr: str) -> str:
    """Drop floor / shop / unit descriptors; collapse whitespace."""
    s = addr
    # drop leading region prefix
    s = _LEADING_REGION.sub("", s)
    # iteratively strip noise tokens
    for _ in range(3):
        s2 = DROP_TOKENS_RE.sub(" ", s)
        if s2 == s:
            break
        s = s2
    # tidy spaces
    s = re.sub(r"\s{2,}", " ", s).strip(" ,;；")
    return s


# ---------- extractors ----------
# Street pattern: <chinese road name><number>號 — captures common HK road types.
_STREET_RE = re.compile(r"([\u4e00-\u9fff]{2,8}(?:道|街|里|徑|路))\s*(\d{1,5})\s*號")
_STREET_RANGE_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}(?:道|街|里|徑|路))\s*(\d+\s*[-－]\s*\d+\s*號)"
)

# Building-name suffix set — for extracting the building/mall name from address.
BUILDING_NAME_SUFFIX = (
    "大廈", "大樓", "中心", "廣場", "城", "坊", "閣", "樓", "苑", "邨",
    "匯", "滙", "薈", "軒", "臺", "台", "酒店", "花園", "新邨", "新苑",
    "花園大廈", "商業大廈", "工業大廈", "購物中心",
    "期", "翼",
)
# Pure-period (e.g. 奧海城3期) detection.
# Allow preceded by door number "X號" but not by another digit/letter.
_PERIOD_RE = re.compile(
    r"(?:^|(?<=\d號)|(?<=\s)|(?<=[A-Z]))([\u4e00-\u9fff]{1,12})\s*(\d{1,2})\s*期(?![\u4e00-\u9fffA-Za-z])"
)


def extract_street_num(addr: str) -> tuple[str | None, str | None]:
    """Return (street, num) where street is e.g. '永安街', num is e.g. '20號'."""
    m = _STREET_RE.search(addr)
    if m:
        return m.group(1), m.group(2) + "號"
    m = _STREET_RANGE_RE.search(addr)
    if m:
        return m.group(1), m.group(2).replace(" ", "")
    return None, None


def extract_building(addr: str) -> str | None:
    """Try to pluck the building/mall name out of an address.

    Returns the most-likely building string, or None if heuristics fail.
    """
    s = addr

    # 1. "<name><digits>期" (奧海城3期 etc)
    m = _PERIOD_RE.search(s)
    if m:
        cand = (m.group(1) + m.group(2) + "期").strip()
        if 2 <= len(cand) <= 24 and not cand.endswith(("道", "街", "里", "徑", "路")):
            return cand

    # 2. suffix-based: find chunk ending in known building suffix
    # BUT skip if the candidate is just "<digit>樓" or "<digit>翼" etc (floor-only)
    for suf in BUILDING_NAME_SUFFIX:
        idx = s.find(suf)
        if idx <= 0:
            continue
        start = idx
        while start > 0:
            ch = s[start - 1]
            if ch in " ,，、 \u3000":
                break
            # previous token says "x層", "x樓" etc — stop
            start -= 1
        cand = s[start : idx + len(suf)].strip()
        # Reject pure-floor like "3樓", "地庫" (just digit + 樓, etc.)
        if re.match(r"^\d+(?:樓|翼|期|座)$", cand):
            continue
        # Reject suffix-only like just "樓", "翼" (1 char)
        if len(cand) < 2:
            continue
        if 2 <= len(cand) <= 30 and not re.match(
            r"^[\u4e00-\u9fff]{0,3}[道街里徑路]$", cand
        ):
            return cand

    # 3. Fallback: grab first 2-14 Chinese chars before first digit
    m2 = re.search(r"\d", s)
    if m2:
        head = s[: m2.start()].strip().strip(",，、 ")
        head = re.sub(r"\s+", "", head)
        head = re.sub(r"^[A-Za-z\d]+號?", "", head)  # strip leading "1號", "A號" etc
        if 2 <= len(head) <= 14:
            return head
    return None


def extract_sub(addr: str) -> str | None:
    """Pick the best area name from `area-centres.json` keys for the address.

    Tie-break:
      (a) the area that occurs LATEST in the address (rfind) wins
      (b) on tie, the longer name wins
      (c) on tie, lexicographic first wins (deterministic)

    Rationale: addresses are written [region][sub], so the deepest area name
    appears last. id 453 '新界荃灣馬灣馬灣公園二期馬灣大街52A號' → 馬灣.
    """
    best: str | None = None
    best_pos: int = -1
    best_len: int = -1
    for k in AREAS.keys():
        idx = addr.rfind(k)
        if idx < 0:
            continue
        if idx > best_pos:
            best, best_pos, best_len = k, idx, len(k)
        elif idx == best_pos:
            lk = len(k)
            if lk > best_len or (lk == best_len and (best is None or k < best)):
                best, best_len = k, lk
    return best


# ---------- scoring ----------
# Regex helpers for candidate evaluation
_STREET_TAIL_RE = re.compile(r"[\u4e00-\u9fff]{2,8}(?:道|街|里|徑|路)")
_NUM_HOUSE_RE = re.compile(r"\d{1,5}\s*號")


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Geodetic distance in metres between two WGS84 points."""
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def score_candidate(
    cand: dict,
    street: str | None,
    num: str | None,
    building: str | None,
    sub_centre: tuple[float, float] | None,
    csdi_district_expected: str | None,
) -> tuple[float, dict]:
    """Return (score, breakdown). breakdown is the dict used to tag `prec`.

    Hard precondition: lat/lng in HK bbox. Caller filters before calling here.
    """
    name = (cand.get("nameZH") or "").strip()
    addr_zh = (cand.get("addressZH") or "").strip()
    district = (cand.get("districtZH") or "").strip()
    text = (name + " " + addr_zh).strip()
    text_norm = re.sub(r"\s+", "", text)

    s = 0.0
    bd: dict = {"street": 0, "num": 0, "bld": 0, "dist": 0, "dist_m": 0, "stat": 0}

    # street match — try exact first, then tolerate sub-name prefix on candidate
    # (e.g. street='西貢西貢海傍街', candidate='西貢海傍街' should match because
    # the tail '西貢海傍街' is identical).
    street_hit = False
    if street:
        if street in text:
            street_hit = True
        else:
            # try stripping area names from the front of the candidate street
            for area in AREA_KEYS_SORTED:
                # if street starts with area and the remainder still matches
                if street.startswith(area) and len(area) < len(street):
                    tail = street[len(area):]
                    if tail in text or tail in text_norm:
                        street_hit = True
                        break
                # also: candidate's name starts with area then street-tail
                if area + street in text or area + street in text_norm:
                    street_hit = True
                    break
    if street_hit:
        s += 40
        bd["street"] = 40

    # door number exact match
    if num:
        n_norm = num.replace(" ", "")
        if n_norm in text_norm:
            s += 30
            bd["num"] = 30

    # building name presence
    if building and building in text:
        s += 25
        bd["bld"] = 25

    # district match
    if csdi_district_expected and district == csdi_district_expected:
        s += 15
        bd["dist"] = 15

    # station / landmark penalty (nameZH ends with 站 or starts with 巴士總站 etc)
    if name.endswith("站") or name.endswith("總站"):
        s -= 20
        bd["stat"] = -20

    # distance to sub centre (closer = higher score)
    if sub_centre is not None:
        try:
            x = float(cand["x"])
            y = float(cand["y"])
            clat, clng = to_wgs84(x, y)
            dist_m = haversine_m(sub_centre[0], sub_centre[1], clat, clng)
            s -= dist_m / 50.0
            bd["dist_m"] = round(dist_m, 1)
        except (KeyError, ValueError):
            pass

    return s, bd


def passes_gate(
    score: float,
    breakdown: dict,
    sub_centre: tuple[float, float] | None,
    csdi_district_expected: str | None,
) -> bool:
    """Acceptance gate.

    Must satisfy (street hit OR door hit) OR (district hit AND distance to
    sub centre < 1500m).
    """
    if breakdown["street"] > 0 or breakdown["num"] > 0:
        return True
    if (
        breakdown["dist"] > 0
        and sub_centre is not None
        and breakdown["dist_m"] < 1500
    ):
        return True
    return False


def pick_best(
    results: list,
    street: str | None,
    num: str | None,
    building: str | None,
    sub: str | None,
    csdi_district_expected: str | None,
) -> tuple[dict | None, float, int, str, dict]:
    """Score every CSDI result and pick the best.

    Returns (best_cand, score, alt_count, prec, breakdown). best_cand is None if
    no candidate passes the gate.
    """
    sub_centre = None
    if sub and sub in AREAS:
        a = AREAS[sub]
        if a.get("lat") is not None and a.get("lng") is not None:
            sub_centre = (float(a["lat"]), float(a["lng"]))

    pool = []
    for r in results or []:
        if "x" not in r or "y" not in r:
            continue
        try:
            x = float(r["x"])
            y = float(r["y"])
            lat, lng = to_wgs84(x, y)
        except (ValueError, TypeError):
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
            continue
        pool.append(r)

    alt = len(pool)
    if not pool:
        return None, -1e9, 0, "area", {}

    best = None
    best_score = -1e9
    best_bd: dict = {}
    for r in pool:
        sc, bd = score_candidate(
            r, street, num, building, sub_centre, csdi_district_expected
        )
        if not passes_gate(sc, bd, sub_centre, csdi_district_expected):
            continue
        if sc > best_score:
            best_score = sc
            best = r
            best_bd = bd

    if best is None:
        return None, -1e9, alt, "area", {}

    if best_bd.get("bld", 0) > 0 or best_bd.get("num", 0) > 0:
        prec = "building"
    else:
        prec = "street"
    return best, best_score, alt, prec, best_bd


# ---------- main work ----------
def build_queries(addr: str) -> tuple[list[tuple[str, str]], dict]:
    """Build candidate query ladder.

    Returns (queries, parts) where queries = [(label, query_string), ...] and
    parts = extracted {street, num, building, sub}.
    """
    # 1. clean the address — drops leading 香港/九龍/新界 + noise tokens
    cleaned = clean(addr)

    # 2. extract street + door from CLEANED address (so the captured street is
    #    pure, not prefixed with "香港山頂道").
    street, num = extract_street_num(cleaned)
    # if not found in cleaned, try original
    if not street:
        street, num = extract_street_num(addr)

    # 3. building from CLEANED address (e.g. 奧海城3期, 山頂凌霄閣, 1E大廈)
    building = extract_building(cleaned)
    if not building:
        building = extract_building(addr)

    # 4. sub (longest-match area key from area-centres.json)
    sub = extract_sub(addr)  # use original to catch e.g. "白石角" mid-address
    if not sub:
        sub = extract_sub(cleaned)

    parts = {"street": street, "num": num, "building": building, "sub": sub}

    queries: list[tuple[str, str]] = []

    # ① sub + street + num  (most specific; rarely spurious)
    if sub and street and num:
        queries.append(("sub+street+num", f"{sub} {street} {num}"))
    elif sub and street:
        queries.append(("sub+street", f"{sub} {street}"))

    # ② street + num (skip if we already tried it as ①)
    if street and num:
        q2 = f"{street} {num}"
        if not any(q == q2 for _, q in queries):
            queries.append(("street+num", q2))

    # ③ building + street (with optional sub prefix)
    if building and street and street not in (building,):
        if sub:
            queries.append(("bld+street+sub", f"{sub} {building} {street}"))
        queries.append(("bld+street", f"{building} {street}"))

    # ④ building alone (last)
    if building and building not in (street or "",):
        queries.append(("building", building))

    # ⑤ sub alone (last-resort pin to area)
    if sub and not any(label.startswith("sub") for label, _ in queries):
        queries.append(("sub", sub))

    return queries, parts


def _is_garbage_query(q: str, AREAS: dict | None = None) -> bool:
    """Reject queries that are pure floor / unit / lot / seat tokens.

    Garbage: '3樓', '地下', '306鋪', 'A座', '地下低層', '及鋪前露天座位'.
    Also reject very short queries (<3 chars with no street/building
    anchor) — they have no useful location signal.

    IMPORTANT: if the query equals an area name in `area-centres.json`,
    it is treated as a legitimate sub-area fallback lookup and is allowed.
    """
    if not q or not q.strip():
        return True
    s = q.strip()
    # allow exact area-name lookups (step ⑤ of the query ladder)
    if AREAS is not None and s in AREAS:
        return False
    # drop leading region tokens / whitespace / common joiners for the length test
    s2 = re.sub(r"^(香港|九龍|新界|大嶼山)\s*", "", s).strip()
    # Pure floor/unit-like patterns
    if re.fullmatch(
        r"(?:\d+|[一二三四五六七八九十]+|地|地下|地庫|高層|低層|平臺|平台)?(?:樓|層|F|F\/|F/|G|F|G層|地|地庫|樓下|樓上|閣樓)"
        r"|(?:地下(?:高層|低層|高層地下|低層地下)?)"
        r"|\d+號(?:鋪|舖|店)?"
        r"|\d+[A-Z]?號?"
        r"|[A-Z]座"
        r"|[A-Z]\d{0,3}室"
        r"|\d+室"
        r"|\d+鋪|\d+舖"  # pure shop-number tokens like '306鋪' (without 號)
        r"|[A-Z]\d+號?(?:鋪|舖)?"
        r"|[A-Z]\d+"  # like 'A306'
        r"|(?:及)?(?:鋪前|鋪後)?露天(?:座位|茶座)?"
        r"|[A-Z]部份|[A-Z]部分",
        s2,
    ):
        return True
    # also drop short queries that don't contain a street/building anchor
    # count "meaningful" chars (Chinese + alnum, ignoring spaces)
    meaningful = re.sub(r"\s+", "", s2)
    # require either a Chinese street-tail suffix (道/街/里/徑/路), a known
    # building suffix, a digit door number, or >=4 chars of substance.
    has_street_tail = bool(re.search(r"[一-鿿]{1,8}(?:道|街|里|徑|路)", s2))
    has_building_tail = bool(
        re.search(
            r"(?:大廈|大樓|中心|廣場|城|坊|閣|苑|邨|匯|滙|薈|軒|臺|台|酒店|花園|新邨|新苑|商場|期)",
            s2,
        )
    )
    has_door_num = bool(re.search(r"\d+號", s2))
    has_mall_token = bool(re.search(r"[A-Z]{2,}", s2))  # e.g. D2 PLACE, SILICONLANE
    if not (has_street_tail or has_building_tail or has_door_num or has_mall_token):
        if len(meaningful) < 4:
            return True
    return False


def fetch_candidates(
    addr: str,
    cache: dict,
) -> tuple[list, list[tuple[str, str]]]:
    """Return (candidate_pool, queries_issued).

    candidate_pool: union of CSDI results for the original address + the
    re-engineered query ladder.  Each candidate is tagged with `__q__` and
    `__label__` so we can attribute the winning hit back to its query.

    queries_issued: list of (label, q) for cache bookkeeping (only includes
    ones not already cached).
    """
    queries, _ = build_queries(addr)
    issued: list[tuple[str, str]] = []
    pool: list = []
    seen: set = set()  # dedupe by (nameZH, addressZH, x, y)
    # 1. always include original-address cache if available (already cached,
    #    so no API hit)
    original = addr.strip()
    if original in cache and not _is_garbage_query(original, AREAS):
        for h in cache[original]:
            key = (h.get("nameZH"), h.get("addressZH"), h.get("x"), h.get("y"))
            if key not in seen:
                seen.add(key)
                tagged = dict(h)
                tagged["__q__"] = original
                tagged["__label__"] = "original"
                pool.append(tagged)
    # 2. run ladder queries (cache hit short-circuits sleep).
    #    Skip garbage queries entirely — they pollute the candidate pool
    #    with out-of-area hits (e.g. id 66 '九龍長沙灣長義街9號 D2 PLACEONE
    #    3樓306鋪' would otherwise surface a Tuen Mun gym '3樓' hit).
    for label, q in queries:
        if not q or not q.strip():
            continue
        if _is_garbage_query(q, AREAS):
            continue
        before = len(cache)
        results = fetch_with_sleep(q, cache)
        if before != len(cache):
            issued.append((label, q))
        for h in results or []:
            key = (h.get("nameZH"), h.get("addressZH"), h.get("x"), h.get("y"))
            if key not in seen:
                seen.add(key)
                tagged = dict(h)
                tagged["__q__"] = q
                tagged["__label__"] = label
                pool.append(tagged)
    return pool, issued


def geocode_one(record: dict, cache: dict, fallback: dict) -> dict:
    """Geocode a single restaurant record. Returns the new coord row."""
    addr = (record.get("address") or "").strip()
    rid = record["id"]
    district = record.get("district") or ""
    csdi_district_expected = csdi_district_for(district)

    queries, parts = build_queries(addr)
    candidate_pool, _issued = fetch_candidates(addr, cache)

    best_hit, best_score, best_alt, best_prec, best_bd = pick_best(
        candidate_pool,
        parts["street"],
        parts["num"],
        parts["building"],
        parts["sub"],
        csdi_district_expected,
    )

    best_q = best_hit.get("__q__") if best_hit else None

    if best_hit and "x" in best_hit and "y" in best_hit:
        lat, lng = to_wgs84(float(best_hit["x"]), float(best_hit["y"]))
        return {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "prec": best_prec,
            "src": "csdi",
            "q": best_q,
            "score": round(best_score, 1),
            "alt": best_alt,
            "parts": parts,
        }

    # fallback: use area centre of detected sub (or rough-bak row)
    sub = parts.get("sub")
    if sub and sub in AREAS and AREAS[sub].get("lat") is not None:
        return {
            "lat": AREAS[sub]["lat"],
            "lng": AREAS[sub]["lng"],
            "prec": "area",
            "src": "fallback",
            "q": None,
            "score": None,
            "alt": best_alt,
            "parts": parts,
        }

    # last-ditch: rough-bak fallback (kept for any record that previously had coords)
    fb = fallback.get(str(rid)) or fallback.get(rid)
    if isinstance(fb, dict) and "lat" in fb and "lng" in fb:
        return {
            "lat": fb["lat"],
            "lng": fb["lng"],
            "prec": "area",
            "src": "fallback",
            "q": None,
            "score": None,
            "alt": best_alt,
            "parts": parts,
        }

    return {
        "lat": None,
        "lng": None,
        "prec": None,
        "src": "missing",
        "q": None,
        "score": None,
        "alt": best_alt,
        "parts": parts,
    }


# ---------- area centres (still needed on first run) ----------
AREAS_RAW = """馬鞍山 科學園 白石角 香港仔 黃竹坑 海洋公園 淺水灣 赤柱 薄扶林 數碼港 鴨脷洲 中環 上環 西營盤 堅尼地城 石塘咀 半山 山頂 金鐘 銅鑼灣 跑馬地 大坑 天后 北角 鰂魚涌 太古 西灣河 筲箕灣 柴灣 尖沙咀 尖東 佐敦 油麻地 旺角 太子 大角咀 長沙灣 荔枝角 美孚 土瓜灣 紅磡 何文田 啟德 九龍灣 觀塘 牛頭角 藍田 油塘 深井 馬灣 荃灣 屯門 黃金海岸 元朗 天水圍 錦田 上水 粉嶺 大埔 沙田 大圍 火炭 西貢 將軍澳 坑口 寶琳 調景嶺 康城 清水灣 葵涌 葵芳 青衣 東涌 愉景灣 迪士尼 機場 大澳 長洲 南丫島 坪洲 奧運 西九龍 旺角東 太古"""


def geocode_area(name: str, cache: dict) -> tuple[dict | None, str]:
    """Geocode a single area name. Tries name, then name+'站', then name+'香港'."""
    attempts = [name, f"{name}站", f"{name}香港"]
    for q in attempts:
        res = fetch_with_sleep(q, cache)
        # area centres use simple bbox + first hit preference
        pool = []
        for r in res or []:
            if "x" not in r or "y" not in r:
                continue
            try:
                x = float(r["x"])
                y = float(r["y"])
                lat, lng = to_wgs84(x, y)
            except (ValueError, TypeError):
                continue
            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                continue
            pool.append((lat, lng, r))
        if pool:
            # prefer hit whose nameZH exactly equals the area name
            for lat, lng, r in pool:
                if (r.get("nameZH") or "").strip() == name:
                    return ({"lat": round(lat, 6), "lng": round(lng, 6), "prec": "csdi"}, q)
            lat, lng, _ = pool[0]
            return ({"lat": round(lat, 6), "lng": round(lng, 6), "prec": "csdi"}, q)
    return (None, "")


# ---------- main ----------
def main():
    t0 = time.time()
    restaurants = json.loads(RESTAURANTS_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(restaurants)} restaurants", flush=True)

    # Backup existing coords before overwriting (only first time)
    if COORDS_OUT.exists():
        bak = COORDS_OUT.with_name("restaurant-coords.rough.bak.json")
        if not bak.exists():
            bak.write_bytes(COORDS_OUT.read_bytes())
            print(f"Backed up rough coords -> {bak.name}", flush=True)
        fallback_raw = json.loads(COORDS_OUT.read_text(encoding="utf-8"))
    else:
        fallback_raw = {}

    cache = load_cache()
    print(f"Cache: {len(cache)} prior queries", flush=True)

    coords: dict[str, dict] = {}
    no_coord: list[int] = []
    prec_counts = {"building": 0, "street": 0, "area": 0, "missing": 0, "other": 0}
    src_counts: dict[str, int] = {}
    api_calls = {"n": 0}
    api_lock = threading.Lock()

    # Reload AREAS in case file just got written
    global AREAS, AREA_KEYS_SORTED
    AREAS = load_area_centres()
    AREA_KEYS_SORTED = sorted(AREAS.keys(), key=lambda s: (-len(s), s))

    cache_size_before_run = len(cache)
    print(f"Cache before run: {cache_size_before_run} queries", flush=True)

    done = {"n": 0}
    done_lock = threading.Lock()

    def work(r: dict) -> None:
        out = geocode_one(r, cache, fallback_raw)
        with done_lock:
            coords[str(r["id"])] = out
            if out["lat"] is None or out["lng"] is None:
                no_coord.append(r["id"])
                prec_counts["missing"] += 1
            else:
                p = out.get("prec") or "other"
                prec_counts[p] = prec_counts.get(p, 0) + 1
                s = out.get("src") or "other"
                src_counts[s] = src_counts.get(s, 0) + 1
            done["n"] += 1
            if done["n"] % 25 == 0 or done["n"] == len(restaurants):
                print(
                    f"[{done['n']}/{len(restaurants)}] done", flush=True
                )
                COORDS_OUT.write_text(
                    json.dumps(coords, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, restaurants))

    # Final write
    COORDS_OUT.write_text(
        json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ----- area centres (only if missing entries) -----
    print("--- geocoding area centres (if missing) ---", flush=True)
    area_names = list(dict.fromkeys(AREAS_RAW.split()))
    areas: dict[str, dict] = dict(AREAS)  # start from existing
    area_fail = []
    for i, nm in enumerate(area_names, 1):
        if nm in areas and areas[nm].get("lat") is not None:
            continue
        out, _q = geocode_area(nm, cache)
        if out:
            areas[nm] = out
        else:
            areas.setdefault(nm, {"lat": None, "lng": None, "prec": None})
            area_fail.append(nm)

    AREA_OUT.write_text(
        json.dumps(areas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_cache(cache, force=True)

    # ----- summary -----
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total restaurants:  {len(restaurants)}")
    print(f"Coords emitted:     {sum(1 for v in coords.values() if v.get('lat') is not None)}")
    print(f"Missing coords:     {len(no_coord)}")
    print(f"prec distribution:  {prec_counts}")
    print(f"src  distribution:  {src_counts}")
    print(f"Cache size before:  {cache_size_before_run}")
    print(f"Cache size after:   {len(cache)}")
    print(f"NEW API calls:      {len(cache) - cache_size_before_run}")
    print(f"Area names:         {len(area_names)}  fail={area_fail}")
    print(f"Wall-clock:         {time.time() - t0:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()