(function () {
  // Card face rule (2026-10-02, Sunny):
  //   有菜系標籤 → 菜系插畫 /illus/<type>-v<n>.jpg
  //   冇菜系標籤 → 地圖縮圖  /thumbs/<id>.jpg
  // 同旅行指南做法一致（有相用相、冇相用縮圖），零估錯。
  function read(id) {
    try {
      var el = document.getElementById(id);
      return el ? (JSON.parse(el.textContent || '{}') || {}) : {};
    } catch (e) { return {}; }
  }
  var TYPES = null, ILLUS = null;
  window.cardFaceSrc = function (id) {
    if (TYPES === null) { TYPES = read('restaurant-types'); ILLUS = read('cuisine-illus'); }
    var rec = TYPES[String(id)];
    var t = rec && rec.types && rec.types[0];
    var vs = t && ILLUS[t];
    if (vs && vs.length) return '/illus/' + vs[Number(id) % vs.length];
    return '/thumbs/' + id + '.jpg';
  };
})();
