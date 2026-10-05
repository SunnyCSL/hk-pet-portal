/* desk-splitter.js — 桌面左右分線（≥1000px）：拖動調地圖闊度、雙擊還原
 * 跟自家 travel 站（kr-travel-guide）2026-10-05 最新桌面版同一套做法：
 *   - 寬度寫入 CSS 變數 --map-w（:root），版面自己重排
 *   - 拖動＝「分線到容器右邊界」嘅距離；夾住唔低過 minMap、唔高過容器一半
 *     （唔係縮細視窗時左邊卡會被壓成一大張單欄方塊）
 *   - 大細記入 localStorage，但每次都會重新 clamp
 *   - 手機（<1000px）分線係 display:none，listener 唔會有意義 → 手機版面完全不變
 *
 * 用法：
 *   NexiSplitter.init({
 *     wrap: el, splitter: el, getMap: () => leafletMap,
 *     key: 'pet_list_map_w', defWidth: 460, minMap: 300, clampMin: 520, pad: 28
 *   });
 */
(function () {
  window.NexiSplitter = {
    init: function (opts) {
      var wrap = opts.wrap;
      var sp = opts.splitter;
      if (!wrap || !sp) return null;

      var KEY = opts.key || 'pet_map_w';
      var DEF = opts.defWidth || 420;
      var MIN_MAP = opts.minMap || 300;
      var CLAMP_MIN = opts.clampMin || 520;   // 左欄最少要留幾多 px
      var PAD = opts.pad || 28;               // 容器左右 padding
      var getMap = opts.getMap || function () { return null; };

      var apply = function (w) {
        document.documentElement.style.setProperty('--map-w', Math.round(w) + 'px');
      };
      var clamp = function (w) {
        var total = wrap.getBoundingClientRect().width - PAD * 2 - 10; // 減左右 padding + 分線闊度
        var cap = Math.max(MIN_MAP, Math.min(total - CLAMP_MIN, total * 0.5));
        return Math.max(MIN_MAP, Math.min(w, cap));
      };
      var invalidate = function () {
        var m = getMap();
        if (!m) return;
        if (m.invalidateSize) m.invalidateSize();
        // Leaflet 唔會叫 MapLibre canvas resize（見 basemap.js resize()）
        if (window.NexiBasemap && NexiBasemap.resize) NexiBasemap.resize(m);
      };
      // MapLibre 向量 canvas 追唔切單次 invalidateSize（實測拖完右邊會有空條）
      // → 即時叫一次，再喺 80ms / 260ms 各補一次，令 canvas 跟到新闊度。
      var invalidateSoon = function () {
        invalidate();
        setTimeout(invalidate, 80);
        setTimeout(invalidate, 260);
      };
      var current = function () {
        return parseInt((getComputedStyle(document.documentElement).getPropertyValue('--map-w') || '').trim(), 10) || DEF;
      };

      // 記住上次大細，但一定要過 clamp（換咗窄螢幕都唔會壓死左欄）
      try {
        var saved = parseInt(localStorage.getItem(KEY) || '', 10);
        if (saved > 0) apply(clamp(saved));
      } catch (e) {}

      window.addEventListener('resize', function () {
        if (window.innerWidth < 1000) return;
        apply(clamp(current()));
        invalidateSoon();
      });

      var dragging = false;
      function move(ev) {
        if (!dragging) return;
        var r = wrap.getBoundingClientRect();
        apply(clamp(r.right - PAD - ev.clientX)); // 分線越左 → 地圖越闊
        invalidateSoon();
        if (ev.cancelable) ev.preventDefault();
      }
      function up() {
        if (!dragging) return;
        dragging = false;
        sp.classList.remove('dragging');
        document.body.classList.remove('kr-dragging');
        try { localStorage.setItem(KEY, (getComputedStyle(document.documentElement).getPropertyValue('--map-w') || '').trim() || DEF + 'px'); } catch (e) {}
        invalidateSoon();
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
      }
      sp.addEventListener('pointerdown', function (ev) {
        dragging = true;
        sp.classList.add('dragging');
        document.body.classList.add('kr-dragging');
        try { sp.setPointerCapture(ev.pointerId); } catch (e) {}
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
        ev.preventDefault();
      });
      sp.addEventListener('dblclick', function () {   // 雙擊＝還原預設
        apply(DEF);
        try { localStorage.setItem(KEY, DEF + 'px'); } catch (e) {}
        invalidateSoon();
      });

      return { apply: apply, clamp: clamp, invalidate: invalidate, current: current };
    }
  };
})();
