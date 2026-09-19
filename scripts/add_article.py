#!/usr/bin/env python3
"""add_article.py — 安全咁加一篇文章入 health-articles.json（唔手打 JSON escape）。

用法:
  python3 scripts/add_article.py /tmp/article_xxx.json          # 新增（slug 重複即 abort）
  python3 scripts/add_article.py /tmp/article_xxx.json --update  # 覆寫同 slug 嘅文章

做嘅嘢：json.load → slug 檢查 → shutil.copy2 備份 → json.dump(ensure_ascii=False) →
重新 load 驗證 + 印字數。內文 HTML 一定要真 HTML（唔可以 double-escape）。
"""
import json, os, shutil, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(BASE, 'src/data/health-articles.json')
REQUIRED = ('slug', 'title', 'title_en', 'emoji', 'cat', 'catName', 'catName_en',
            'tags', 'tags_en', 'content_html', 'content_html_en', 'desc_en',
            'source', 'source_en', 'disclaimer', 'disclaimer_en', 'date', 'date_iso')


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    new = json.load(open(sys.argv[1], encoding='utf-8'))
    update = '--update' in sys.argv
    miss = [k for k in REQUIRED if not new.get(k)]
    if miss:
        print(f'❌ 缺欄位：{miss}'); sys.exit(1)
    for k in ('content_html', 'content_html_en'):
        if '&lt;p' in new[k]:
            print(f'❌ {k} 有 double-escape（&lt;p）— 唔好 escape HTML'); sys.exit(1)

    arts = json.load(open(TARGET, encoding='utf-8'))
    idx = next((i for i, a in enumerate(arts) if a['slug'] == new['slug']), None)
    if idx is not None and not update:
        print(f"❌ slug 已存在：{new['slug']}（要覆寫加 --update）"); sys.exit(2)
    bak = TARGET + f".bak-{new['slug'].split('-')[0]}"
    shutil.copy2(TARGET, bak)
    if idx is None:
        arts.append(new); action = '新增'
    else:
        arts[idx] = new; action = '覆寫'
    json.dump(arts, open(TARGET, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    chk = json.load(open(TARGET, encoding='utf-8'))
    got = next(a for a in chk if a['slug'] == new['slug'])
    print(f"✅ {action} {new['slug']}｜文章總數 {len(chk)}｜zh {len(got['content_html'])} 字｜"
          f"en {len(got['content_html_en'])} 字｜備份 {os.path.basename(bak)}")


if __name__ == '__main__':
    main()
