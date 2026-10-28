#!/usr/bin/env python3
"""驗證 hk-pet-portal 餐廳卡走位修正已上線（可重跑）。

聲明：production /restaurants 嘅資訊卡排版修正已生效 ——
      卡片標題/地址唔再被 UA 預設 margin 撐歪。

驗法：python3 scripts/verify_card_spacing_fix.py
合格輸出：MARKER_OK
"""
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = "https://hk-pet-portal.vercel.app"
RULE = "h1,h2,h3,h4,h5,h6,p,figure,blockquote,dl,dd{margin:0}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    html = get(f"{BASE}/restaurants")
    m = re.search(r'/_astro/[^"\']+\.css', html)
    if not m:
        print("FAIL[no-css] 頁面冇引用 /_astro/*.css")
        return 1
    css_url = BASE + m.group(0)
    css = get(css_url)
    rule_ok = RULE in css
    print(f"css_url={css_url}")
    print(f"reset_rule_present={rule_ok}")

    # 舊（未修）bundle 一定冇呢條 rule；bundle hash 亦應唔同
    stale = "BaseLayout.DUwAnOPi.css"
    print(f"stale_bundle_replaced={stale not in css_url}")

    head = subprocess.run(["git", "log", "-1", "--format=%h %s"], capture_output=True,
                          text=True, cwd=str(REPO)).stdout.strip()
    css_local = (REPO / "src/styles/ui-v3-book.css").read_text("utf-8")
    local_rule_ok = "h1, h2, h3, h4, h5, h6, p, figure, blockquote, dl, dd { margin: 0; }" in css_local
    log = subprocess.run(["git", "log", "--format=%h %s", "-n", "40"], capture_output=True,
                         text=True, cwd=str(REPO)).stdout
    commit_ok = "margin 重置" in log
    print(f"head_commit={head}")
    print(f"local_css_has_reset={local_rule_ok}")
    print(f"fix_commit_in_history={commit_ok}")

    if rule_ok and local_rule_ok and commit_ok and stale not in css_url:
        print("MARKER_OK")
        return 0
    print("FAIL[evidence]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
