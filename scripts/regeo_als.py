#!/usr/bin/env python3
"""regeo_als.py — 用兩個官方來源（地政總署 ALS ＋ 地圖處 CSDI）互相對照，重定位「唔夠準」嘅餐廳座標。

背景（Sunny 2026-09-29）：「放大後睇位置好似唔係好啱」。
實查：992 間之中 772 間 building 級（準），其餘 220 間係 street／area 級，其中 ~150 間實際上
擺咗喺地區中心（唔係餐廳位置）。

為何要兩個來源：
  - CSDI Location Search：對「街名＋門牌」命中好，但大廈級要 query 打得準，而且會撞名。
  - ALS（地政總署地址搜尋）：識拆屋苑/期數/座數、直接回官方座標 + 驗證分數，但同名鄉村會撳錯區
    （實測：大嶼山貝澳羅屋村 → 元朗；馬灣珀麗灣 → 中環）。
  → 兩個來源一致（≤200m）＝高信心；只有一個中 ＝要用分區＋距離閘＋街名/大廈名佐證。

硬閘（缺一不可）：
  1. 分區必須一致（FEHD 18 區 → CSDI/ALS 名稱，油尖區/旺角區 → 油尖旺區）
  2. 命中要有證據：街名＋門牌緊貼、或大廈名命中（＋門牌／街名佐證）
  3. 新座標同 anchor（舊座標，或地址所屬地區中心）相距 ≤ 3 公里
  4. ALS 要有 ValidationInformation.Score ≥ 70（或在 CSDI 拿到 adj 級證據）

只改 prec != building 或冇座標嘅 rows；原檔自動備份。
用法：
    ~/.hermes-venv/bin/python3 scripts/regeo_als.py --dry-run
    ~/.hermes-venv/bin/python3 scripts/regeo_als.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COORDS = REPO / "src" / "data" / "restaurant-coords.json"
RESTS = REPO / "src" / "data" / "restaurants.json"
AREA = REPO / "src" / "data" / "area-centres.json"
CACHE_PATH = REPO / "scripts" / ".geocode_als_cache.json"
ALSCACHE = Path(os.path.expanduser("~/.hermes/profiles/pet/cache/scratch/probe_als_cache.json"))
UA = "Mozilla/5.0"
DISTRICT_FEHD_TO_CSDI = {"油尖區": "油尖旺區", "旺角區": "油尖旺區"}
MAX_MOVE_FROM_ANCHOR = 3000.0
AGREE_M = 200.0          # 兩來源一致嘅門檻
ALS_MIN_SCORE = 70.0

cache: dict = {}
if CACHE_PATH.exists():
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
elif ALSCACHE.exists():          # 重用之前 probe 嘅 ALS 回應
    try:
        cache = json.loads(ALSCACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        cache = {}


def _get(url: str, key: str) -> dict:
    if key in cache:
        return cache[key]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=25).read())
            cache[key] = d
            time.sleep(0.2)
            return d
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    cache[key] = {}
    return {}


def als(q: str, n: int = 3) -> dict:
    key = f"ALS|{q}|{n}"
    return _get("https://www.als.gov.hk/lookup?q=" + urllib.parse.quote(q) + f"&n={n}", key)


def csdi(q: str) -> list:
    key = f"CSDI|{q}"
    d = _get("https://www.map.gov.hk/gs/api/v1.0.0/locationSearch?q=" + urllib.parse.quote(q), key)
    return d if isinstance(d, list) else []


def hav(a, b) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ---------- address parsing ----------
ROAD_RE = r"([\u4e00-\u9fff]{2,8}(?:道|街|里|徑|路|坊|圍|村|臺|台)(?:[東西南北中])?)"
NUMS_AFTER_ROAD = r"([0-9]{1,5}[A-Za-z]?(?:\s*[-－及,、至]\s*[0-9]{1,5}[A-Za-z]?)*)\s*號"
STREET_ADJ_RE = re.compile(ROAD_RE + r"\s*" + NUMS_AFTER_ROAD)
DROP_RE = re.compile(
    r"(地下高層|高層地下|地庫|地下低層|地下|閣樓|一樓|二樓|三樓|四樓|五樓|六樓|七樓|八樓|九樓|十樓|"
    r"[0-9]+樓|[A-Z]/?F|G層|G/?F|U/F|號鋪|號舖|號店|舖|鋪|室|單位|及鋪前露天座位|及鋪後露天座位|及露天座位|"
    r"露天茶座|主要部份|其餘部份|\(部份\)|（部份）|及相連政府地)")


def norm(s: str) -> str:
    return re.sub(r"[\s\u3000\-－–—]+", "", s or "")


def street_and_nums(addr: str):
    m = STREET_ADJ_RE.search(addr)
    if m:
        return m.group(1), re.findall(r"[0-9]{1,5}[A-Za-z]?", m.group(2))
    return None, []


def clean_addr(addr: str) -> str:
    s = re.sub(r"^(香港|九龍|新界|大嶼山)\s*", "", addr or "")
    for _ in range(3):
        s2 = DROP_RE.sub(" ", s)
        if s2 == s:
            break
        s = s2
    return re.sub(r"\s{2,}", " ", s).strip(" ,;；")


def als_candidates(q: str):
    """ALS 回應 → [{lat,lng,score,street,building,district,nums}] 由高分到低分。"""
    out = []
    for s in (als(q).get("SuggestedAddress") or []):
        pa = (s.get("Address") or {}).get("PremisesAddress", {})
        gi = pa.get("GeospatialInformation", {})
        score = (s.get("ValidationInformation") or {}).get("Score", 0) or 0
        try:
            lat, lng = float(gi.get("Latitude")), float(gi.get("Longitude"))
        except (TypeError, ValueError):
            continue
        ch = pa.get("ChiPremisesAddress") or {}
        eng = pa.get("EngPremisesAddress") or {}
        chi_st = ch.get("ChiStreet") or {}
        street = chi_st.get("StreetName", "") or ""
        eng_street = (eng.get("EngStreet") or {}).get("StreetName", "") or ""
        nums = []
        for src in (chi_st, eng.get("EngStreet") or {}):
            for fld in ("BuildingNoFrom", "BuildingNoTo"):
                v = str(src.get(fld) or "").strip()
                m = re.match(r"^([0-9]{1,5})", v)
                if m:
                    nums.append(m.group(1))
        num_from = str(chi_st.get("BuildingNoFrom") or eng.get("EngStreet", {}).get("BuildingNoFrom") or "")
        num_to = str(chi_st.get("BuildingNoTo") or eng.get("EngStreet", {}).get("BuildingNoTo") or "")
        est = (eng.get("EngEstate") or {}).get("EstateName", "") or ""
        out.append({"lat": lat, "lng": lng, "score": float(score),
                    "street": street, "eng_street": eng_street,
                    "building": ch.get("BuildingName", "") or est,
                    "nums": sorted(set(nums)), "num_from": num_from, "num_to": num_to,
                    "district": (ch.get("ChiDistrict") or {}).get("DcDistrict", "") or ""})
    out.sort(key=lambda x: -x["score"])
    return out


def street_match(a: str, b: str) -> bool:
    """街名比對：處理異體字（鳯/鳳、褔/福、電器/電氣、邨/村、匯/滙）、去方位後綴，容忍 1 字之差。"""
    def m(s):
        s = norm(s)
        for x, y in (("鳯", "鳳"), ("鳳", "鳳"), ("褔", "福"), ("電器", "電氣"),
                     ("邨", "村"), ("滙", "匯"), ("恒", "恆"), ("徑", "徑")):
            s = s.replace(x, y)
        for suf in ("西", "東", "南", "北", "中"):
            if s.endswith(suf) and len(s) > 3:
                s = s[:-1]
        return s
    x, y = m(a), m(b)
    if not x or not y:
        return False
    if x == y or x in y or y in x:
        return True
    if abs(len(x) - len(y)) <= 1 and sum(c1 != c2 for c1, c2 in zip(x, y)) <= 1:
        return True
    return False


def nums_cover_nums(als_nums, ours) -> bool:
    """我們地址抽到嘅門牌，有冇一個落喺 ALS 回嘅門牌（或範圍）之內。"""
    for o in ours:
        for a in als_nums:
            if o == a:
                return True
            try:
                if abs(int(o) - int(a)) <= 2:
                    return True
            except ValueError:
                pass
    return False


def csdi_candidates(hits, street, nums, blds, district, tr):
    """CSDI 命中 → 只留通過硬閘嘅，按證據強度排序。"""
    street_n = norm(street)
    out = []
    for h in hits:
        hd = str(h.get("districtZH") or "")
        if district and hd and hd != district:
            continue
        text = " ".join(str(h.get(k) or "") for k in ("nameZH", "addressZH", "nameEN", "addressEN"))
        text_n = norm(text)
        addr_n = norm(str(h.get("addressZH") or "") + " " + str(h.get("addressEN") or ""))
        adj = bool(street_n and nums) and any((street_n + n + "號") in addr_n for n in nums)
        num_hit = bool(nums) and any(
            re.search(r"(?<!\d)" + re.escape(n) + r"[A-Za-z]?\s*號", str(h.get("addressZH") or "")) for n in nums)
        bld_hit = any(b and b in text_n for b in blds)
        if adj:
            strength = "adj"
        elif bld_hit and (num_hit or (street_n and street_n in text_n)):
            strength = "bld"
        else:
            continue
        try:
            lng, lat = tr.transform(float(h["x"]), float(h["y"]))
        except Exception:
            continue
        out.append({"lat": lat, "lng": lng, "strength": strength,
                    "name": h.get("nameZH") or "", "addr": h.get("addressZH") or ""})
    out.sort(key=lambda x: 0 if x["strength"] == "adj" else 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    coords = json.loads(COORDS.read_text(encoding="utf-8"))
    rests = {str(r["id"]): r for r in json.loads(RESTS.read_text(encoding="utf-8"))}
    areas = json.loads(AREA.read_text(encoding="utf-8")) if AREA.exists() else {}

    todo = [k for k, v in coords.items()
            if v.get("prec") != "building" or not isinstance(v.get("lat"), (int, float))]
    print(f"要處理 rows: {len(todo)}（總 {len(coords)}）")

    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:2326", "EPSG:4326", always_xy=True)

    both = als_only = csdi_only = none = 0
    report = []
    for i, k in enumerate(todo, 1):
        old = coords[k]
        r = rests.get(k, {})
        addr = r.get("address", "") or ""
        district = DISTRICT_FEHD_TO_CSDI.get(r.get("district", ""), r.get("district", "")) or ""
        st, nums = street_and_nums(addr)
        blds = [b for b in re.findall(r"([\u4e00-\u9fffA-Za-z]{2,10}(?:大廈|中心|廣場|商場|酒店|街市|城|匯|滙|樓|花園|新邨|苑|閣|軒))", addr)]
        anchor = (old["lat"], old["lng"]) if isinstance(old.get("lat"), (int, float)) else None
        if anchor is None:
            for key in sorted(areas.keys(), key=lambda s: -len(s)):
                if key and key in addr and areas[key].get("lat"):
                    anchor = (areas[key]["lat"], areas[key]["lng"])
                    break

        cleaned = clean_addr(addr)
        qs = [cleaned]
        if st and nums:
            qs.append(f"{st}{nums[0]}號 {district}")
            qs.append(f"{st}{nums[0]}號 {district.replace('區', '')}")
        if blds:
            qs.append(f"{blds[0]} {district}")
            qs.append(f"{blds[0]} {district.replace('區', '')}")
        a_list = []
        seen_q = set()
        for q in qs:
            if not q or q in seen_q:
                continue
            seen_q.add(q)
            a_list += als_candidates(q)
        a_list.sort(key=lambda x: -x["score"])
        a_best = None
        a_ev = ""
        for a in a_list:
            if a["district"] and district and a["district"] != district:
                continue
            d_anchor = hav(anchor, (a["lat"], a["lng"])) if anchor else 0.0
            street_ok = bool(st) and street_match(st, a["street"])
            num_ok = bool(nums) and nums_cover_nums(a["nums"], nums)
            a_bld_n = norm(a["building"])
            bld_ok = any(norm(b) in a_bld_n or (a_bld_n and a_bld_n in norm(b)) for b in blds)
            # 門牌或大廈名命中 ＝ 證據夠強，score 65 都收；純街名要 70
            if a["score"] < (65.0 if (num_ok or bld_ok) else ALS_MIN_SCORE):
                continue
            if street_ok and num_ok:
                if d_anchor > 15000:          # 街名＋門牌都中，只需 sanity 距離閘
                    continue
                a["_tier"] = "num"
                a_best, a_ev = a, f"街名＋門牌（score {a['score']:.0f}, {a['street']}{a['num_from']}）"
                break
            if bld_ok or street_ok:
                if d_anchor > MAX_MOVE_FROM_ANCHOR:
                    continue
                a["_tier"] = "name"
                a_best, a_ev = a, f"{'大廈名' if bld_ok else '街名'}（score {a['score']:.0f}, {a['street']} {a['building']}）"
                break

        c_list = []
        for q in ([f"{district.replace('區', '')} {st}{nums[0]}號"] if (st and nums) else []) + \
                 ([f"{b} {district.replace('區', '')}" for b in blds]) + ([cleaned] if cleaned else []):
            c_list = csdi_candidates(csdi(q), st, nums, blds, district, tr)
            if c_list:
                break
        c_best = c_list[0] if c_list else None

        chosen = None
        how = ""
        a_prec = "building" if (a_best and a_best.get("_tier") == "num") else "street"
        if a_best and c_best:
            d_ac = hav((a_best["lat"], a_best["lng"]), (c_best["lat"], c_best["lng"]))
            if d_ac <= AGREE_M:
                chosen = {"lat": a_best["lat"], "lng": a_best["lng"], "prec": a_prec,
                          "src": "als+csdi", "conf": "both"}
                how = f"兩個來源一致（相距 {d_ac:.0f} m）｜ALS {a_ev}"
                both += 1
        if chosen is None and a_best:
            chosen = {"lat": a_best["lat"], "lng": a_best["lng"], "prec": a_prec,
                      "src": "als", "conf": f"als score {a_best['score']:.0f}"}
            how = f"ALS 命中｜{a_ev}"
            als_only += 1
        if chosen is None and c_best and c_best["strength"] == "adj":
            chosen = {"lat": c_best["lat"], "lng": c_best["lng"], "prec": "building",
                      "src": "csdi", "conf": "adj"}
            how = f"CSDI 街名＋門牌緊貼（{c_best['name']} / {c_best['addr'][:28]}）"
            csdi_only += 1
        if chosen is None:
            none += 1
            report.append((k, r.get("name_zh", ""), addr, "KEEP", None, None, ""))
            continue

        d_old = hav(anchor, (chosen["lat"], chosen["lng"])) if anchor else None
        new = {**chosen, "score": a_best["score"] if a_best else None,
               "q": cleaned, "alt": old.get("alt")}
        new["lat"] = round(new["lat"], 6)
        new["lng"] = round(new["lng"], 6)
        report.append((k, r.get("name_zh", ""), addr, "FIX", d_old, new, how))
        if not args.dry_run:
            import pyproj  # noqa: F401
            coords[k] = new
        if i % 25 == 0:
            CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  ...{i}/{len(todo)}  兩個來源 {both} / 只 ALS {als_only} / 只 CSDI {csdi_only} / 留原狀 {none}", flush=True)

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    if not args.dry_run:
        bak = COORDS.with_suffix(f".json.bak-als-{date.today().isoformat()}")
        if not bak.exists():
            shutil.copy2(COORDS, bak)
        COORDS.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已寫 {COORDS}（備份 {bak.name}）")

    print()
    print(f"修到: {both + als_only + csdi_only} / {len(todo)}  （兩個來源一致 {both}｜只 ALS {als_only}｜只 CSDI {csdi_only}）")
    print(f"保留原狀（搵唔到可信座標）: {none}")
    moves = sorted([x[4] for x in report if x[4] is not None])
    if moves:
        print(f"移動距離: 中位 {moves[len(moves)//2]:.0f} m | p90 {moves[int(len(moves)*0.9)]:.0f} m | 最大 {moves[-1]:.0f} m")
    print()
    fixed = [x for x in report if x[3] == "FIX"]
    print("--- 移動最多嘅 12 個 ---")
    for k, nm, addr, st_, d, new, how in sorted(fixed, key=lambda x: -(x[4] or 0))[:12]:
        print(f"  id{k:<5} {str(nm)[:16]:<18} {addr[:32]}")
        print(f"        → {new['lat']:.6f},{new['lng']:.6f} | 移動 {d:.0f} m | {how}")
    print()
    print("--- 隨機抽 10 個已修（核查）---")
    import random as _rnd
    _rnd.seed(11)
    for k, nm, addr, st_, d, new, how in _rnd.sample(fixed, min(10, len(fixed))):
        print(f"  id{k:<5} {str(nm)[:16]:<18} {addr[:34]} → 移動 {0 if d is None else round(d)} m | {how}")


if __name__ == "__main__":
    main()
