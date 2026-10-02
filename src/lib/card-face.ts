// Card face rule (2026-10-02, Sunny) — 前端鏡像：public/card-face.js
//   有菜系標籤 → 菜系插畫 /illus/<type>-v<n>.jpg
//   冇菜系標籤 → 地圖縮圖 /thumbs/<id>.jpg
// 零估錯：唔會為未分類嘅店砌一個菜系插畫。
import typesJson from '../data/restaurant-types.json';
import illusJson from '../data/cuisine-illus.json';

const TYPES = typesJson as Record<string, { types?: string[] }>;
const ILLUS = illusJson as Record<string, string[]>;

export function cardFace(id: number | string): string {
  const rec = TYPES[String(id)];
  const t = rec?.types?.[0];
  const vs = t ? ILLUS[t] : undefined;
  if (vs && vs.length) return `/illus/${vs[Number(id) % vs.length]}`;
  return `/thumbs/${id}.jpg`;
}
