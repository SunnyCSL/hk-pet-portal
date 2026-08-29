#!/usr/bin/env python3
"""
Generate OG image for HK Pet Portal — 1200x630 PNG, brand green gradient
background with title + paw glyph. Used as og:image / twitter:image default.

Run:  python3 scripts/gen_og_image.py
Out:  public/og-image.png
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "public" / "og-image.png"
WIDTH, HEIGHT = 1200, 630
BRAND_GREEN_TOP = (45, 155, 78)    # #2D9B4E
BRAND_GREEN_BOT = (29, 110, 56)    # #1D6E38 (darker shade)


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Try macOS system fonts first, fall back to Pillow defaults."""
    candidates = [
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    # Pillow fallback (DejaVu ships in Pillow's wheels)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _vertical_gradient(size: tuple[int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (w, h), BRAND_GREEN_TOP)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        t = y / (h - 1)
        r = int(BRAND_GREEN_TOP[0] * (1 - t) + BRAND_GREEN_BOT[0] * t)
        g = int(BRAND_GREEN_TOP[1] * (1 - t) + BRAND_GREEN_BOT[1] * t)
        b = int(BRAND_GREEN_TOP[2] * (1 - t) + BRAND_GREEN_BOT[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return base


def _draw_paw(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, fill: tuple[int, int, int]) -> None:
    """Draw a simple paw print: pad + 4 toes. Vector only, no external assets."""
    # Main pad (oval)
    pad_w, pad_h = int(120 * scale), int(95 * scale)
    draw.ellipse(
        [cx - pad_w / 2, cy - pad_h / 2, cx + pad_w / 2, cy + pad_h / 2],
        fill=fill,
    )
    # 4 toes (smaller ellipses arranged above)
    toe_w, toe_h = int(45 * scale), int(58 * scale)
    positions = [
        (cx - int(80 * scale), cy - int(95 * scale)),  # outer left
        (cx - int(28 * scale), cy - int(120 * scale)),  # inner left
        (cx + int(28 * scale), cy - int(120 * scale)),  # inner right
        (cx + int(80 * scale), cy - int(95 * scale)),   # outer right
    ]
    for tx, ty in positions:
        draw.ellipse(
            [tx - toe_w / 2, ty - toe_h / 2, tx + toe_w / 2, ty + toe_h / 2],
            fill=fill,
        )


def render() -> Path:
    img = _vertical_gradient((WIDTH, HEIGHT))

    # soft radial glow centered top-right (PIL-only via translucent ellipses)
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(280, 60, -20):
        alpha = int(28 * (1 - (r - 60) / 220))
        gd.ellipse(
            [WIDTH - r * 1.6, -r * 0.6, WIDTH + r * 0.4, r * 1.4],
            fill=(255, 255, 255, max(0, alpha)),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=40))
    img.paste(glow, (0, 0), glow)

    draw = ImageDraw.Draw(img)

    # Decorative paw (background accent, semi-transparent)
    paw_overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pd = ImageDraw.Draw(paw_overlay)
    pd.ellipse([0, 0, 0, 0])  # noop for typing
    _draw_paw(pd, cx=int(WIDTH * 0.82), cy=int(HEIGHT * 0.5), scale=2.4, fill=(255, 255, 255, 38))
    img.paste(paw_overlay, (0, 0), paw_overlay)

    # Foreground paw (solid white, smaller)
    _draw_paw(draw, cx=160, cy=int(HEIGHT * 0.78), scale=0.9, fill=(255, 255, 255))

    # Title text (rendered as two lines to keep wide)
    title_font = _load_font(96, bold=True)
    sub_font = _load_font(36, bold=False)

    title = "HK Pet Portal"
    # centered horizontally, but slightly left-aligned with the paw on the right
    title_x = 220
    title_y = 230
    # subtle text shadow for legibility on green
    shadow_offset = 4
    draw.text((title_x + shadow_offset, title_y + shadow_offset), title, font=title_font, fill=(0, 60, 20))
    draw.text((title_x, title_y), title, font=title_font, fill=(255, 255, 255))

    tagline_zh = "香港寵物友善資訊平台"
    tagline_en = "Pet-friendly Hong Kong · Dog Restaurants · Pet Health"
    tz_y = title_y + 130
    draw.text((title_x + 2, tz_y + 2), tagline_zh, font=sub_font, fill=(0, 60, 20))
    draw.text((title_x, tz_y), tagline_zh, font=sub_font, fill=(240, 255, 245))
    te_y = tz_y + 50
    draw.text((title_x + 2, te_y + 2), tagline_en, font=sub_font, fill=(0, 60, 20))
    draw.text((title_x, te_y), tagline_en, font=sub_font, fill=(255, 255, 255))

    # bottom-right brand badge
    badge_font = _load_font(22, bold=True)
    draw.text((WIDTH - 250, HEIGHT - 60), "🐾  hkpetportal", font=badge_font, fill=(255, 255, 255))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # downscale to keep file size sensible while staying sharp at preview sizes
    target = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    target.save(OUT_PATH, format="PNG", optimize=True)
    return OUT_PATH


def main() -> int:
    out = render()
    size_kb = out.stat().st_size / 1024
    print(f"✓ wrote {out} ({size_kb:.1f} KB, {WIDTH}x{HEIGHT} PNG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
