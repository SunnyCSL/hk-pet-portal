/* 健康圖書館分類篩選（zh/en 共用）
 *
 * 為何要 client-side：astro.config.mjs 係 output: 'static' → 頁面 frontmatter 嘅
 * `Astro.url.searchParams.get('cat')` 係 build 時執行，永遠攞到空字串，
 * 所以 `/health?cat=tcm` 之類嘅 URL 以前永遠顯示全部文章（首頁四個分類磚 + 分類 chips 全部中招）。
 * 呢支 script 喺瀏覽器讀 query param、即時隱藏唔匹配嘅卡、更新 chip 狀態同空狀態。
 *
 * 契約（頁面要出嘅 hook）：
 *   [data-health-grid]   ← 包住所有文章卡嘅容器
 *   [data-cat]           ← 每張卡只帶自己嘅分類 key（nutrition/tcm/care/behavior）
 *   [data-cat-chip]      ← 分類 chip，值 = 分類 key（「全部」= 空字串）
 *   [data-health-empty]  ← 冇結果時顯示（預設 hidden）
 */
(function () {
  function currentCat() {
    try {
      return new URLSearchParams(window.location.search).get('cat') || '';
    } catch (e) {
      return '';
    }
  }

  function apply() {
    var grid = document.querySelector('[data-health-grid]');
    if (!grid) return;
    var cat = currentCat();
    var shown = 0;

    var cards = grid.querySelectorAll('[data-cat]');
    for (var i = 0; i < cards.length; i++) {
      var el = cards[i];
      var match = !cat || el.getAttribute('data-cat') === cat;
      el.style.display = match ? '' : 'none';
      if (match) shown++;
    }

    var chips = document.querySelectorAll('[data-cat-chip]');
    for (var j = 0; j < chips.length; j++) {
      var a = chips[j];
      var isOn = (a.getAttribute('data-cat-chip') || '') === cat;
      a.classList.toggle('is-active', isOn);
      a.setAttribute('aria-current', isOn ? 'true' : 'false');
    }

    var empty = document.querySelector('[data-health-empty]');
    if (empty) empty.hidden = shown !== 0;

    document.documentElement.setAttribute('data-health-cat', cat);
  }

  // chip 撳落去唔使 reload：更新 URL 再即時過濾（back/forward 亦跟得住）
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var a = t.closest('[data-cat-chip]');
    if (!a) return;
    // 中鍵／新視窗開法唔攔
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    var cat = a.getAttribute('data-cat-chip') || '';
    var url = window.location.pathname + (cat ? '?cat=' + encodeURIComponent(cat) : '');
    history.pushState({ cat: cat }, '', url);
    apply();
  });

  window.addEventListener('popstate', apply);
  apply();
})();
