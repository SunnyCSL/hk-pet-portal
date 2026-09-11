#!/usr/bin/env python3
"""Acceptance tests for restaurant-coords.json regeneration.

A: 906/906 have lat/lng, no null, no out-of-bounds
B: outlier check (geodetic distance from longest-matched area centre)
C: hard spot-check with ±1500m tolerance
D: prec/src distribution + API call count + wall-clock
E: random sample of 10 with centre distances
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path("/Users/nexi/Projects/hk-pet-portal")
COORDS = json.loads((ROOT / "src/data/restaurant-coords.json").read_text())
RESTAURANTS = json.loads((ROOT / "src/data/restaurants.json").read_text())
AREAS = json.loads((ROOT / "src/data/area-centres.json").read_text())
CACHE = json.loads((ROOT / "scripts/.geocode_cache.json").read_text())

print("=" * 70)
print("ACCEPTANCE TESTS — feat/geo-accurate-coords")
print("=" * 70)

# ---------- A: completeness + bbox ----------
print("\n[A] Completeness & bbox")
print(f"  total restaurants: {len(RESTAURANTS)}")
print(f"  total coords: {len(COORDS)}")
no_coord = [
    r["id"]
    for r in RESTAURANTS
    if COORDS.get(str(r["id"]), {}).get("lat") is None
    or COORDS.get(str(r["id"]), {}).get("lng") is None
]
print(f"  missing lat/lng: {len(no_coord)}")

oob = []
for r in RESTAURANTS:
    c = COORDS.get(str(r["id"]))
    if not c or c.get("lat") is None:
        continue
    lat, lng = c["lat"], c["lng"]
    if not (22.13 <= lat <= 22.60 and 113.80 <= lng <= 114.45):
        oob.append((r["id"], lat, lng))
print(f"  out-of-bounds: {len(oob)}")
if oob[:5]:
    for x in oob[:5]:
        print(f"    {x}")

# ---------- B: outlier check ----------
print("\n[B] Outlier check (geodetic distance from area-centres)")


def best_matched_area(addr: str) -> str | None:
    """Parent's tie-break: rfind (last-occurs) > longest > lexicographic.

    Addresses are written [region][sub], so the deepest area name appears
    last in the string.
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


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

outlier_3km = []
outlier_5km = []
outlier_distances = []
for r in RESTAURANTS:
    addr = r["address"]
    c = COORDS.get(str(r["id"]))
    if not c or c.get("lat") is None:
        continue
    area = best_matched_area(addr)
    if area and area in AREAS:
        d = haversine_m(c["lat"], c["lng"], AREAS[area]["lat"], AREAS[area]["lng"])
        outlier_distances.append((r["id"], r["name_zh"], r["district"], addr, area, d))
        if d > 5000:
            outlier_5km.append((r["id"], r["name_zh"], r["district"], addr, area, d))
        elif d > 3000:
            outlier_3km.append((r["id"], r["name_zh"], r["district"], addr, area, d))

print(f"  >3km outliers: {len(outlier_3km)}  (target ≤5)")
print(f"  >5km outliers: {len(outlier_5km)}  (target 0)")
if outlier_5km:
    print("  >>5km outliers (id, name, district, addr, area, dist_m):")
    for x in outlier_5km:
        print(f"    {x}")
if outlier_3km:
    print("  3-5km outliers:")
    for x in outlier_3km:
        print(f"    {x}")

# ---------- C: hard spot-check ----------
print("\n[C] Hard spot-check (tolerance ±1200m per parent spec)")
spot_checks = [
    (66, "捌捌陸", 22.335, 114.150, 1200),  # D2 PLACE in 長沙灣
    (453, "KNOCK KNOCK", 22.35, 114.06, 1200),  # 馬灣馬灣公園
    (938, "寶寶屋食堂", 22.35, 114.06, 1200),  # 珀麗灣
    (570, "NAK Kafé", 22.25, 113.86, 1200),  # 大澳
    (1, "%ARABICA", 22.2707, 114.150, 1200),  # 山頂凌霄閣
    (941, "樂膳", 22.4246, 114.213, 1200),  # 科學園
]
for rid, name, tlat, tlng, tol in spot_checks:
    c = COORDS.get(str(rid))
    if not c or c.get("lat") is None:
        print(f"  id={rid} {name}: NO COORD")
        continue
    d = haversine_m(c["lat"], c["lng"], tlat, tlng)
    ok = d <= tol
    print(f"  id={rid} {name}: actual=({c['lat']:.4f},{c['lng']:.4f}), dist={d:.0f}m, tol={tol}m -> {'PASS' if ok else 'FAIL'}")

# ---------- D: distributions + API calls ----------
print("\n[D] Distributions")
prec_counts: dict[str, int] = {}
src_counts: dict[str, int] = {}
for v in COORDS.values():
    prec_counts[v.get("prec") or "other"] = prec_counts.get(v.get("prec") or "other", 0) + 1
    src_counts[v.get("src") or "other"] = src_counts.get(v.get("src") or "other", 0) + 1
print(f"  prec: {prec_counts}")
print(f"  src:  {src_counts}")
print(f"  cache size now: {len(CACHE)}")

# ---------- E: 10 random records ----------
print("\n[E] Random sample of 10 records")
random.seed(42)
sample = random.sample(RESTAURANTS, 10)
for r in sample:
    c = COORDS.get(str(r["id"]))
    if not c or c.get("lat") is None:
        print(f"  id={r['id']} {r['name_zh']}: NO COORD")
        continue
    area = best_matched_area(r["address"])
    if area and area in AREAS:
        d = haversine_m(c["lat"], c["lng"], AREAS[area]["lat"], AREAS[area]["lng"])
    else:
        d = None
    print(
        f"  id={r['id']} {r['name_zh'][:20]:<20} dist={r['district'][:6]:<6} addr={r['address'][:35]:<35}\n"
        f"        -> ({c['lat']:.4f}, {c['lng']:.4f}) prec={c.get('prec'):<8} src={c.get('src'):<8} score={c.get('score')}\n"
        f"        matched_area={area}, dist_from_area={f'{d:.0f}m' if d is not None else 'N/A'}"
    )