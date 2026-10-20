// LaCADIAN - shared header, navigation, footer and small helpers used on every page.
// A page sets <html data-root="../" data-page="Drought"> (root = path back to the site's top folder).
(function () {
  "use strict";
  const ROOT = document.documentElement.dataset.root || "";
  const PAGE = document.documentElement.dataset.page || "";

  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Load a data file. From a web server it is fetched as JSON. When index.html is opened straight from disk (file:)
  // the browser blocks fetch(), so the same data is loaded from the .js copy the update writes beside it.
  const loadedScripts = {};
  function getData(path) {
    if (location.protocol === "file:") {
      const js = ROOT + path.replace(/\.(json|geojson)$/, ".js");
      if (window.__LC && window.__LC[path]) return Promise.resolve(window.__LC[path]);
      return (loadedScripts[js] = loadedScripts[js] || new Promise((ok, no) => {
        const s = document.createElement("script");
        s.src = js; s.onload = () => (window.__LC && window.__LC[path] ? ok(window.__LC[path]) : no(new Error("empty " + path)));
        s.onerror = () => no(new Error("missing " + path));
        document.head.appendChild(s);
      })).then(() => window.__LC[path]);
    }
    return fetch(ROOT + path + "?v=" + Math.floor(Date.now() / 600000)).then(r => {
      if (!r.ok) throw new Error(path + ": HTTP " + r.status);
      return r.json();
    });
  }

  const NAV = [["Map", "index.html"], ["Stations", "pages/stations.html"], ["Parish reports", "pages/parish.html"],
               ["Data", "pages/data.html"], ["Methods", "pages/methods.html"], ["About", "pages/about.html"]];

  function frame() {
    const h = document.getElementById("hdr");
    if (h) {
      h.className = "top";
      h.innerHTML = `<div class="wrap bar"><a class="brand" href="${ROOT}index.html" aria-label="LaCADIAN Environmental Intelligence home"><span class="mark" aria-hidden="true"></span><span class="brandtext"><span class="name">LaCADIAN Environmental Intelligence</span><span class="name2">LAND · WATER · CLIMATE INTELLIGENCE</span></span></a>
        <nav class="nav" aria-label="Pages">${NAV.map(([t, u]) => `<a href="${ROOT}${u}"${t === PAGE ? ' aria-current="page"' : ""}>${esc(t)}</a>`).join("")}</nav>
        <form class="hsearch" role="search" onsubmit="return false"><input type="search" id="hs" name="lc-search" list="hs-list" autocomplete="off" spellcheck="false" placeholder="Search parish or layer…" aria-label="Search parish or layer"><datalist id="hs-list"></datalist></form></div>
        <div class="proto"><div class="wrap"><strong>Unofficial prototype for review.</strong> Built from public data by a graduate student. It has not been reviewed or approved by the LaCADIAN network team and must not be used for farm decisions.</div></div>`;
      const box = document.getElementById("hs");
      let index = null;
      const load = () => index || (index = Promise.all([getData("data/parishes.geojson"), getData("data/layers.json")]).then(([gj, man]) => {
        const items = [];
        gj.features.forEach(f => items.push({ text: f.properties.name + " Parish", url: ROOT + "pages/parish.html#" + f.properties.id }));
        man.layers.filter(l => l.built).forEach(l => items.push({ text: l.label + " (layer)", url: ROOT + "index.html#layer=" + l.key }));
        document.getElementById("hs-list").innerHTML = items.map(i => `<option value="${esc(i.text)}">`).join("");
        return items;
      }).catch(() => []));
      box.addEventListener("focus", load);
      box.addEventListener("change", () => load().then(items => {
        const q = box.value.trim().toLowerCase();
        const hit = items.find(i => i.text.toLowerCase() === q) || items.find(i => i.text.toLowerCase().startsWith(q) && q.length > 1);
        if (hit) location.href = hit.url;
      }));
    }
    const f = document.getElementById("ftr");
    if (f) {
      f.className = "foot";
      f.innerHTML = `<div class="wrap"><p>Station data: LaCADIAN network (Louisiana Climate &amp; Digital Ag Network), LSU Soil Hydrology and Remote Sensing (SHaRE) Lab; stated as CC BY-NC 4.0, for academic and non-commercial use.
        Satellite and gridded layers: NASA, USDA, FEMA, JRC and University of Idaho sources, credited on each map. Parish boundaries: US Census Bureau.
        Basemap: Esri, HERE, Garmin, OpenStreetMap contributors.</p>
        <p><a href="${ROOT}pages/methods.html">Data and methods</a> · <a href="${ROOT}pages/about.html">About this prototype</a></p></div>`;
    }
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function niceDate(iso) {
    if (!iso) return "n/a";
    const p = String(iso).slice(0, 10).split("-");
    return parseInt(p[2], 10) + " " + MONTHS[parseInt(p[1], 10) - 1] + " " + p[0];
  }
  function csvQuote(v) { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function saveText(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type || "text/csv" }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  window.LC = { ROOT, PAGE, esc, getData, niceDate, csvQuote, saveText, el, MONTHS };
  document.addEventListener("DOMContentLoaded", frame);
})();
