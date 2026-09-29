#!/usr/bin/env python3
"""mark_approx.py — 誠實標示：座標仍然「擺正區中心」嘅餐廳，prec 改為 'area'。

點解要做：網站 UI 對 prec=='area' 會顯示「位置約略」而唔係一個假距離。
之前有 70 間查到唔到可信座標，粒點仍然係地區中心座標（同中心點差距 < 25 m），
如果照樣當「精確」顯示，用戶放大後就會覺得撳錯位（Sunny 2026-09-29 指出嘅問題）。

只改 prec != 'building' 而且**粒點同最近地區中心相距 < 25 m** 嘅 rows。自動備份。
用法： ~/.hermes-venv/bin/python3 scripts/mark_approx.py [--dry-run]
"""
import argparse
import json
import math
import shutil
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COORDS = REPO / "src" / "data" / "restaurant-coords.json"
AREA = REPO / "src" / "data" / "area-centres.json"
RESTS = REPO / "src" / "data" / "restaurants.json"
TOL_M = 25.0


def hav(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    coords = json.loads(COORDS.read_text(encoding="utf-8"))
    areas = json.loads(AREA.read_text(encoding="utf-8"))
    rests = {str(r["id"]): r for r in json.loads(RESTS.read_text(encoding="utf-8"))}
    centres = [(v["lat"], v["lng"]) for v in areas.values() if v.get("lat") and v.get("lng")]

    hits = []
    for k, v in coords.items():
        if v.get("prec") == "building" or not isinstance(v.get("lat"), (int, float)):
            continue
        d = min(hav((v["lat"], v["lng"]), c) for c in centres)
        if d < TOL_M:
            hits.append((k, v.get("prec"), d))

    print(f"仍然擺正地區中心（<{TOL_M:.0f} m）而唔係 building 級: {len(hits)}")
    for k, p, d in hits[:12]:
        print(f"  id{k:<5} prec={p:<7} {d:5.1f} m  {rests.get(k, {}).get('name_zh', '')[:14]} {rests.get(k, {}).get('address', '')[:36]}")
    if args.dry_run or not hits:
        return
    bak = COORDS.with_suffix(f".json.bak-approx-{date.today().isoformat()}")
    if not bak.exists():
        shutil.copy2(COORDS, bak)
    for k, _, _ in hits:
        coords[k]["prec"] = "area"
    COORDS.write_text(json.dumps(coords, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter
    print(f"已改 {len(hits)} 行 prec → area（備份 {bak.name}）")
    print("prec 分佈:", Counter(v.get("prec") for v in coords.values()).most_common())


if __name__ == "__main__":
    main()
