#!/usr/bin/env python3
"""
migrate-article-classes.py — One-off migration to upgrade inline Tailwind
classes inside the prose body of every article stored in
src/data/health-articles.json.

Background
----------
Articles ship as plain HTML inside the JSON's `content_html` /
`content_html_en` fields. The zh field is **double-encoded** (HTML
entities), the en field is **plain HTML**. Both contain Tailwind utility
classes inline on every element (e.g. `<p class="text-sm text-gray-600
leading-relaxed mb-2">…</p>`). The article page just `set:html`-injects
them.

Phase 2 UI upgrade wanted to bump the reading typography
(text-base / leading-8 / better margins, h2 brand-green bar, table
zebra, blockquote left bar) without forcing us to ship a fragile
global-CSS-override layer. Doing it at the JSON level is more robust
because every site that consumes the JSON (current page, future RSS
export, JSON-LD, etc.) gets the upgrade for free.

What this script does
---------------------
Per article we touch `content_html` (zh) and `content_html_en` (en).
For each we apply a sequence of regex substitutions:

  text-sm text-gray-600 leading-relaxed mb-2  → text-base text-gray-700 leading-8 mb-5
  text-sm text-gray-600 leading-relaxed mb-3  → text-base text-gray-700 leading-8 mb-6
  text-lg font-bold text-near-black mt-6 mb-2 → text-xl font-bold text-near-black mt-10 mb-3
  text-base font-semibold text-near-black mt-5 mb-1.5 → text-lg font-semibold text-near-black mt-6 mb-2
  …etc.

Important: only run this ONCE on each field. The substitutions are
designed to be idempotent (output class strings do not match any input
class string). Running it twice on the same data is a no-op.

Run order
---------
1. python3 scripts/migrate-article-classes.py           (default: src/data/health-articles.json)
2. python3 scripts/migrate-article-classes.py --dry-run  (preview only)
3. python3 scripts/migrate-article-classes.py --revert   (undo from .bak.json)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Substitution table. Order matters: longer / more specific patterns first so
# we don't accidentally rewrite a substring of a larger match.
# ---------------------------------------------------------------------------
SUBS: list[tuple[re.Pattern[str], str]] = [
    # ---------- Body paragraphs ----------
    # The two paragraph rhythms we use today. Both share text-sm+text-gray-600
    # but differ in vertical rhythm (mb-2 vs mb-3).
    (re.compile(r'\btext-sm text-gray-600 leading-relaxed mb-3\b'),
     'text-base text-gray-700 leading-8 mb-6'),
    (re.compile(r'\btext-sm text-gray-600 leading-relaxed mb-2\b'),
     'text-base text-gray-700 leading-8 mb-5'),
    (re.compile(r'\btext-sm text-gray-600 leading-relaxed\b'),
     'text-base text-gray-700 leading-8'),
    # Stray text-sm paragraphs (e.g. inside disclaimers or late edits).
    (re.compile(r'\btext-sm text-gray-600 mb-2\b'),
     'text-base text-gray-700 leading-8 mb-5'),
    (re.compile(r'\btext-sm text-gray-600 mb-1\b'),
     'text-base text-gray-700 leading-8 mb-4'),
    # Bare text-sm fallback (rare, defensive).
    (re.compile(r'\btext-sm text-gray-600\b'),
     'text-base text-gray-700 leading-8'),

    # ---------- Lists ----------
    # li in ol/ul
    (re.compile(r'\btext-sm text-gray-600 mb-1\b'),
     'text-base text-gray-700 leading-8 mb-3'),

    # ---------- Headings ----------
    # h2 — was text-lg mt-6 mb-2, now slightly bigger and with more breath.
    (re.compile(r'\btext-lg font-bold text-near-black mt-6 mb-2\b'),
     'text-xl font-bold text-near-black mt-10 mb-3'),
    # h3 — was text-base mt-5 mb-1.5, now text-lg mt-6 mb-2.
    (re.compile(r'\btext-base font-semibold text-near-black mt-5 mb-1\.5\b'),
     'text-lg font-semibold text-near-black mt-6 mb-2'),

    # ---------- Table cells (zebra + accent header) ----------
    # Header cells: keep bg but deepen text contrast.
    (re.compile(r'\bbg-gray-50 text-gray-700 text-left font-medium\b'),
     'bg-brand-light text-brand font-semibold text-left'),
    # Body cells: keep border, soften padding for density.
    (re.compile(r'\bborder border-gray-100 px-3 py-2\b'),
     'border border-gray-100 px-3 py-2.5'),
    # Table itself — keep border-collapse.
    (re.compile(r'\bw-full text-xs border-collapse\b'),
     'w-full text-sm border-collapse'),

    # ---------- Lists container rhythm ----------
    # ol/ul lists — slight tweak: mb-3 stays, my-3 → my-4 to give the table
    # a touch more room above/below.
    (re.compile(r'\blist-decimal ml-5 mb-3\b'),
     'list-decimal ml-5 mb-5'),
    (re.compile(r'\blist-disc ml-5 mb-3\b'),
     'list-disc ml-5 mb-5'),
]


def migrate_html(html_str: str) -> tuple[str, int]:
    """Apply every substitution. Returns (new_html, replacement_count)."""
    if not html_str:
        return html_str, 0
    count = 0
    out = html_str
    for pattern, replacement in SUBS:
        out, n = pattern.subn(replacement, out)
        count += n
    return out, count


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    p.add_argument('--file', default='src/data/health-articles.json',
                   help='Path to health-articles.json (default: src/data/health-articles.json)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show what would change, do not write.')
    p.add_argument('--revert', action='store_true',
                   help='Restore from <file>.bak.json if present.')
    p.add_argument('--fields', default='content_html,content_html_en',
                   help='Comma-separated JSON fields to migrate.')
    args = p.parse_args()

    repo = Path(__file__).resolve().parents[1]
    target = repo / args.file
    fields = [f.strip() for f in args.fields.split(',') if f.strip()]

    if args.revert:
        bak = target.with_suffix(target.suffix + '.bak.json')
        if not bak.exists():
            print(f'No backup at {bak}. Nothing to revert.')
            return 1
        shutil.copy2(bak, target)
        print(f'Reverted {target} from {bak}')
        return 0

    with target.open('r', encoding='utf-8') as f:
        data = json.load(f)

    total_subs = 0
    total_articles = 0
    touched_articles: list[str] = []
    for article in data:
        slug = article.get('slug', '<unknown>')
        article_changes = 0
        for field in fields:
            original = article.get(field, '') or ''
            new, n = migrate_html(original)
            if n > 0:
                article[field] = new
                article_changes += n
                total_subs += n
        if article_changes:
            total_articles += 1
            touched_articles.append(f'  - {slug}: {article_changes} replacement(s)')

    if total_subs == 0:
        print('No substitutions made — classes may already be migrated.')
        return 0

    print(f'Total substitutions: {total_subs} across {total_articles} article(s)')
    for line in touched_articles:
        print(line)

    if args.dry_run:
        print('\nDry run — not writing.')
        return 0

    # Back up the original on the first run only.
    bak = target.with_suffix(target.suffix + '.bak.json')
    if not bak.exists():
        shutil.copy2(target, bak)
        print(f'Backed up original to {bak}')

    with target.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f'Wrote {target}')
    return 0


if __name__ == '__main__':
    sys.exit(main())