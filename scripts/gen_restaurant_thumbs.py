#!/usr/bin/env python3
"""gen_restaurant_thumbs.py — static map thumbnails (card faces) for restaurants.

Renders the SAME keyless basemap the live site uses (OpenFreeMap "positron"
vector style, MapLibre GL) in headless Chromium, then screenshots the map.

Why map thumbnails and not photos: the restaurant DB has 942 FEHD-licensed
premises and no licensed photo source; Google Places ToS forbids storing /
indexing their content in our own database, so a baked photo is not allowed.
A map thumbnail is generated purely from our own lat/lng and is ToS-clean
(OpenFreeMap: no key, no quota, commercial use allowed).

Output : public/thumbs/<id>.jpg   800x533 (3:2), warm-treated to match v3.
Usage  : python3 scripts/gen_restaurant_thumbs.py [--ids 1,62,1095] [--limit N]
         [--force] [--out DIR] [--concurrency 1]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
COORDS = ROOT / "src/data/restaurant-coords.json"
REST = ROOT / "src/data/restaurants.json"
OUT_DEFAULT = ROOT / "public/thumbs"

W, H = 800, 533
STYLE_URL = "https://tiles.openfreemap.org/styles/positron"

HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body{margin:0;padding:0;background:#F4EEDF}
  #map{width:%(w)dpx;height:%(h)dpx;filter:sepia(.18) saturate(.95) brightness(1.02) contrast(.98)}
  .pin{width:22px;height:22px;border-radius:50%%;background:#C03818;border:3px solid #1B1814;
       box-shadow:0 0 0 5px rgba(255,253,247,.92)}
  .credit{position:absolute;right:4px;bottom:3px;font:10px/1.2 -apple-system,'Noto Sans HK',sans-serif;
       color:#4A433A;background:rgba(255,253,247,.86);padding:1px 5px;border-radius:2px;
       border:1px solid rgba(27,24,20,.35);z-index:5}
</style></head><body>
<div id="map"></div><div class="credit">© OpenStreetMap</div>
<script>
  var map = new maplibregl.Map({container:'map', style:'%(style)s',
      center:[114.15,22.30], zoom:15, attributionControl:false,
      interactive:false, fadeDuration:0});
  window.__ready = false;
  map.on('load', function(){
    var el = document.createElement('div'); el.className = 'pin';
    window.__marker = new maplibregl.Marker({element: el, anchor:'center'}).setLngLat([114.15,22.30]).addTo(map);
    window.__ready = true;
  });
  window.renderThumb = function(lat, lng, zoom){
    window.__marker.setLngLat([lng, lat]);
    map.jumpTo({center:[lng, lat], zoom: zoom});
    return new Promise(function(res){
      if (map.loaded() && map.areTilesLoaded()) { requestAnimationFrame(function(){ res(true); }); return; }
      var done = false;
      function fin(){ if(done) return; done = true; map.off('idle', fin); setTimeout(function(){res(true);}, 120); }
      map.on('idle', fin);
      setTimeout(fin, 8000);
    });
  };
</script></body></html>""" % {"w": W, "h": H, "style": STYLE_URL}


def load_records():
    coords = json.loads(COORDS.read_text())
    recs = json.loads(REST.read_text())
    out = []
    for r in recs:
        c = coords.get(str(r["id"]))
        if not c or c.get("lat") is None:
            continue
        out.append({
            "id": r["id"],
            "name": r.get("name_zh") or r.get("name_en") or "",
            "district": r.get("district", ""),
            "lat": c["lat"], "lng": c["lng"],
            "prec": c.get("prec", ""),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--scale", type=float, default=1.0, help="deviceScaleFactor")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    recs = load_records()
    if args.ids:
        want = {int(x) for x in args.ids.split(",") if x.strip()}
        recs = [r for r in recs if r["id"] in want]
    if not args.force:
        recs = [r for r in recs if not (outdir / f"{r['id']}.jpg").exists()]
    if args.limit:
        recs = recs[: args.limit]
    if not recs:
        print("nothing to do"); return 0
    print(f"rendering {len(recs)} thumbnails -> {outdir}")

    from playwright.sync_api import sync_playwright
    t0 = time.time()
    done = 0
    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader",
                                           "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width": W, "height": H},
                                  device_scale_factor=args.scale)
        page = ctx.new_page()
        page.set_content(HTML, wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=60000)
        el = page.query_selector("#map")
        for i, r in enumerate(recs, 1):
            zoom = 17 if r["prec"] == "building" else 15.6
            try:
                page.evaluate("([a,b,c]) => window.renderThumb(a,b,c)", [r["lat"], r["lng"], zoom])
                el.screenshot(path=str(outdir / f"{r['id']}.jpg"), type="jpeg", quality=80)
                done += 1
            except Exception as e:
                fails.append((r["id"], str(e)[:80]))
            if i % 25 == 0 or i == len(recs):
                el_s = time.time() - t0
                print(f"  {i}/{len(recs)}  ({el_s:.0f}s, {el_s/max(i,1):.2f}s each)", flush=True)
        browser.close()
    print(f"done: {done} ok, {len(fails)} failed, {time.time()-t0:.0f}s")
    for fid, err in fails[:10]:
        print("  FAIL", fid, err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
