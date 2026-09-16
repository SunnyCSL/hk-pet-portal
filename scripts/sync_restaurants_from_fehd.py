#!/usr/bin/env python3
"""sync_restaurants_from_fehd.py — 由食環署官方 JSON 全面同步餐廳名單。

Source (authoritative, structured):
    https://www.fehd.gov.hk/english/licensing/dog_restaurants/getData.php
    → JSON array, 每次名單更新即變, 內含 licence / shop_sign_en|tc|sc /
      address_en|tc|sc / district_en|tc|sc / house_rule
    (取代舊做法: 由 fulllist.pdf 用 pdftotext 抽，column flatten 好易錯)

Output: src/data/restaurants.json

規則:
  * licence_no 相同      → 保留原 id (保住 /restaurants/<id> URL 同 SEO)
  * 名單新增餐廳          → 新 id (現有 max id + 1 起, 順序遞增)
  * 網站有但名單已冇      → 刪除 (已退出計劃 / 被剔除)
  * 手動條目 (license_no 空) → 一律原封不動保留 (唔可以用名單驗證)

用法:
    python3 scripts/sync_restaurants_from_fehd.py            # 寫檔
    python3 scripts/sync_restaurants_from_fehd.py --dry-run  # 只報數
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "data" / "restaurants.json"
STATS = REPO / "src" / "data" / "restaurant-stats.json"
SRC_URL = "https://www.fehd.gov.hk/english/licensing/dog_restaurants/getData.php"

# FEHD 店號有時係「冇記錄」placeholder — 唔好用嚟蓋過現有店名
PLACEHOLDER = ("(no record found)", "(沒有記錄)", "(没有记录)", "沒有記錄", "没有记录")


def fetch_list() -> list[dict]:
    raw = subprocess.run(
        ["curl", "-s", SRC_URL], capture_output=True, timeout=90
    ).stdout
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list) or len(data) < 500:
        raise SystemExit(f"FEHD list looks wrong: {type(data)} len={len(data) if data else 0}")
    return data


def good_name(*cands) -> str:
    """First non-empty, non-placeholder candidate (None-safe)."""
    for c in cands:
        if c and str(c).strip() and str(c).strip().lower() not in PLACEHOLDER:
            return str(c).strip()
    for c in cands:
        if c:
            return str(c).strip()
    return ""


def addr_key(addr: str, n: int = 12) -> str:
    """Coarse address key — same building/complex => same key."""
    return re.sub(r"\s+", "", addr or "")[:n]


def sibling_names(fehd: list[dict]) -> dict[str, str]:
    """address_key -> a usable shop name, for records whose own sign is
    '(no record found)' (FEHD sometimes has a blank sign for e.g. club/camp
    premises that share an address with a named record)."""
    out: dict[str, str] = {}
    for rec in fehd:
        nm = good_name(rec.get("shop_sign_tc"), rec.get("shop_sign_sc"), rec.get("shop_sign_en"))
        if nm and nm.lower() not in PLACEHOLDER:
            out.setdefault(addr_key(rec.get("address_tc") or ""), nm)
    return out


def main() -> None:
    dry = "--dry-run" in sys.argv
    fehd = fetch_list()
    print(f"FEHD list: {len(fehd)} approved restaurants (fetched live)")
    siblings = sibling_names(fehd)

    site = json.loads(OUT.read_text(encoding="utf-8"))
    print(f"Site data: {len(site)} rows → {OUT.relative_to(REPO)}")

    by_lic: dict[str, dict] = {}
    manual: list[dict] = []
    dupes: list[dict] = []
    for r in site:
        lic = (r.get("license_no") or "").strip()
        if not lic:
            manual.append(r)
            continue
        if lic in by_lic:
            dupes.append(r)
            continue
        by_lic[lic] = r

    next_id = max([r["id"] for r in site] + [0]) + 1
    out: list[dict] = []
    added, renamed, readdr, kept = [], [], [], 0

    for rec in fehd:
        lic = (rec.get("licence") or "").strip()
        name_zh = good_name(rec.get("shop_sign_tc"), rec.get("shop_sign_sc"), rec.get("shop_sign_en"))
        name_en = good_name(rec.get("shop_sign_en"), rec.get("shop_sign_tc"))
        if name_zh.lower() in PLACEHOLDER:  # FEHD blank sign → borrow sibling name
            sib = siblings.get(addr_key(rec.get("address_tc") or ""))
            if sib:
                name_zh = name_en = sib
        row = {
            "name_en": name_en,
            "name_zh": name_zh,
            "district": (rec.get("district_tc") or "").strip(),
            "address": (rec.get("address_tc") or "").strip(),
            "license_no": lic,
        }
        old = by_lic.pop(lic, None)
        if old is None:
            row["id"] = next_id
            next_id += 1
            out.append(row)
            added.append((row["id"], name_zh))
            continue
        row["id"] = old["id"]
        if (old.get("name_zh") or "") != name_zh or (old.get("name_en") or "") != name_en:
            renamed.append((old["id"], old.get("name_zh"), name_zh))
        if (old.get("address") or "") != row["address"]:
            readdr.append((old["id"], name_zh))
        out.append(row)
        kept += 1

    removed = [(r["id"], r.get("name_zh")) for r in by_lic.values()]

    out.sort(key=lambda r: r["id"])
    # 手動條目 (冇牌照) — 如果官方名單而家有同名同區記錄 (即已正式入名單 + 有完整地址),
    # 就刪走手動 placeholder, 免搜尋出現重複。
    official_names = {(r["name_zh"], r["district"]) for r in out}
    kept_manual = [m for m in manual if (m.get("name_zh"), m.get("district")) not in official_names]
    superseded = [m for m in manual if m not in kept_manual]
    out.extend(kept_manual)
    out.sort(key=lambda r: r["id"])
    if superseded:
        print("  superseded manual rows dropped:",
              [(m["id"], m["name_zh"]) for m in superseded])

    print(f"  kept (licence match) : {kept}")
    print(f"  added                : {len(added)}")
    print(f"  removed (off list)   : {len(removed)}")
    print(f"  renamed              : {len(renamed)}")
    print(f"  address refreshed    : {len(readdr)}")
    print(f"  manual rows kept     : {len(manual)}")
    if dupes:
        print(f"  ⚠ duplicate licences dropped: {[(d['id'], d.get('license_no')) for d in dupes]}")
    if added:
        print("  --- new (sample) ---")
        for i, n in added[:15]:
            print(f"    + id {i}: {n}")
    if removed:
        print("  --- delisted ---")
        for i, n in removed:
            print(f"    - id {i}: {n}")

    if dry:
        print("\nDRY RUN — nothing written")
        return

    OUT.with_name("restaurants.json.bak-sync").write_text(
        json.dumps(site, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    districts = sorted({r["district"] for r in out if r.get("district")})
    STATS.write_text(
        json.dumps(
            {
                "total": len(out),
                "districts": len(districts),
                "updated": __import__("datetime").date.today().isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {len(out)} rows → {OUT.relative_to(REPO)}")
    print(f"Wrote stats → {STATS.relative_to(REPO)}")
    print("Next: scripts/geocode_restaurants.py then scripts/build_restaurant_types.py")


if __name__ == "__main__":
    main()
