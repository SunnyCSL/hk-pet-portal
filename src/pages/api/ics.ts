// GET /api/ics?d=<base64url(JSON)>
// 寵物用藥日曆產生器 —— 回傳 text/calendar（iOS Safari 只認「真 URL 回 text/calendar」，
// blob:/data: URI 一律被封）。payload 完全放喺 URL 內 → 無 DB、無 PII、無 logging。
export const prerender = false;

import type { APIRoute } from 'astro';

type Item = [string, number, string]; // [name, intervalMonths, lastDateISO]

/** 加月份，遇月底自動夾（例：1/31 + 1 個月 = 2/28）。 */
function addMonths(iso: string, months: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const total = m - 1 + months;
  const ny = y + Math.floor(total / 12);
  const nm = (total % 12) + 1;
  const lastDay = new Date(Date.UTC(ny, nm, 0)).getUTCDate();
  const dd = Math.min(d, lastDay);
  return `${ny}-${String(nm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
}

function esc(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
}

/** iCalendar 75-octet 折行。 */
function fold(line: string): string {
  const chars = [...line];
  let out = '';
  let cur = '';
  for (const ch of chars) {
    if (cur.length + ch.length > 73) {
      out += (out ? '\r\n ' : '') + cur;
      cur = ch;
    } else {
      cur += ch;
    }
  }
  return out + (out ? '\r\n ' : '') + cur;
}

function buildIcs(pet: string, items: Item[]): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const L: string[] = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//HK Pet Portal//Pet Med Calendar//ZH-HK',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    `X-WR-CALNAME:${esc(pet + ' 用藥時間表')}`,
    'X-WR-TIMEZONE:Asia/Hong_Kong',
    'REFRESH-INTERVAL;VALUE=DURATION:P1W',
    'X-PUBLISHED-TTL:P1W',
  ];
  items.forEach(([name, months, last], i) => {
    const nxt = addMonths(last, months);
    const ymd = nxt.replace(/-/g, '');
    L.push(
      'BEGIN:VEVENT',
      `UID:petmed-${i}-${ymd}@hk-pet-portal`,
      `DTSTAMP:${stamp}`,
      `DTSTART:${ymd}T010000Z`, // 09:00 HKT
      `DTEND:${ymd}T013000Z`,
      `SUMMARY:${esc('🐾 ' + pet + ' · ' + name)}`,
      `DESCRIPTION:${esc(`${pet} 需要 ${name}（每 ${months} 個月）。上次：${last}。`)}`,
      'STATUS:CONFIRMED',
      'TRANSP:TRANSPARENT',
      'BEGIN:VALARM',
      'ACTION:DISPLAY',
      `DESCRIPTION:${esc(`聽日要俾 ${pet} ${name}`)}`,
      'TRIGGER:-P1D',
      'END:VALARM',
      'BEGIN:VALARM',
      'ACTION:DISPLAY',
      `DESCRIPTION:${esc(`今日要俾 ${pet} ${name}`)}`,
      'TRIGGER:-PT0M',
      'END:VALARM',
      'END:VEVENT',
    );
  });
  L.push('END:VCALENDAR');
  return L.map(fold).join('\r\n') + '\r\n';
}

function bad(status: number, msg: string): Response {
  return new Response(JSON.stringify({ error: msg }), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

export const GET: APIRoute = ({ request }) => {
  const raw = new URL(request.url).searchParams.get('d') || '';
  if (!raw || raw.length > 6000) return bad(400, 'missing or oversized d');
  try {
    // ⚠️ JS 嘅 % 會保留負號（-158 % 4 === -2），所以一定要先 +4 再 %4
    const pad = (4 - (raw.length % 4)) % 4;
    const b64 = raw.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat(pad);
    const json = Buffer.from(b64, 'base64').toString('utf-8');
    const data = JSON.parse(json);
    const pet = String(data?.p ?? '我隻寵物').slice(0, 40) || '我隻寵物';
    const arr = Array.isArray(data?.i) ? data.i.slice(0, 40) : [];
    const items: Item[] = [];
    for (const x of arr) {
      if (!Array.isArray(x) || x.length < 3) continue;
      const name = String(x[0]).slice(0, 60).trim();
      const months = Math.max(1, Math.min(120, parseInt(String(x[1]), 10) || 1));
      const last = String(x[2]).slice(0, 10);
      if (!name || !/^\d{4}-\d{2}-\d{2}$/.test(last)) continue;
      items.push([name, months, last]);
    }
    if (!items.length) return bad(400, 'no valid items');
    const body = buildIcs(pet, items);
    return new Response(body, {
      status: 200,
      headers: {
        'Content-Type': 'text/calendar; charset=utf-8',
        'Content-Disposition': 'inline; filename="pet-med-calendar.ics"',
        'Cache-Control': 'no-store',
      },
    });
  } catch (e) {
    return bad(400, 'bad payload: ' + String((e as Error)?.message ?? e).slice(0, 120));
  }
};
