#!/usr/bin/env python3
"""Mac-optimized whiteboard generator - SPLIT_LEN=4, SKIP_RATE=1"""
import argparse, os, sys, math, time, datetime, cv2, numpy as np
from pathlib import Path

_SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
_ASSETS_DIR = _SCRIPT_DIR / "assets"
HAND_PATH = str(_ASSETS_DIR / "drawing-hand.png")

# Mac-optimized parameters
FRAME_RATE = 60
SPLIT_LEN = 4
MAX_1080P = True
DEFAULT_TOTAL_DURATION_SECONDS = 10
HOLD_PHASE_DURATION_SECONDS = 3
SKETCH_PHASE_WEIGHT = 2
COLOR_PHASE_WEIGHT = 1
COLOR_BRUSH_RADIUS = 50
SKIP_RATE = 1
BACKGROUND_HEX = "#F6F1E3"
HAND_TARGET_HT = 493
BLACK_PIXEL_THRESHOLD = 10
ROW_GROUP_MAX_GAP = 1
BLOCK_SPAN_MAX_GAP = 1
BLOCK_SUB_BAND_ROWS = 3
TEXT_LIKE_MIN_HEIGHT = 3
TEXT_LIKE_MAX_HEIGHT = 12
TEXT_LIKE_MIN_ASPECT_RATIO = 2.2
TEXT_LIKE_MIN_DENSITY = 0.5
TEXT_SEGMENT_MIN_WIDTH = 3
TEXT_SEGMENT_MAX_WIDTH = 6
ORGANIC_MAX_ASPECT_RATIO = 2.0
ORGANIC_MIN_LARGEST_CC_RATIO = 0.90
ORGANIC_MAX_PROVISIONAL_BLOCKS = 3
ORGANIC_START_TOP_RATIO = 0.15
ORGANIC_WIDE_START_TOP_RATIO = 0.25
ORGANIC_WIDE_MIN_ASPECT_RATIO = 1.4
COMPONENT_PRIORITY_MIN_SIZE = 8
COMPONENT_PRIORITY_MIN_RATIO = 0.03
STRUCTURED_SPAN_SUPPORT_COL_MARGIN = 2
STRUCTURED_PRIMARY_SCORE_RATIO = 0.79
STRUCTURED_PRIMARY_SUPPORT_RATIO = 0.45

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
BACKGROUND_RGB = np.array(_hex_to_rgb(BACKGROUND_HEX), dtype=np.uint8)
BACKGROUND_BGR = BACKGROUND_RGB[::-1].copy()

def euc_dist(a, p): return np.sqrt(np.sum((a - p) ** 2, axis=1))
def get_extreme_coordinates(m):
    x, y = np.where(m > 0)[1], np.where(m > 0)[0]
    return (np.min(x), np.min(y)), (np.max(x), np.max(y))

def preprocess_image(img, v):
    img = cv2.resize(img, (v["resize_wd"], v["resize_ht"]))
    v["img_gray"] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    v["img_thresh"] = cv2.adaptiveThreshold(v["img_gray"], 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10)
    v["img"] = img
    return v

def preprocess_hand(hand_path, v):
    h = cv2.imread(hand_path, cv2.IMREAD_UNCHANGED)
    hm = h[:,:,3] if h.shape[2]==4 else cv2.threshold(cv2.cvtColor(h, cv2.COLOR_BGR2GRAY), 250, 255, cv2.THRESH_BINARY_INV)[1]
    tl, br = get_extreme_coordinates(hm)
    h, hm = h[tl[1]:br[1], tl[0]:br[0]], hm[tl[1]:br[1], tl[0]:br[0]]
    s = HAND_TARGET_HT / h.shape[0]
    nw = max(1, int(h.shape[1] * s))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    h = cv2.resize(h, (nw, HAND_TARGET_HT), interpolation=interp)
    hm = cv2.resize(hm, (nw, HAND_TARGET_HT), interpolation=interp).astype(np.float32) / 255.0
    h[np.where(hm == 0)] = [0, 0, 0]
    v["hand_ht"], v["hand_wd"] = h.shape[0], h.shape[1]
    v["hand"], v["hand_mask"], v["hand_mask_inv"] = h, hm, 1.0 - hm
    return v

def create_background(s):
    c = np.zeros(s, dtype=np.uint8)
    c[...] = BACKGROUND_BGR
    return c

def compute_phase(dur_ms):
    hold_ms = HOLD_PHASE_DURATION_SECONDS * 1000
    anim_ms = dur_ms - hold_ms
    r = anim_ms % (SKETCH_PHASE_WEIGHT + COLOR_PHASE_WEIGHT)
    if r: anim_ms, hold_ms = anim_ms - r, hold_ms + r
    return {"hold": round(hold_ms*FRAME_RATE/1000), "sketch": round(anim_ms*SKETCH_PHASE_WEIGHT/(SKETCH_PHASE_WEIGHT+COLOR_PHASE_WEIGHT)*FRAME_RATE/1000),
            "color": round(anim_ms*COLOR_PHASE_WEIGHT/(SKETCH_PHASE_WEIGHT+COLOR_PHASE_WEIGHT)*FRAME_RATE/1000)}

def draw_hand(d, hand, x, y, hm, hmi, hh, hw, ih, iw):
    ch, cw = min(hh, ih-y), min(hw, iw-x)
    if ch <= 0 or cw <= 0: return d
    hc, hmc, hmic = hand[:ch,:cw], hm[:ch,:cw], hmi[:ch,:cw]
    for c in range(3): d[y:y+ch, x:x+cw, c] = d[y:y+ch, x:x+cw, c] * hmic + hc[:,:,c] * hmc
    return d

def split_cells(img, sl):
    h, w = img.shape[:2]
    nr, nc = h//sl, w//sl
    return img.reshape(nr, sl, nc, sl, 3).transpose(0, 2, 1, 3, 4) if img.ndim==3 else img.reshape(nr, sl, nc, sl).transpose(0, 2, 1, 3)

def get_active(img_th, sl):
    gc = split_cells(img_th, sl)
    ag = np.any(gc < BLACK_PIXEL_THRESHOLD, axis=(2, 3))
    return ag, [tuple(int(v) for v in c) for c in np.argwhere(ag)]

def _merge_indices(idx, mg):
    if len(idx) == 0: return []
    spans, s, e = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - e <= mg + 1: e = i
        else: spans.append((s, e)); s, e = i, i
    spans.append((s, e))
    return spans

def _span_center(sp): return (sp[0] + sp[1]) / 2.0

def _nearest_order(cells, seed):
    remaining, ordered = [tuple(c) for c in cells], [tuple(seed)]
    remaining.remove(tuple(seed))
    cur = tuple(seed)
    while remaining:
        ra = np.array(remaining)
        nxt = int(np.argmin(euc_dist(ra, np.array(cur))))
        cur = remaining.pop(nxt)
        ordered.append(cur)
    return ordered

def _get_bounds(cells):
    rs, cs = [c[0] for c in cells], [c[1] for c in cells]
    return min(rs), max(rs), min(cs), max(cs)

def _get_cc(cells):
    tr, br, lc, rc = _get_bounds(cells)
    m = np.zeros((br - tr + 1, rc - lc + 1), dtype=np.uint8)
    for r, c in cells: m[r - tr, c - lc] = 1
    nl, lb = cv2.connectedComponents(m, connectivity=8)
    comps = []
    for lbl in range(1, nl):
        pos = np.argwhere(lb == lbl)
        cc = [(int(r + tr), int(c + lc)) for r, c in pos]
        cr = [c[0] for c in cc]; cc2 = [c[1] for c in cc]
        comps.append({"size": len(cc), "cells": sorted(cc), "top": min(cr), "bottom": max(cr), "left": min(cc2), "right": max(cc2),
                       "center_row": float(np.mean(cr)), "center_col": float(np.mean(cc2))})
    comps.sort(key=lambda x: (-x["size"], x["top"], x["left"]))
    return comps

def _looks_like_text(cells):
    if not cells: return False
    tr, br, lc, rc = _get_bounds(cells)
    bh, bw = br - tr + 1, rc - lc + 1
    return TEXT_LIKE_MIN_HEIGHT <= bh <= TEXT_LIKE_MAX_HEIGHT and bw/max(1,bh) >= TEXT_LIKE_MIN_ASPECT_RATIO and len(cells)/max(1,bh*bw) >= TEXT_LIKE_MIN_DENSITY

def _classify_group(cells, nc):
    tr, br, lc, rc = _get_bounds(cells)
    gh, gw = br - tr + 1, rc - lc + 1
    ar = gw / max(1, gh)
    cc = _get_cc(cells)
    lcc = cc[0]["size"] / len(cells) if cc else 0
    if _looks_like_text(cells): return "text_like"
    if ar <= ORGANIC_MAX_ASPECT_RATIO and lcc >= ORGANIC_MIN_LARGEST_CC_RATIO: return "organic_like"
    return "structured_like"

def _build_organic_order(cells):
    comps = _get_cc(cells)
    pt = max(COMPONENT_PRIORITY_MIN_SIZE, math.ceil(len(cells) * COMPONENT_PRIORITY_MIN_RATIO))
    pri = [c for c in comps if c["size"] >= pt] or [comps[0]]
    cells_flat = [tuple(c) for c in pri[0]["cells"]]
    order = _nearest_order(cells_flat, cells_flat[0])
    cur = order[-1]
    for comp in comps:
        if comp["size"] < pt:
            c2 = [tuple(c) for c in comp["cells"]]
            seed = min(c2, key=lambda c: (c[0]-cur[0])**2 + (c[1]-cur[1])**2)
            o2 = _nearest_order(c2, seed)
            order.extend(o2); cur = o2[-1]
    return order

def _build_layout(ag):
    cells = [tuple(int(v) for v in c) for c in np.argwhere(ag)]
    if not cells: return []
    nr, nc = ag.shape
    row_counts = np.sum(ag, axis=1)
    rspans = _merge_indices(np.where(row_counts >= max(3, math.ceil(nc * 0.05)))[0], ROW_GROUP_MAX_GAP) or [(int(np.where(row_counts>0)[0][0]), int(np.where(row_counts>0)[0][-1]))]
    blocks = []
    for rg_idx, (rs, re) in enumerate(rspans):
        gcells = [c for c in cells if rs <= c[0] <= re]
        if not gcells: continue
        strategy = _classify_group(gcells, nc)
        if strategy == "organic_like":
            blocks.append({"cells": gcells, "order": _build_organic_order(gcells)})
        else:
            blocks.append({"cells": gcells, "order": _nearest_order(gcells, min(gcells))})
    return blocks

def render_scene(args, v):
    ag, cells = get_active(v["img_thresh"], v["split_len"])
    v["active_grid"], v["active_cells"] = ag, cells
    blocks = _build_layout(ag)
    v["draw_order"] = []
    for b in blocks: v["draw_order"].extend(b["order"])
    
    actual = len(v["draw_order"])
    pf = compute_phase(args.duration)
    sk_target = pf["sketch"] * SKIP_RATE
    
    # Create video writer with Mac-optimized codec
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vout = cv2.VideoWriter(v["raw_path"], fourcc, FRAME_RATE, (v["resize_wd"], v["resize_ht"]))
    v["drawn_frame"] = create_background(v["img"].shape)
    
    # Mac: Use all cores for OpenCV
    cv2.setNumThreads(8)
    
    counter, fa, fw = 0, 0.0, 0
    fr = sk_target / max(1, actual)
    print(f"  {actual} cells, {sk_target} target cells, {fr:.2f} ratio")
    
    for row, col in v["draw_order"]:
        rvs, rve = row * v["split_len"], row * v["split_len"] + v["split_len"]
        chs, che = col * v["split_len"], col * v["split_len"] + v["split_len"]
        tc = v["grid_of_cuts"][row, col]
        td = np.repeat(tc[:,:,None], 3, axis=2).astype(np.uint8)
        ink = tc < BLACK_PIXEL_THRESHOLD
        if np.any(ink): v["drawn_frame"][rvs:rve, chs:che][ink] = td[ink]
        
        if v["draw_hand"]:
            hx, hy = chs + v["split_len"] // 2, rvs + v["split_len"] // 2
            frame = draw_hand(v["drawn_frame"].copy(), v["hand"], hx, hy, v["hand_mask"], v["hand_mask_inv"], v["hand_ht"], v["hand_wd"], v["resize_ht"], v["resize_wd"])
        else:
            frame = v["drawn_frame"].copy()
        
        counter += 1; fa += fr
        nf = int(fa) - fw
        if nf > 0:
            for _ in range(nf): vout.write(frame.astype(np.uint8))
            fw += nf
        if counter % 200 == 0: print(f"  {int(counter/actual*100)}%")
    
    # Hold phase
    end_img = v["drawn_frame"].astype(np.uint8)
    for _ in range(pf["hold"]): vout.write(end_img)
    vout.release()
    print(f"  Done: {counter} steps, {fw} frames")

def h264_convert(src, dst):
    import subprocess
    # Use ffmpeg with VideoToolbox for Mac speed
    cmd = ["ffmpeg", "-y", "-i", src, "-c:v", "h264_videotoolbox", "-quality", "95", "-b:v", "2000k", dst, "-hide_banner"]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        os.unlink(src)
        return dst
    except: return src

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image_path"); ap.add_argument("--output-dir", default="./output_mac")
    ap.add_argument("--duration", type=int, default=10000); ap.add_argument("--no-hand", action="store_true"); ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    
    img = cv2.imread(args.image_path)
    if img is None: print(f"Error: can't read {args.image_path}"); sys.exit(1)
    
    h, w = img.shape[:2]
    # Keep original dimensions - input images are already 9:16
    # Only resize if image is very large (>1080p)
    if max(w, h) > 1080:
        s = 1080 / max(w, h)
        w, h = int(w * s), int(h * s)
    lcm = SPLIT_LEN if SPLIT_LEN % 2 == 0 else SPLIT_LEN * 2
    w, h = (w // lcm) * lcm, (h // lcm) * lcm
    
    os.makedirs(args.output_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(args.output_dir, f"vid_{ts}.mp4")
    h264_path = os.path.join(args.output_dir, f"vid_{ts}_h264.mp4")
    
    v = {"frame_rate": FRAME_RATE, "resize_wd": w, "resize_ht": h, "split_len": SPLIT_LEN, "draw_hand": not args.no_hand, "raw_path": raw_path}
    
    v = preprocess_image(img, v)
    v["grid_of_cuts"] = split_cells(v["img_thresh"], SPLIT_LEN)
    
    if v["draw_hand"]:
        try: v = preprocess_hand(HAND_PATH, v)
        except: print("No hand asset, continuing without hand"); v["draw_hand"] = False
    
    render_scene(args, v)
    final = h264_convert(raw_path, h264_path)
    print(f"Done: {final}")
    sys.exit(0)

if __name__ == "__main__":
    main()
