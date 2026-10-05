/* basemap.js — keyless basemap for hk-pet-portal
 *
 * Primary : OpenFreeMap "positron" (vector tiles, MapLibre GL) — no API key,
 *           no account, no request quota, commercial use allowed, MIT.
 *           Same light-grey Positron look the site had with CARTO light_all.
 * Fallback: Esri "World Light Gray Canvas" raster (also keyless) if the
 *           style JSON or the MapLibre runtime cannot be used.
 *
 * Why: CARTO raster basemaps started requiring an API key on 2026-09-23 and
 * every tile served without one is a 2 KB "API KEY REQUIRED" watermark.
 * Neither provider used here can break that way.
 *
 * Usage in an Astro page, right after the Leaflet map + markers are created:
 *     NexiBasemap.add(map);
 */
(function () {
  var OFM_STYLE = 'https://tiles.openfreemap.org/styles/positron';
  var ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  var OFM_ATTR = '<a href="https://openfreemap.org/">OpenFreeMap</a> ' +
    '&copy; <a href="https://www.openmaptiles.org/">OpenMapTiles</a> ' +
    'Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
  var ESRI_ATTR = '&copy; <a href="https://www.esri.com/">Esri</a> ' +
    '&copy; OpenStreetMap contributors';

  function addAttribution(map, html) {
    try { if (map.attributionControl) map.attributionControl.addAttribution(html); } catch (e) {}
  }

  function addEsri(map) {
    if (map.__basemapDone) return;
    map.__basemapDone = true;
    L.tileLayer(ESRI + 'World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      maxNativeZoom: 16, maxZoom: 19, attribution: ESRI_ATTR
    }).addTo(map);
    L.tileLayer(ESRI + 'World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxNativeZoom: 16, maxZoom: 19, pane: 'shadowPane'
    }).addTo(map);
    map.__basemapKind = 'esri-raster-fallback';
  }

  function add(map) {
    if (!map || typeof L === 'undefined') return;
    map.__basemapKind = 'pending';

    // No MapLibre bridge available (script blocked / old browser): raster only.
    if (typeof L.maplibreGL !== 'function' || typeof maplibregl === 'undefined') {
      addEsri(map);
      return;
    }

    // If the style JSON does not answer quickly, go raster so the page is never
    // left with a blank map.
    var stall = setTimeout(function () { addEsri(map); }, 6000);

    fetch(OFM_STYLE, { method: 'GET', cache: 'force-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('style http ' + r.status);
        if (map.__basemapDone) return;
        clearTimeout(stall);
        try {
          var gl = L.maplibreGL({ style: OFM_STYLE, attributionControl: false }).addTo(map);
          map.__glLayer = gl;
          addAttribution(map, OFM_ATTR);
          map.__basemapKind = 'openfreemap-positron-vector';
          // 首次加完之後版面可能仲未定（字體／reveal 動畫）→ 過一陣再同步一次
          setTimeout(function () { resize(map); }, 150);
        } catch (e) {
          addEsri(map);
        }
      })
      .catch(function () {
        clearTimeout(stall);
        addEsri(map);
      });
  }

  /* 容器大細變咗（例如拖分線／視窗 resize）時，Leaflet 只會 invalidateSize，
     但 @maplibre/maplibre-gl-leaflet 0.1.0 有兩個陷阱（實測 2026-10-05）：
       1. resize handler 唔會叫 MapLibre resize；
       2. gl 容器嘅 width/height 只喺 onAdd 時寫死 px（_initContainer），之後
          再冇更新 → 拖闊之後 canvas 停留舊闊度，右邊出現空條。
     所以呢度要自己：改 gl 容器 px → 叫 MapLibre resize → fire('move') 重新定位。 */
  function resize(map) {
    var layer = map && map.__glLayer;
    if (!layer) return;
    try {
      var cont = (layer.getContainer && layer.getContainer()) || layer._container;
      if (cont) {
        // ⚠️ 一定要用 layer.getSize()（= map size × (1 + padding*2)，預設 1.2 倍），
        // 唔係 map.getSize()。插件刻意整大個 gl 容器等滾動時唔使即刻重繪；
        // 用細咗嘅尺寸會令容器縮細 + 位置偏移，右／下邊出現一條冇圖嘅空條。
        var s = layer.getSize ? layer.getSize() : map.getSize();
        cont.style.width = s.x + 'px';
        cont.style.height = s.y + 'px';
      }
      var m = layer.getMaplibreMap ? layer.getMaplibreMap() : null;
      if (m && m.resize) m.resize();
      if (map.fire) map.fire('move');
    } catch (e) {}
  }

  window.NexiBasemap = { add: add, resize: resize };
})();
