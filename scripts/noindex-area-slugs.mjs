// Shared computation for the area-page `noindex` decision.
//
// Both `src/pages/restaurants/area/[slug].astro` (zh) and
// `src/pages/en/restaurants/area/[slug].astro` (en) emit `<meta robots
// noindex,follow>` when the candidate count is < 3. The Astro sitemap
// integration needs the same set so those pages can be excluded from the
// sitemap.
//
// The Astro page decides noindex via the union of (within 2 km radius) and
// (name/address hit OR alias-group match). To stay byte-identical we
// reproduce that algorithm here. Source of truth: the alias-groups list
// + the area-coord / restaurant-coord JSON files. If those change, both
// pages and this module pick the change up automatically.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA = join(__dirname, '..', 'src', 'data');

const areas = JSON.parse(readFileSync(join(DATA, 'area-centres.json'), 'utf8'));
const areaSlugs = JSON.parse(readFileSync(join(DATA, 'area-slugs.json'), 'utf8'));
const coords = JSON.parse(readFileSync(join(DATA, 'restaurant-coords.json'), 'utf8'));
const restaurants = JSON.parse(readFileSync(join(DATA, 'restaurants.json'), 'utf8'));

const SUB_AREAS = [
  '馬鞍山','科學園','白石角','香港仔','黃竹坑','海洋公園','淺水灣','赤柱','薄扶林','數碼港','鴨脷洲',
  '中環','上環','西營盤','堅尼地城','石塘咀','半山','山頂','金鐘',
  '銅鑼灣','跑馬地','大坑','天后','北角','鰂魚涌','太古','西灣河','筲箕灣','柴灣',
  '尖沙咀','尖東','佐敦','油麻地','旺角','太子','大角咀',
  '長沙灣','荔枝角','美孚',
  '土瓜灣','紅磡','何文田','啟德',
  '九龍灣','觀塘','牛頭角','藍田','油塘',
  '深井','馬灣','荃灣',
  '屯門','黃金海岸',
  '元朗','天水圍','錦田',
  '上水','粉嶺',
  '大埔',
  '沙田','大圍','火炭',
  '西貢','將軍澳','坑口','寶琳','調景嶺','康城','清水灣',
  '葵涌','葵芳','青衣',
  '東涌','愉景灣','迪士尼','機場','大澳','長洲','南丫島','坪洲',
];

const ALIAS_GROUPS = [
  { names: ['奧運','olympic','olympian'], keys: ['奧海城','海泓道','大角咀','利奧坊','海帆道','匯翔道','櫻桃街','奧柏'] },
  { names: ['旺角東'], keys: ['旺角','太子'] },
  { names: ['西九龍','west kowloon','elements','圓方'], keys: ['西九龍','柯士甸','圓方','elements'] },
  { names: ['科學園','science park'], keys: ['科學園','白石角'] },
];

const DEFAULT_RADIUS = 2000;

function haversine(lat1, lng1, lat2, lng2) {
  const R = 6371000.0;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function hitsArea(r, areaZh) {
  const base = ' '.concat(
    r.name_zh || '',
    r.name_en || '',
    r.address || '',
    r.district || ''
  );
  if (base.includes(areaZh)) return true;
  for (const g of ALIAS_GROUPS) {
    if (!g.names.includes(areaZh)) continue;
    if (g.keys.some((k) => base.includes(k))) return true;
  }
  return false;
}

// Same `byId` union as the Astro pages. Returns total candidate count.
function candidateCount(areaZh) {
  if (!areas[areaZh]) return 0;
  const c = areas[areaZh];
  const byId = new Map();
  for (const r of restaurants) {
    const cr = coords[String(r.id)];
    if (!cr || cr.lat == null || cr.lng == null) continue;
    const d = haversine(c.lat, c.lng, cr.lat, cr.lng);
    if (d <= DEFAULT_RADIUS) byId.set(r.id, d);
  }
  for (const r of restaurants) {
    if (byId.has(r.id)) continue;
    if (!hitsArea(r, areaZh)) continue;
    const cr = coords[String(r.id)];
    if (!cr || cr.lat == null || cr.lng == null) continue;
    const d = haversine(c.lat, c.lng, cr.lat, cr.lng);
    byId.set(r.id, d);
  }
  return byId.size;
}

const NOINDEX_THRESHOLD = 3;
const noindexSlugs = new Set();
for (const [zh, slug] of Object.entries(areaSlugs)) {
  if (!areas[zh]) continue;
  if (candidateCount(zh) < NOINDEX_THRESHOLD) noindexSlugs.add(slug);
}

export { noindexSlugs, SUB_AREAS, ALIAS_GROUPS, DEFAULT_RADIUS, NOINDEX_THRESHOLD };
