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
          L.maplibreGL({ style: OFM_STYLE, attributionControl: false }).addTo(map);
          addAttribution(map, OFM_ATTR);
          map.__basemapKind = 'openfreemap-positron-vector';
        } catch (e) {
          addEsri(map);
        }
      })
      .catch(function () {
        clearTimeout(stall);
        addEsri(map);
      });
  }

  window.NexiBasemap = { add: add };
})();
