// LaCADIAN Environmental Intelligence - the map dashboard (home page).
// Reads data/layers.json (which layers exist) and data/<layer>.json (one file per layer). Nothing is hard-wired to values.
(function () {
  "use strict";
  const { esc, getData, niceDate, saveText } = LC;
  const CH = LC.charts;
  const $ = id => document.getElementById(id);

  // Layer sidebar: groups, and layers that are planned but not built (shown greyed out, never as data).
  const CROPS = ["crops", "crop_rice", "crop_cane", "crop_soy", "crop_corn", "crop_cotton", "crop_sweetpotato", "crop_wheat", "crop_pasture", "crop_aqua"];
  const SOILP = ["soilph", "soilom", "soilclay", "soilsand", "soilbd", "soildrain"];
  const CATS = [
    { id: "c1", title: "Climate & weather", items: [{ k: "rain" }, { k: "dryspell" }, { p: "Air temperature anomaly" }, { p: "Evaporative demand (ET₀)" }] },
    { id: "c2", title: "Soil & hydrology", items: [{ k: "soil" }, { p: "Surface soil moisture (0–5 cm)" }, { p: "Root-zone model (pCC)" }, { p: "Soil-water deficit" }] },
    { id: "c3", title: "Drought", items: [{ k: "usdm" }, { p: "Drought onset and recovery" }, { p: "Surface–root-zone drought gap" }] },
    { id: "c4", title: "Agriculture & vegetation", items: [{ k: "cropland" }, { k: "vegetation" }, { sub: "Crops", keys: CROPS }, { sub: "Soil properties", keys: SOILP }, { p: "Crop water stress" }] },
    { id: "c5", title: "Water & flooding", items: [{ k: "flood" }, { k: "water" }, { p: "River and streamflow" }, { p: "Rainfall recharge effectiveness" }] },
    { id: "c6", title: "Land & coastal", items: [{ p: "Land-cover change" }, { p: "Wetland and coastal vegetation change" }, { p: "Coastal salinity stress" }] },
  ];
  const TABS = [
    ["Overview", ["rain", "soil", "usdm", "dryspell", "vegetation", "flood", "water", "cropland"]],
    ["Climate", ["rain", "dryspell"]],
    ["Soil & drought", ["soil", "usdm"].concat(SOILP)],
    ["Agriculture", ["cropland", "vegetation"].concat(CROPS)],
    ["Water", ["flood", "water"]],
  ];
  const PLAIN = ["rain", "soil", "usdm", "dryspell", "vegetation", "flood", "water"];

  const app = $("app");
  app.innerHTML = `
    <section class="ribbon" id="ribbon" aria-label="Statewide summary"></section>
    <div class="dash">
      <aside class="card side" aria-label="Map layers">
        <h2>Map layers</h2>
        <div id="cats"></div>
        <div class="sidectl">
          <label><input type="checkbox" id="stn"> Show LaCADIAN stations</label>
          <label for="opa">Layer opacity <input type="range" id="opa" min="30" max="100" value="90"> <span id="opav">90%</span></label>
          <button class="btn" id="reset" type="button">Reset layers</button>
        </div>
      </aside>
      <div class="centre">
        <div class="card mapcard">
          <div class="status" id="status"></div>
          <h2 class="maptitle" id="title">Loading…</h2>
          <p class="sub" id="subtitle"></p>
          <div class="mapbox"><div id="map" role="application" aria-label="Map of Louisiana parishes"></div>
            <div class="maptoggle seg" role="group" aria-label="Background"><button type="button" id="bm-map" aria-pressed="true">Map</button><button type="button" id="bm-sat" aria-pressed="false">Satellite</button></div></div>
          <ul class="lnotes" id="lnotes"></ul>
          <div class="btns">
            <button class="btn" id="download-img" type="button">Download map image (PNG)</button>
            <button class="btn" id="download" type="button">Download this map (CSV)</button>
            <button class="btn" id="cite-copy" type="button">Copy citation</button>
          </div>
          <p class="sub cite" id="cite" style="margin:10px 0 0"></p>
        </div>
        <div class="card" id="rankcard" hidden style="margin-top:14px">
          <div class="cardhead"><h2>Ranking</h2><div class="seg" role="group" aria-label="Ranking order"><button type="button" id="rk-hi" aria-pressed="true">Highest 10</button><button type="button" id="rk-lo" aria-pressed="false">Lowest 10</button></div></div>
          <ol class="rank" id="rank"></ol><p class="sub" id="rank-note"></p>
        </div>
      </div>
      <aside class="card pinfo" id="pinfo" aria-live="polite"></aside>
    </div>
    <div class="bottom">
      <section class="card"><div class="cardhead"><h2>Time series</h2></div><select id="tsSel" aria-label="Layer for the time series"></select><div id="tsBody"></div></section>
      <section class="card"><div class="cardhead"><h2>Compare parishes</h2></div>
        <select id="cmpA" aria-label="First parish"></select><div style="height:6px"></div><select id="cmpB" aria-label="Second parish"></select><div class="cmp" id="cmpBody"></div></section>
      <section class="card"><div class="cardhead"><h2>Related layers</h2></div><div class="rel" id="relBody"></div></section>
      <section class="card"><div class="cardhead"><h2>Download data</h2></div>
        <div class="fld"><label for="dlLayer">Layer</label><select id="dlLayer"></select></div>
        <div class="fld"><label for="dlFmt">Format</label><select id="dlFmt"><option value="csv">CSV (table)</option><option value="json">JSON (full layer)</option></select></div>
        <div class="fld"><label>Area</label><span>Louisiana, all 64 parishes</span></div>
        <div class="fld"><label>Period</label><span>Latest update (<span id="dlDate">n/a</span>)</span></div>
        <button class="btn primary" id="dlGo" type="button" style="width:100%;margin-top:6px">Download data</button></section>
    </div>
    <section class="card notes"><h2>How to read this map</h2><p id="how"></p><h2>Limits</h2><ul id="limits"></ul><h2>Credits</h2><ul id="credits"></ul></section>
    <section class="card notes" id="validation" hidden></section>`;

  // ------------------------------------------------------------ state
  let MAN, GJ, DATA = {}, cur = null, sel = null, tab = 0, tsKey = null, cmpA = "", cmpB = "", rankHigh = true;
  let STN = null, stnGroup = null, SAT = false, VAL;
  const PROMISES = {};
  const shapes = {};
  let geo, map, legendCtl;
  const layerMeta = k => MAN.layers.find(l => l.key === k);
  const catOf = k => { const c = CATS.find(c => c.items.some(i => i.k === k || (i.keys && i.keys.includes(k)))); return c ? c.id : null; };
  const nameOf = id => { const f = GJ.features.find(f => f.properties.id === id); return f ? f.properties.name : id; };
  const opacity = () => (+$("opa").value / 100) * (SAT ? 0.8 : 1);

  function load(key) {
    const m = layerMeta(key);
    if (!m || !m.built) return Promise.reject(new Error("not built"));
    return PROMISES[key] || (PROMISES[key] = getData(m.file).then(d => (DATA[key] = d)));
  }

  // ------------------------------------------------------------ sidebar
  function layerHtml(k) {
    const m = layerMeta(k);
    if (!m) return "";
    if (!m.built) return `<div class="lay off"><input type="radio" disabled aria-label="${esc(m.label)}"><span>${esc(m.label)}</span><span class="tag">Not built yet</span></div>`;
    return `<label class="lay"><input type="radio" name="layer" value="${esc(k)}"><span>${esc(m.label)}</span></label>`;
  }
  function sideHtml() {
    return CATS.map(c => {
      let total = 0, built = 0;
      const body = c.items.map(i => {
        if (i.p) { total++; return `<div class="lay off"><input type="radio" disabled aria-label="${esc(i.p)}"><span>${esc(i.p)}</span><span class="tag">Planned</span></div>`; }
        if (i.sub) {
          const ks = i.keys.filter(layerMeta);
          ks.forEach(k => { total++; if (layerMeta(k).built) built++; });
          return `<details class="sub"><summary>${esc(i.sub)} (${ks.length})</summary>${ks.map(layerHtml).join("")}</details>`;
        }
        if (!layerMeta(i.k)) return "";
        total++; if (layerMeta(i.k).built) built++;
        return layerHtml(i.k);
      }).join("");
      return `<details class="cat" data-c="${c.id}"><summary><span class="ci ${c.id}"></span>${esc(c.title)} <span class="ct">(${built}/${total})</span></summary><div class="catbody">${body}</div></details>`;
    }).join("");
  }
  function markSide() {
    const r = document.querySelector(`#cats input[value="${cur}"]`);
    document.querySelectorAll("#cats input").forEach(i => { i.checked = false; });
    if (r) { r.checked = true; for (let d = r.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true; }
  }

  // ------------------------------------------------------------ map
  function styleFor(id) {
    const D = DATA[cur], p = D && D.parishes[id], col = p ? (CH.maps(D).color[p.cat] || "#bdbdbd") : "#d9d9d9";
    return { fillColor: col, fillOpacity: opacity(), color: id === sel ? "#111" : (SAT ? "#fff" : "#55605c"), weight: id === sel ? 3 : 0.7 };
  }
  function restyle() { Object.entries(shapes).forEach(([id, l]) => { l.setStyle(styleFor(id)); if (id === sel) l.bringToFront(); }); }
  function basemap(on) {
    SAT = on;
    if (on) { map.removeLayer(street); sat.addTo(map); } else { map.removeLayer(sat); street.addTo(map); }
    $("bm-map").setAttribute("aria-pressed", !on); $("bm-sat").setAttribute("aria-pressed", on);
    restyle();
  }
  let street, sat;
  function buildMap() {
    map = L.map("map", { zoomSnap: 0.25, attributionControl: false, scrollWheelZoom: false });
    street = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 12, maxNativeZoom: 10, opacity: 0.9 }).addTo(map);
    sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 12 });
    L.control.attribution({ prefix: false }).addAttribution("Basemap and imagery: Esri, HERE, Garmin, Maxar, OpenStreetMap contributors").addTo(map);
    geo = L.geoJSON(GJ, {
      style: f => styleFor(f.properties.id),
      onEachFeature: (f, l) => {
        shapes[f.properties.id] = l;
        l.bindTooltip(() => { const p = DATA[cur] && DATA[cur].parishes[f.properties.id]; return esc(f.properties.name) + " Parish" + (p ? "<br><b>" + esc(p.tip || p.big) + "</b>" : ""); }, { sticky: true });
        l.on("click", () => select(f.properties.id));
      },
    }).addTo(map);
    map.fitBounds(geo.getBounds(), { padding: [8, 8] });
    map.setMaxBounds(geo.getBounds().pad(0.5));
    map.setMinZoom(map.getZoom() - 0.5);
    legendCtl = L.control({ position: "bottomleft" });
    legendCtl.onAdd = () => { const d = L.DomUtil.create("div", "lg-ctl"); d.id = "lgctl"; L.DomEvent.disableClickPropagation(d); return d; };
    legendCtl.addTo(map);
    $("bm-map").addEventListener("click", () => basemap(false));
    $("bm-sat").addEventListener("click", () => basemap(true));
  }

  // ------------------------------------------------------------ showing a layer
  function setHash() { history.replaceState(null, "", "#layer=" + cur + (sel ? "&parish=" + sel : "")); }
  function show(key) {
    load(key).then(D => {
      cur = key; render(D); markSide(); setHash();
    }).catch(() => { $("title").textContent = "This layer could not be loaded"; });
  }
  function render(D) {
    const { color } = CH.maps(D);
    $("title").textContent = D.title;
    $("subtitle").textContent = D.subtitle || "";
    $("status").innerHTML = `<span class="pill">Updated ${esc(niceDate(D.updated))}</span>` + (D.demo ? ' <span class="pill warn">Demo data</span>' : "");
    const rows = D.categories.filter(c => (D.counts[c.key] || 0) > 0 || !/^(not_rated|none|cloud|few)$/.test(c.key));
    $("lgctl").innerHTML = `<b class="h">${esc(D.label)}</b>` + rows.map(c => `<div class="row"><span class="sw" style="background:${esc(c.color)}"></span><span>${esc(c.label)}</span><span class="cnt">${D.counts[c.key] || 0}</span></div>`).join("");
    $("lnotes").innerHTML = (D.legend_notes || []).map(t => `<li>${esc(t)}</li>`).join("");
    $("how").textContent = D.how || "";
    $("limits").innerHTML = (D.limits || []).map(t => `<li>${esc(t)}</li>`).join("");
    $("credits").innerHTML = (D.credits || []).map(c => `<li>${c.url ? `<a href="${esc(c.url)}" rel="noopener">${esc(c.text)}</a>` : esc(c.text)}</li>`).join("");
    $("cite").textContent = `LaCADIAN Environmental Intelligence (unofficial prototype), ${new Date(D.updated).getFullYear()}. ${D.title}: ${D.subtitle || ""}. Source: ${D.source}. Updated ${D.updated}.`;
    restyle(); ranking(); validation(D); bottom();
    if (sel) pinfo();
  }

  // ------------------------------------------------------------ selecting a parish
  function select(id) { sel = id || null; restyle(); setHash(); pinfo(); bottom(); }
  function focusOn(id) { select(id); if (shapes[id]) map.fitBounds(shapes[id].getBounds().pad(1.5)); }

  function pinfo() {
    const names = GJ.features.map(f => f.properties).sort((a, b) => a.name.localeCompare(b.name));
    let h = `<h2>Parish information</h2><select id="psel" aria-label="Parish"><option value="">Select a parish…</option>${names.map(p => `<option value="${p.id}"${p.id === sel ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>`;
    if (!sel) {
      h += `<p class="sub" style="margin-top:10px">Click a parish on the map, or choose one above, to see its indicators.</p>`;
    } else {
      const f = GJ.features.find(f => f.properties.id === sel).properties;
      h += `<h3 class="pname">${esc(f.name)} Parish</h3><p class="meta">Land area ${Math.round(f.land_sqmi).toLocaleString()} sq mi · FIPS ${esc(sel)}</p>`;
      h += `<div class="tabs" role="group" aria-label="Indicator group">${TABS.map((t, i) => `<button type="button" data-t="${i}" aria-pressed="${i === tab}">${esc(t[0])}</button>`).join("")}</div>`;
      const keys = TABS[tab][1].filter(k => layerMeta(k) && layerMeta(k).built);
      const items = keys.map(k => {
        const D = DATA[k], p = D && D.parishes[sel];
        if (!D) return `<li data-k="${k}" tabindex="0"><span class="il">${esc(layerMeta(k).label)}</span><span class="iv">…</span></li>`;
        if (!p) return "";
        return `<li data-k="${k}" tabindex="0"><span class="chip" style="background:${esc(CH.maps(D).color[p.cat] || "#bdbdbd")}"></span><span class="il">${esc(D.label)}</span><span class="iv">${esc(p.big)}</span></li>`;
      }).join("");
      h += `<h3>Key indicators</h3>` + (items ? `<ul class="ind">${items}</ul>` : `<p class="sub">No built layers in this group yet.</p>`);
      const plain = PLAIN.filter(k => DATA[k] && DATA[k].parishes[sel]).map(k => {
        const D = DATA[k], p = D.parishes[sel];
        return `<li><b>${esc(D.label)}:</b> ${esc(p.big)}${p.big_note ? ", " + esc(p.big_note) : ""}</li>`;
      }).join("");
      if (plain) h += `<h3>In plain words</h3><ul class="plain">${plain}</ul><p class="sub" style="margin-top:6px">Each line is the value on that layer's map, as measured or mapped. It is not advice.</p>`;
      h += `<p style="margin:12px 0 0"><a class="btn primary" href="pages/parish.html#${esc(sel)}">View full parish report</a></p>`;
      if (DATA[cur] && DATA[cur].parishes[sel]) {
        const D = DATA[cur], p = D.parishes[sel];
        h += `<h3>${esc(D.label)} on the map</h3><p class="big"><span class="chip" style="background:${esc(CH.maps(D).color[p.cat] || "#bdbdbd")}"></span>${esc(p.big)}</p><p class="sub">${esc(p.big_note || "")}</p>`;
        if (p.rows && p.rows.length) h += `<dl class="kv">${p.rows.map(r => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl>`;
        if (p.table) h += CH.tableHtml(p.table);
      }
    }
    $("pinfo").innerHTML = h;
  }
  $("pinfo").addEventListener("change", e => { if (e.target.id === "psel") { if (e.target.value) focusOn(e.target.value); else select(null); } });
  $("pinfo").addEventListener("click", e => {
    const t = e.target.closest("[data-t]"); if (t) { tab = +t.dataset.t; pinfo(); return; }
    const li = e.target.closest("li[data-k]"); if (li) show(li.dataset.k);
  });
  $("pinfo").addEventListener("keydown", e => { const li = e.target.closest("li[data-k]"); if (li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); show(li.dataset.k); } });

  // ------------------------------------------------------------ ranking
  function ranking() {
    const D = DATA[cur];
    const has = D && D.rank && Object.values(D.parishes).some(p => p.rv != null);
    $("rankcard").hidden = !has;
    if (!has) return;
    $("rk-hi").setAttribute("aria-pressed", rankHigh); $("rk-lo").setAttribute("aria-pressed", !rankHigh);
    const list = Object.entries(D.parishes).filter(([, p]) => p.rv != null).sort((a, b) => rankHigh ? b[1].rv - a[1].rv : a[1].rv - b[1].rv).slice(0, 10);
    $("rank").innerHTML = list.map(([id, p], i) => `<li data-id="${esc(id)}" tabindex="0"><span class="rn">${i + 1}</span><span class="rname">${esc(p.name)}</span><span class="rval">${esc(p.big)}</span></li>`).join("");
    $("rank-note").textContent = (rankHigh ? D.rank.high : D.rank.low) + ". " + (D.rank.note || "");
  }
  $("rk-hi").addEventListener("click", () => { rankHigh = true; ranking(); });
  $("rk-lo").addEventListener("click", () => { rankHigh = false; ranking(); });
  const rankPick = e => { const li = e.target.closest("li"); if (li) focusOn(li.dataset.id); };
  $("rank").addEventListener("click", rankPick);
  $("rank").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); rankPick(e); } });

  // ------------------------------------------------------------ bottom cards
  function bottom() { ts(); cmp(); rel(); dl(); }

  function ts() {
    const withChart = Object.keys(DATA).filter(k => DATA[k].chart && Object.values(DATA[k].parishes).some(p => p.v && p.v.length));
    const order = (MAN.layers.map(l => l.key)).filter(k => withChart.includes(k));
    if (!tsKey || !order.includes(tsKey)) tsKey = order.includes(cur) ? cur : order[0];
    else if (order.includes(cur) && tsKey !== cur && ts.follow !== false) tsKey = cur;
    $("tsSel").innerHTML = order.map(k => `<option value="${k}"${k === tsKey ? " selected" : ""}>${esc(DATA[k].label)}</option>`).join("");
    const body = $("tsBody"); body.innerHTML = "";
    if (!tsKey) { body.innerHTML = `<p class="sub">No chart data yet.</p>`; return; }
    if (!sel) { body.innerHTML = `<p class="sub" style="margin-top:8px">Select a parish to see its chart.</p>`; return; }
    const D = DATA[tsKey], p = D.parishes[sel], box = p && CH.chartBox(D, p);
    if (box) { body.appendChild(box); const s = document.createElement("p"); s.className = "sub"; s.textContent = `${D.source}. Updated ${D.updated}.`; body.appendChild(s); }
    else body.innerHTML = `<p class="sub" style="margin-top:8px">No chart for this parish on this layer.</p>`;
  }
  $("tsSel").addEventListener("change", e => { tsKey = e.target.value; ts.follow = false; ts(); });

  function cmp() {
    const names = GJ.features.map(f => f.properties).sort((a, b) => a.name.localeCompare(b.name));
    if (!cmpA) cmpA = sel || "22033";
    if (!cmpB || cmpB === cmpA) cmpB = cmpA === "22055" ? "22033" : "22055";
    if (sel && cmp.lastSel !== sel) { cmpA = sel; cmp.lastSel = sel; if (cmpB === cmpA) cmpB = cmpA === "22055" ? "22033" : "22055"; }
    const opts = v => names.map(p => `<option value="${p.id}"${p.id === v ? " selected" : ""}>${esc(p.name)}</option>`).join("");
    $("cmpA").innerHTML = opts(cmpA); $("cmpB").innerHTML = opts(cmpB);
    const D = DATA[cur], body = $("cmpBody");
    if (!D) { body.innerHTML = ""; return; }
    const mx = Math.max.apply(null, Object.values(D.parishes).map(p => p.rv).filter(v => v != null).concat([0]));
    body.innerHTML = [cmpA, cmpB].map((id, i) => {
      const p = D.parishes[id];
      if (!p) return `<div class="cmprow"><div class="cn">${esc(nameOf(id))}</div><div class="sub">No value on this layer</div></div>`;
      const w = p.rv != null && mx > 0 ? Math.max(2, Math.round(Math.abs(p.rv) / mx * 100)) : 0;
      return `<div class="cmprow"><div class="cn"><span class="chip" style="background:${esc(CH.maps(D).color[p.cat] || "#bdbdbd")}"></span> ${esc(nameOf(id))}: ${esc(p.big)}</div>${w ? `<div class="bar1${i ? " g" : ""}"><i style="width:${w}%"></i></div>` : ""}<div class="sub" style="margin:0">${esc(p.big_note || "")}</div></div>`;
    }).join("") + `<p class="sub">Layer: ${esc(D.label)}.${D.rank ? " Bars are scaled to the highest parish on this layer." : ""}</p>`;
  }
  $("cmpA").addEventListener("change", e => { cmpA = e.target.value; cmp(); });
  $("cmpB").addEventListener("change", e => { cmpB = e.target.value; cmp(); });

  function rel() {
    const c = catOf(cur);
    const loaded = MAN.layers.filter(l => l.built && DATA[l.key] && l.key !== cur);
    const same = loaded.filter(l => catOf(l.key) === c), other = loaded.filter(l => catOf(l.key) !== c);
    const pick = same.concat(other).slice(0, 4);
    $("relBody").innerHTML = pick.length ? pick.map(l => {
      const D = DATA[l.key], p = sel && D.parishes[sel];
      return `<button class="reltile" type="button" data-k="${l.key}"><div class="rt">${esc(l.label)}</div><div class="rv2">${p ? `<span class="chip" style="background:${esc(CH.maps(D).color[p.cat] || "#bdbdbd")}"></span>${esc(p.big)}` : "Open map"}</div></button>`;
    }).join("") : `<p class="sub">Other layers appear here once they are built.</p>`;
  }
  $("relBody").addEventListener("click", e => { const b = e.target.closest("[data-k]"); if (b) show(b.dataset.k); });

  function dl() {
    const built = MAN.layers.filter(l => l.built);
    const keep = $("dlLayer").value || cur;
    $("dlLayer").innerHTML = built.map(l => `<option value="${l.key}"${l.key === keep ? " selected" : ""}>${esc(l.label)}</option>`).join("");
    const m = layerMeta($("dlLayer").value); $("dlDate").textContent = m && m.updated ? niceDate(m.updated) : "n/a";
  }
  $("dlLayer").addEventListener("change", dl);
  $("dlGo").addEventListener("click", () => {
    const k = $("dlLayer").value; if (!k) return;
    load(k).then(D => {
      if ($("dlFmt").value === "json") saveText(`lacadian-${k}-${D.updated}.json`, JSON.stringify(D), "application/json");
      else saveText(`lacadian-${k}-${D.updated}.csv`, CH.csvText(D));
    });
  });

  // ------------------------------------------------------------ station check block
  function validation(D) {
    const box = $("validation");
    if (!D.validation) { box.hidden = true; return; }
    box.hidden = false;
    const fill = v => { box.innerHTML = CH.validationHtml(v, D.validation); };
    if (VAL !== undefined) return fill(VAL);
    getData("data/validation.json").then(v => { VAL = v; fill(v); }).catch(() => { VAL = null; fill(null); });
  }

  // ------------------------------------------------------------ map-side controls
  $("download").addEventListener("click", () => { const D = DATA[cur]; if (D) saveText(`lacadian-${D.key}-${D.updated}.csv`, CH.csvText(D)); });
  $("download-img").addEventListener("click", () => { const D = DATA[cur]; if (D) CH.savePng(D, GJ); });
  $("cite-copy").addEventListener("click", () => {
    const done = () => { $("cite-copy").textContent = "Copied"; setTimeout(() => $("cite-copy").textContent = "Copy citation", 1500); };
    (navigator.clipboard ? navigator.clipboard.writeText($("cite").textContent) : Promise.reject()).then(done).catch(() => {
      const r = document.createRange(); r.selectNodeContents($("cite")); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    });
  });
  $("cats").addEventListener("change", e => { if (e.target.name === "layer") show(e.target.value); });
  $("opa").addEventListener("input", e => { $("opav").textContent = e.target.value + "%"; restyle(); });
  $("stn").addEventListener("change", e => {
    if (!e.target.checked) { if (stnGroup) map.removeLayer(stnGroup); return; }
    (STN ? Promise.resolve(STN) : getData("data/stations.json").then(d => (STN = d))).then(d => {
      if (!stnGroup) {
        stnGroup = L.layerGroup();
        d.stations.forEach(s => L.circleMarker([s.lat, s.lon], { radius: 5.5, weight: 1.6, color: "#fff", fillColor: "#16324F", fillOpacity: 1 })
          .bindTooltip(`${esc(s.name)} (station)<br>Rain, last 7 days: ${s.rain7 == null ? "n/a" : s.rain7.toFixed(1) + " mm"}`).addTo(stnGroup));
      }
      if ($("stn").checked) stnGroup.addTo(map);
    }).catch(() => { $("stn").checked = false; });
  });
  $("reset").addEventListener("click", () => {
    $("stn").checked = false; if (stnGroup) map.removeLayer(stnGroup);
    $("opa").value = 90; $("opav").textContent = "90%"; basemap(false);
    sel = null; tab = 0; show(defaultLayer()); pinfo(); map.fitBounds(geo.getBounds(), { padding: [8, 8] });
  });

  // ------------------------------------------------------------ statewide ribbon
  function tile(cls, ico, title, value, sub) {
    return `<div class="tile"><span class="ico ${cls}" aria-hidden="true">${ico}</span><div><div class="t">${esc(title)}</div><div class="v">${esc(value)}</div><div class="s">${esc(sub)}</div></div></div>`;
  }
  function countOf(D, keys) { return keys.reduce((n, k) => n + (D.counts[k] || 0), 0); }
  function ribbon() {
    const t = [], n = GJ.features.length;
    const R = DATA.rain, S = DATA.soil, U = DATA.usdm;
    t.push(R ? tile("b", "R", "Rainfall below normal", `${countOf(R, ["very_dry", "dry"])} of ${n}`, "parishes, " + (R.subtitle || R.label)) : tile("b", "R", "Rainfall", "–", "not built yet"));
    t.push(S ? tile("a", "S", "Dry root-zone soil", `${countOf(S, ["very_dry", "dry"])} of ${n}`, "parishes, " + (S.subtitle || S.label)) : tile("a", "S", "Soil moisture", "–", "not built yet"));
    t.push(U ? tile("a", "D", "In drought (D1–D4)", `${countOf(U, ["d1", "d2", "d3", "d4"])} of ${n}`, "parishes, " + (U.subtitle || U.label)) : tile("a", "D", "Drought Monitor", "–", "not built yet"));
    t.push(STN ? tile("g", "St", "LaCADIAN stations", String(STN.n), "data through " + niceDate(STN.data_through)) : tile("g", "St", "LaCADIAN stations", "–", "not available"));
    const built = MAN.layers.filter(l => l.built).length;
    t.push(tile("n", "L", "Map layers built", `${built} of ${MAN.layers.length}`, "more are planned"));
    const newest = MAN.layers.map(l => l.updated).filter(Boolean).sort().pop();
    t.push(tile("n", "U", "Last updated", newest ? niceDate(newest) : "n/a", "map layers, daily or monthly"));
    $("ribbon").innerHTML = t.join("");
  }

  // ------------------------------------------------------------ start
  function defaultLayer() { return ["soil", "rain", "usdm"].find(k => layerMeta(k) && layerMeta(k).built) || (MAN.layers.find(l => l.built) || {}).key; }
  Promise.all([getData("data/parishes.geojson"), getData("data/layers.json")]).then(([gj, man]) => {
    GJ = gj; MAN = man;
    $("cats").innerHTML = sideHtml();
    buildMap();
    ribbon(); pinfo();
    const q = new URLSearchParams(location.hash.slice(1).includes("=") ? location.hash.slice(1) : "layer=" + location.hash.slice(1));
    const want = q.get("layer"), p0 = q.get("parish");
    if (p0 && GJ.features.some(f => f.properties.id === p0)) sel = p0;
    const first = want && layerMeta(want) && layerMeta(want).built ? want : defaultLayer();
    if (!first) { $("title").textContent = "No layers have been built yet"; $("how").textContent = "Run the update workflow once; the maps appear here after it finishes."; return; }
    show(first);
    getData("data/stations.json").then(d => { STN = d; ribbon(); }).catch(() => {});
    Promise.allSettled(MAN.layers.filter(l => l.built).map(l => load(l.key))).then(() => { ribbon(); pinfo(); bottom(); });
  }).catch(e => { $("title").textContent = "Could not load the data files"; $("subtitle").textContent = e.message; });
})();
