#!/usr/bin/env python3
"""gen_cuisine_illustrations.py — 繪本風菜系插畫（餐廳卡面用）

由 FAL 直連 Nano Banana Pro（fal-ai/nano-banana-pro，$0.15/張）生成，
嚴格跟 v3「繪本牛奶盒」色票：紙米白 #F4EEDF／墨黑 #1B1814／煲呔紅 #D9432B／
奶油黃 #F6D77A／橄欖 #8A9B4A／暖褐 #8C6D4F。

輸出：public/illus/<slug>-v<n>.jpg（480×480 JPEG，卡面用）
      原檔 PNG 存 assets/illus_src/<slug>-v<n>.png（可再切／放大用）

用法：
  python3 scripts/gen_cuisine_illustrations.py --only 咖啡,茶餐廳 --variants 1
  python3 scripts/gen_cuisine_illustrations.py                # 全部類別 × variants
  python3 scripts/gen_cuisine_illustrations.py --list
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "public/illus"
SRC = ROOT / "assets/illus_src"
ENDPOINT = "https://queue.fal.run/fal-ai/nano-banana-pro"
FINAL_PX = 480

STYLE = (
    "Flat picture-book illustration, warm Hong Kong vintage storybook style. "
    "SUBJECT: {subject}. "
    "Composition: one single centred subject filling about 70% of the frame, square 1:1, "
    "a modest empty margin around it, nothing cropped or touching the edges. "
    "BACKGROUND: the ENTIRE square is flat cream paper colour #F4EEDF edge to edge — "
    "no white panel, no white inset square, no border, no frame. "
    "Style rules: hand-drawn ink outlines in dark ink, FLAT solid colour fills only, "
    "absolutely no gradients, no shading, no 3D, no photorealism, no drop shadows, no gloss. "
    "Slight risograph / letterpress print texture with subtle paper grain. "
    "Strict palette only: cream paper #F4EEDF, ink black #1B1814, tomato red #D9432B, "
    "butter yellow #F6D77A, muted olive green #8A9B4A, warm brown #8C6D4F — no blue, no grey, no purple. "
    "No text, no letters, no numbers, no words, no logo, no watermark, no frame, no border."
)

# 類別 → 主體描述（key 同 src/data/restaurant-types.json 嘅 types 對得上）
CATS = {
    "咖啡": "a steaming cup of coffee on a saucer beside a small butter croissant",
    "酒吧": "a tall beer glass with a foamy head beside a small cocktail glass with a cherry",
    "西餐": "a dinner plate with a steak, a sprig of parsley, and a fork and knife laid beside it",
    "茶餐廳": "a glass cup of Hong Kong milk tea beside a pineapple bun with a slice of butter",
    "泰越星馬": "a bowl of noodles with a chilli, a wedge of lime, lemongrass and coriander",
    "中菜": "a round plate of stir-fried greens and a small bowl of rice with chopsticks",
    "甜品／烘焙": "a slice of layered cake with a strawberry on a small plate",
    "壽司／刺身": "three pieces of nigiri sushi and a maki roll on a wooden board with chopsticks",
    "粉麵": "a bowl of noodles with chopsticks lifting a few strands",
    "海鮮": "a plate with a whole fish, two prawns and a lemon wedge",
    "串燒燒烤": "three skewers of grilled meat on a small charcoal grill",
    "中式地方菜": "a clay pot of braised food with a lid and a serving spoon",
    "日式": "a bento box with rice, a rolled omelette and a small side dish",
    "點心": "a bamboo steamer with three dumplings and a small dish of sauce",
    "拉麵／烏冬": "a bowl of ramen with a halved egg, nori and spring onion",
    "韓式": "a Korean stone pot of soup with three small side dishes",
    "港式大排檔": "a wok with stir-fried food beside a small stool",
    "印度尼泊爾": "a bowl of curry with a piece of naan bread and a spoon",
    "港式燒味": "a plate of sliced roast meat with a drizzle of sauce and rice",
    "粥品": "a bowl of congee with a spoon, a spring onion and a dough stick",
    "素食": "a bowl of fresh vegetables and salad with a fork",
    "日式燒肉": "a small tabletop grill with slices of meat and tongs",
    "法式": "a baguette, a wedge of cheese and a small glass of red wine",
    "台灣": "a cup of bubble tea with a fat straw beside a small snack",
    "__default__": "a simple round plate with chopsticks and a spoon resting on a striped placemat",
}

# 大類別加多幾個唔同主體，避免同一張插畫重複太多次
EXTRAS = {
    "咖啡": ["a tall latte glass with layers of milk beside a small spoon",
             "a coffee cup with a saucer and a small potted plant",
             "a paper cup of coffee beside a slice of banana bread",
             "a moka pot with a small espresso cup"],
    "酒吧": ["two beer glasses clinking on a wooden board",
             "a cocktail glass with a straw and a slice of orange",
             "a beer tap handle with a small glass of beer"],
    "西餐": ["a plate of pasta with a fork twirling the noodles",
             "a burger with a knife stuck in the top and a side of fries",
             "a pizza slice on a plate with a small bowl of salad"],
    "茶餐廳": ["a bowl of instant noodles with a fried egg and a slice of luncheon meat",
              "a toast with butter and condensed milk beside a cup of milk tea",
              "a plate of rice with a fried egg and a cup of hot coffee"],
    "泰越星馬": ["a bowl of pho with beef slices and herbs",
                "a plate of pad thai with a lime wedge and peanuts",
                "a bowl of laksa with a spoon and a chilli"],
}


def fal_key() -> str:
    k = os.environ.get("FAL_KEY")
    if k:
        return k
    env = pathlib.Path.home() / ".hermes/.env"
    for line in env.read_text().splitlines():
        if line.startswith("FAL_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("FAL_KEY not found")


def post(url, payload, key):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Key " + key, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": "Key " + key})
    return json.load(urllib.request.urlopen(req, timeout=90))


def gen(subject: str, key: str, tries: int = 3) -> bytes:
    payload = {"prompt": STYLE.format(subject=subject), "num_images": 1,
               "aspect_ratio": "1:1", "output_format": "png"}
    last = None
    for t in range(tries):
        try:
            r = post(ENDPOINT, payload, key)
            url = r.get("response_url") or r.get("status_url")
            for _ in range(75):
                time.sleep(4)
                try:
                    d = get(url, key)
                except Exception as e:            # 400 until ready
                    last = e
                    continue
                if d.get("images"):
                    img = d["images"][0]["url"]
                    return urllib.request.urlopen(img, timeout=180).read()
            last = RuntimeError("poll timeout")
        except Exception as e:
            last = e
        time.sleep(3)
    raise RuntimeError(f"gen failed for {subject!r}: {last}")


def subject_for(cat: str, v: int) -> str:
    """Variant 1 = 主體；之後輪流用 EXTRAS 嘅替代主體。"""
    pool = [CATS[cat]] + EXTRAS.get(cat, [])
    return pool[(v - 1) % len(pool)]


def auto_variants(count: int) -> int:
    """按該類別餐廳數目決定要幾多個變體（10 間一個，1–10 個）。"""
    import math
    return max(1, min(10, math.ceil(count / 10)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--variants", type=int, default=0, help="0 = 按餐廳數目自動")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--manifest", default=str(ROOT / "src/data/cuisine-illus.json"))
    args = ap.parse_args()

    if args.list:
        for k, v in CATS.items():
            print(f"  {k}: {v}")
        return 0

    slug = lambda s: s.replace("／", "-").replace("/", "-").replace(" ", "")
    types = json.loads((ROOT / "src/data/restaurant-types.json").read_text())
    counts: dict[str, int] = {}
    for rec in types.values():
        for t in (rec.get("types") or []):
            counts[t] = counts.get(t, 0) + 1
    keys = [k for k in args.only.split(",") if k.strip()] if args.only else [k for k in CATS if k != "__default__"]
    for k in keys:
        if k not in CATS:
            raise SystemExit(f"unknown category {k!r}; use --list")

    OUT.mkdir(parents=True, exist_ok=True)
    SRC.mkdir(parents=True, exist_ok=True)
    key = fal_key()
    todo = []
    for k in keys:
        n = args.variants or auto_variants(counts.get(k, 0))
        for v in range(1, n + 1):
            f = OUT / f"{slug(k)}-v{v}.jpg"
            if f.exists() and not args.force:
                continue
            todo.append((k, v, f))
    if not todo:
        print("nothing to do")
    else:
        print(f"generating {len(todo)} illustrations (${0.15*len(todo):.2f})")
        from PIL import Image
        import io
        t0 = time.time()
        for i, (k, v, f) in enumerate(todo, 1):
            raw = gen(subject_for(k, v), key)
            (SRC / f"{slug(k)}-v{v}.png").write_bytes(raw)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            s = min(im.size)
            im = im.crop(((im.width - s) // 2, (im.height - s) // 2,
                          (im.width + s) // 2, (im.height + s) // 2))     # centre square
            im = im.resize((FINAL_PX, FINAL_PX), Image.LANCZOS)
            im.save(f, "JPEG", quality=86, optimize=True)
            print(f"  {i}/{len(todo)}  {f.name}  {f.stat().st_size//1024}KB  ({time.time()-t0:.0f}s)", flush=True)
        print(f"done {len(todo)} in {time.time()-t0:.0f}s")

    # manifest：type → [檔名...]（按現有檔案重建，永遠同 disk 一致）
    man: dict[str, list[str]] = {}
    for k in CATS:
        if k == "__default__":
            continue
        fs = sorted(OUT.glob(f"{slug(k)}-v*.jpg"),
                    key=lambda p: int(p.stem.split("-v")[-1]))
        if fs:
            man[k] = [p.name for p in fs]
    dflt = sorted(OUT.glob("__default__-v*.jpg"))
    if dflt:
        man["__default__"] = [p.name for p in dflt]
    pathlib.Path(args.manifest).write_text(json.dumps(man, ensure_ascii=False, indent=0) + "\n")
    print(f"manifest: {args.manifest}  ({len(man)} 類, {sum(len(v) for v in man.values())} 張)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
