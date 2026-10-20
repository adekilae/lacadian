// LaCADIAN - the parish map application. One page of the site shows the layers listed for it in data/layers.json.
// A page sets <html data-pagekey="drought"> and contains <div id="app"></div>.
(function () {
  "use strict";
  const { esc, getData, niceDate, csvQuote, saveText } = LC;
  const PAGEKEY = document.documentElement.dataset.pagekey;
  const $ = id => document.getElementById(id);

  $("app").innerHTML = `
    <nav class="tabs" aria-label="Layers" id="tabs"></nav>
    <div class="grp" id="grpwrap" hidden><label for="grp" id="grplab"></label><select id="grp"></select></div>
    <div class="grid">
      <div class="card mapcol">
        <div id="status" class="status"></div>
        <h2 id="title">Loading…</h2>
        <p class="sub" id="subtitle"></p>
        <div class="mapbox"><div id="map" role="application" aria-label="Map of Louisiana parishes"></div>
          <div class="maptoggle seg" role="group" aria-label="Background"><button type="button" id="bm-map" aria-pressed="true">Map</button><button type="button" id="bm-sat" aria-pressed="false">Satellite</button></div></div>
        <ul class="legend" id="legend"></ul>
        <ul class="lnotes" id="lnotes"></ul>
        <div class="btns">
          <button class="btn" id="download-img" type="button">Download map image (PNG)</button>
          <button class="btn" id="download" type="button">Download this map (CSV)</button>
        </div>
        <p class="sub" style="margin:12px 0 4px"><strong>Cite this map</strong></p>
        <p class="sub cite" id="cite"></p>
        <button class="btn" id="cite-copy" type="button">Copy citation</button>
      </div>
      <aside>
        <div class="card">
          <input type="search" id="search" name="lc-parish" autocomplete="off" spellcheck="false" list="names" placeholder="Find a parish…" aria-label="Find a parish">
          <datalist id="names"></datalist>
          <div id="detail"></div>
        </div>
        <div class="card rank-card" id="rankcard" hidden>
          <h2>Ranking</h2>
          <div class="seg" role="group" aria-label="Ranking order"><button type="button" id="rk-hi" aria-pressed="true">Highest 10</button><button type="button" id="rk-lo" aria-pressed="false">Lowest 10</button></div>
          <ol class="rank" id="rank"></ol>
          <p class="sub" id="rank-note"></p>
        </div>
      </aside>
    </div>
    <section class="card notes">
      <h2>How to read this map</h2><p id="how"></p>
      <h2>Limits</h2><ul id="limits"></ul>
      <h2>Credits</h2><ul id="credits"></ul>
    </section>
    <section class="card notes" id="validation" hidden></section>`;

  const EMPTY = '<p class="sub" style="margin:0">Click a parish on the map, or search for one, to see its numbers.</p>';
  $("detail").innerHTML = EMPTY;

  // ---------------------------------------------------------------- the map
  const map = L.map("map", { zoomSnap: 0.25, attributionControl: false, scrollWheelZoom: false });
  const street = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 12, maxNativeZoom: 10, opacity: 0.9 }).addTo(map);
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 12 });
  L.control.attribution({ prefix: false }).addAttribution("Basemap and imagery: Esri, HERE, Garmin, Maxar, OpenStreetMap contributors").addTo(map);
  let SAT = false;
  function basemap(on) {
    SAT = on;
    if (on) { map.removeLayer(street); sat.addTo(map); } else { map.removeLayer(sat); street.addTo(map); }
    $("bm-map").setAttribute("aria-pressed", !on); $("bm-sat").setAttribute("aria-pressed", on);
    restyle();
  }
  $("bm-map").addEventListener("click", () => basemap(false));
  $("bm-sat").addEventListener("click", () => basemap(true));

  let geo = null, shapes = {}, D = null, selected = null, rankHigh = true, color = {}, label = {};
  let MANIFEST = null, LAYERS = [], chosen = {};            // chosen: last layer shown in each group

  function styleFor(id) {
    const p = D && D.parishes[id];
    const c = p ? color[p.cat] || "#bdbdbd" : "#d9d9d9";
    return { fillColor: c, fillOpacity: SAT ? 0.6 : 0.92, color: id === selected ? "#111" : (SAT ? "#fff" : "#55605c"), weight: id === selected ? 3 : 0.7 };
  }
  function restyle() {
    if (!geo) return;
    Object.entries(shapes).forEach(([id, l]) => { l.setStyle(styleFor(id)); if (id === selected) l.bringToFront(); });
  }

  // ---------------------------------------------------------------- tabs
  function drawTabs(activeKey) {
    const items = [], seen = new Set();
    LAYERS.forEach(l => {
      if (l.group) {
        if (seen.has(l.group)) return;
        seen.add(l.group);
        const members = LAYERS.filter(x => x.group === l.group);
        const keep = chosen[l.group] && members.some(x => x.key === chosen[l.group]) ? chosen[l.group] : (members.find(x => x.built) || members[0]).key;
        items.push({ key: keep, group: l.group, text: l.group_tab, built: members.some(x => x.built), active: members.some(x => x.key === activeKey) });
      } else items.push({ key: l.key, text: l.label, built: l.built, active: l.key === activeKey });
    });
    $("tabs").innerHTML = items.map(i => `<button type="button" data-key="${esc(i.key)}" ${i.active ? 'aria-current="true"' : ""}${i.built ? "" : ' class="off" title="Not built yet"'}>${esc(i.text)}</button>`).join("");
    const act = LAYERS.find(l => l.key === activeKey);
    const g = act && act.group;
    $("grpwrap").hidden = !g;
    if (g) {
      chosen[g] = activeKey;
      $("grplab").textContent = act.group_label;
      $("grp").innerHTML = LAYERS.filter(l => l.group === g).map(l => `<option value="${esc(l.key)}"${l.built ? "" : " disabled"}>${esc(l.label)}${l.built ? "" : " (not built yet)"}</option>`).join("");
      $("grp").value = activeKey;
    }
  }
  $("tabs").addEventListener("click", e => { const b = e.target.closest("button"); if (b) show(b.dataset.key); });
  $("grp").addEventListener("change", e => show(e.target.value));

  // ---------------------------------------------------------------- showing a layer
  const cache = {};
  function show(key) {
    const l = LAYERS.find(x => x.key === key) || LAYERS.find(x => x.built) || LAYERS[0];
    if (!l) { $("title").textContent = "No layers for this page yet"; return; }
    history.replaceState(null, "", "#" + l.key);
    drawTabs(l.key);
    if (!l.built) return notBuilt(l);
    (cache[l.key] ? Promise.resolve(cache[l.key]) : getData(l.file).then(d => (cache[l.key] = d)))
      .then(d => render(d))
      .catch(() => notBuilt(l, true));
  }
  function notBuilt(l, failed) {
    D = null;
    $("title").textContent = l.label;
    $("subtitle").textContent = "";
    $("status").innerHTML = "";
    $("legend").innerHTML = ""; $("lnotes").innerHTML = "";
    $("how").textContent = failed ? "This layer's data file could not be loaded." : "This layer has not been built yet. It appears here after the next successful update of the site's data.";
    $("limits").innerHTML = ""; $("credits").innerHTML = ""; $("validation").hidden = true; $("rankcard").hidden = true;
    $("cite").textContent = "";
    restyle();
    $("detail").innerHTML = EMPTY;
  }

  function render(d) {
    D = d;
    color = {}; label = {};
    d.categories.forEach(c => { color[c.key] = c.color; label[c.key] = c.label; });
    $("title").textContent = d.title;
    $("subtitle").textContent = d.subtitle || "";
    $("status").innerHTML = `<span class="pill">Updated ${esc(niceDate(d.updated))}</span>` + (d.demo ? ' <span class="pill warn">Demo data</span>' : "");
    $("legend").innerHTML = d.categories.filter(c => (d.counts[c.key] || 0) > 0 || !/^(not_rated|none|cloud|few)$/.test(c.key)).map(c =>
      `<li><span class="sw" style="background:${esc(c.color)}"></span><span class="lt"><b>${esc(c.label)}</b>${c.note ? ` <span class="n">${esc(c.note)}</span>` : ""}</span><span class="cnt">${d.counts[c.key] || 0}</span></li>`).join("");
    $("lnotes").innerHTML = (d.legend_notes || []).map(t => `<li>${esc(t)}</li>`).join("");
    $("how").textContent = d.how || "";
    $("limits").innerHTML = (d.limits || []).map(t => `<li>${esc(t)}</li>`).join("");
    $("credits").innerHTML = (d.credits || []).map(c => `<li>${c.url ? `<a href="${esc(c.url)}" rel="noopener">${esc(c.text)}</a>` : esc(c.text)}</li>`).join("");
    $("cite").textContent = `LaCADIAN (unofficial prototype), ${new Date(d.updated).getFullYear()}. ${d.title}: ${d.subtitle || ""}. Source: ${d.source}. Updated ${d.updated}.`;
    $("names").innerHTML = Object.values(d.parishes).map(p => `<option value="${esc(p.name)}">`).join("");
    restyle();
    ranking();
    if (selected && d.parishes[selected]) showDetail(selected); else { selected = null; $("detail").innerHTML = EMPTY; }
    validationBlock(d);
  }

  // ---------------------------------------------------------------- parish details
  const parishName = p => p.name.includes("Parish") ? p.name : p.name + " Parish";
  function select(id) {
    selected = id;
    restyle();
    if (D && D.parishes[id]) showDetail(id);
  }
  function focusOn(id) { select(id); if (shapes[id]) map.fitBounds(shapes[id].getBounds().pad(1.5)); }
  function showDetail(id) {
    const p = D.parishes[id];
    const c = color[p.cat] || "#bdbdbd";
    let h = `<h3 class="pname">${esc(parishName(p))}</h3>
      <p class="big"><span class="chip" style="background:${esc(c)}"></span>${esc(p.big)}</p><p class="sub">${esc(p.big_note || "")}</p>
      <p class="sub"><b>${esc(label[p.cat] || "")}</b></p>`;
    if (p.rows && p.rows.length) h += `<dl class="kv">${p.rows.map(r => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl>`;
    if (p.table) h += tableHtml(p.table);
    $("detail").innerHTML = h;
    const ch = chartSvg(D.chart, p);
    if (ch) { const box = document.createElement("div"); box.className = "chart"; box.innerHTML = `<p><b>${esc(D.chart.caption || "")}</b></p>`; box.appendChild(ch); $("detail").appendChild(box); }
  }
  function tableHtml(t) {
    return `<div class="ptable"><p><b>${esc(t.caption || "")}</b></p><table><thead><tr>${t.head.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${
      t.rows.map(r => `<tr>${r.map((x, i) => `<td${i ? ' class="r"' : ""}>${esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>${t.note ? `<p class="sub">${esc(t.note)}</p>` : ""}</div>`;
  }

  // ---------------------------------------------------------------- charts (SVG)
  const NS = "http://www.w3.org/2000/svg";
  const sv = (n, a) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
  function chartSvg(c, p) {
    if (!c || !p.v || !p.v.length) return null;
    const W = 320, H = 150, L = 6, R = 6, T = 14, B = 30, n = p.v.length, bw = (W - L - R) / n;
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": c.caption || "chart" });
    const txt = (x, y, s, anchor, extra) => { const t = sv("text", Object.assign({ x, y, "text-anchor": anchor || "middle" }, extra || {})); t.textContent = s; svg.appendChild(t); };
    const rotate = n > 8 || c.x.some(x => String(x).length > 6);
    const lab = (i, y) => {
      const x = L + i * bw + bw / 2;
      if (rotate) txt(x, y, String(c.x[i]), "end", { transform: `rotate(-40 ${x} ${y})` });
      else txt(x, y, String(c.x[i]), "middle");
    };
    if (c.kind === "diverging") {
      const mid = T + (H - T - B) / 2, half = (H - T - B) / 2, cap = c.cap || 50;
      svg.appendChild(sv("line", { x1: L, x2: W - R, y1: mid, y2: mid, stroke: "#8a948f", "stroke-width": 1 }));
      p.v.forEach((v, i) => {
        if (v == null) { svg.appendChild(sv("rect", { x: L + i * bw + 2, y: mid - 1, width: bw - 4, height: 2, fill: "#bdbdbd" })); }
        else {
          const hgt = Math.min(Math.abs(v) / cap, 1) * half;
          svg.appendChild(sv("rect", { x: L + i * bw + 2, y: v >= 0 ? mid - hgt : mid, width: bw - 4, height: Math.max(hgt, 1), fill: color[(p.c || [])[i]] || "#999", stroke: "#55605c", "stroke-width": 0.4 }));
        }
        lab(i, H - B + 11);
      });
      if (c.top) txt(L, T - 3, "↑ " + c.top, "start");
      if (c.bottom) txt(L, H - 2, "↓ " + c.bottom, "start");
    } else {
      const top = Math.max(1e-9, Math.max.apply(null, p.v.filter(x => x != null).concat([0])));
      const base = H - B, usable = base - T - 10;
      svg.appendChild(sv("line", { x1: L, x2: W - R, y1: base, y2: base, stroke: "#8a948f", "stroke-width": 1 }));
      p.v.forEach((v, i) => {
        if (v != null) {
          const hgt = v / top * usable;
          svg.appendChild(sv("rect", { x: L + i * bw + 3, y: base - hgt, width: bw - 6, height: Math.max(hgt, 0.5), fill: (p.bc || [])[i] || "#2D6A4F" }));
          if (n <= 12) txt(L + i * bw + bw / 2, base - hgt - 3, v >= 1000 ? Math.round(v).toLocaleString() : (Math.abs(v) < 10 && v % 1 ? v.toFixed(1) : String(Math.round(v * 10) / 10)), "middle", { class: "val" });
        }
        lab(i, base + 11);
      });
      if (c.unit) txt(W - R, T - 3, c.unit, "end");
    }
    return svg;
  }

  // ---------------------------------------------------------------- ranking
  function ranking() {
    const has = D && D.rank && Object.values(D.parishes).some(p => p.rv != null);
    $("rankcard").hidden = !has;
    if (!has) return;
    $("rk-hi").textContent = D.rank.high ? "Highest 10" : "Highest 10"; $("rk-lo").textContent = "Lowest 10";
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
  $("search").addEventListener("change", e => {
    const q = e.target.value.trim().toLowerCase().replace(/ parish$/, "");
    if (!D) return;
    const id = Object.keys(D.parishes).find(k => D.parishes[k].name.toLowerCase() === q);
    if (id) focusOn(id);
  });

  // ---------------------------------------------------------------- downloads
  $("download").addEventListener("click", () => {
    if (!D) return;
    const labels = [];
    Object.values(D.parishes).forEach(p => (p.rows || []).forEach(r => { if (!labels.includes(r[0])) labels.push(r[0]); }));
    const lines = [["Parish FIPS", "Parish", "Class", "Main figure", "Note"].concat(labels).map(csvQuote).join(",")];
    Object.entries(D.parishes).forEach(([id, p]) => {
      const m = Object.fromEntries((p.rows || []).map(r => [r[0], r[1]]));
      lines.push([id, p.name, label[p.cat] || "", p.big, p.big_note || ""].concat(labels.map(l => m[l] == null ? "" : m[l])).map(csvQuote).join(","));
    });
    lines.push("", csvQuote(`LaCADIAN (unofficial prototype). ${D.title}. Source: ${D.source}. Updated ${D.updated}. Not for farm decisions.`));
    saveText(`lacadian-${D.key}-${D.updated}.csv`, lines.join("\n"));
  });
  $("cite-copy").addEventListener("click", () => {
    const done = () => { $("cite-copy").textContent = "Copied"; setTimeout(() => $("cite-copy").textContent = "Copy citation", 1500); };
    (navigator.clipboard ? navigator.clipboard.writeText($("cite").textContent) : Promise.reject()).then(done).catch(() => {
      const r = document.createRange(); r.selectNodeContents($("cite")); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    });
  });
  $("download-img").addEventListener("click", () => {
    if (!D || !geo) return;
    const polys = [];
    geo.eachLayer(l => { const f = l.feature; (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates).forEach(poly => polys.push([f.properties.id, poly])); });
    let w = 1e9, e = -1e9, s = 1e9, n = -1e9;
    polys.forEach(([, poly]) => poly[0].forEach(([x, y]) => { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }));
    const k = Math.cos((s + n) / 2 * Math.PI / 180), mw = 1500, sc = mw / ((e - w) * k), mh = Math.round((n - s) * sc);
    const cats = D.categories.filter(c => (D.counts[c.key] || 0) > 0);
    const top = 190, legendH = 70 + cats.length * 46, foot = 150, W = mw + 160, H = top + Math.max(mh, legendH) + foot;
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H; const g = cv.getContext("2d");
    const SANS = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif";
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#1d2a26"; g.font = `700 54px ${SANS}`; g.fillText(D.title, 80, 90, W - 160);
    g.fillStyle = "#5a6a64"; g.font = `34px ${SANS}`; g.fillText(D.subtitle || "", 80, 145, W - 160);
    polys.forEach(([id, poly]) => {
      g.beginPath();
      poly.forEach(ring => ring.forEach(([x, y], i) => { const px = 80 + (x - w) * k * sc, py = top + (n - y) * sc; i ? g.lineTo(px, py) : g.moveTo(px, py); }));
      const p = D.parishes[id]; g.fillStyle = p ? color[p.cat] || "#ccc" : "#ccc"; g.fill("evenodd"); g.strokeStyle = "#55605c"; g.lineWidth = 1.2; g.stroke();
    });
    let ly = top + 20; g.font = `600 32px ${SANS}`;
    cats.forEach(c => { g.fillStyle = c.color; g.fillRect(W - 640, ly, 34, 34); g.strokeStyle = "#555"; g.strokeRect(W - 640, ly, 34, 34); g.fillStyle = "#1d2a26"; g.fillText(`${c.label} (${D.counts[c.key]})`, W - 590, ly + 27, 520); ly += 46; });
    g.fillStyle = "#5a6a64"; g.font = `28px ${SANS}`;
    g.fillText(`Source: ${D.source}. Updated ${D.updated}.`, 80, H - 90, W - 160);
    g.fillText("LaCADIAN (unofficial prototype, not approved by the network team). Not for farm decisions. Boundaries: US Census Bureau.", 80, H - 45, W - 160);
    const a = document.createElement("a"); a.href = cv.toDataURL("image/png"); a.download = `lacadian-${D.key}-${D.updated}.png`; document.body.appendChild(a); a.click(); a.remove();
  });

  // ---------------------------------------------------------------- the check against the stations
  let VAL = undefined;
  function validationBlock(d) {
    const box = $("validation");
    if (!d.validation) { box.hidden = true; return; }
    box.hidden = false;
    const kind = d.validation;
    const fill = v => {
      const blk = v && v[kind];
      const f = (x, dec) => x == null ? "n/a" : Number(x).toFixed(dec == null ? 2 : dec);
      let h = `<h2>Check against the LaCADIAN stations</h2>`;
      if (!blk) { box.innerHTML = h + "<p>The check has not been run yet. It needs the rainfall and soil moisture records and the station data; it appears after the next full update.</p>"; return; }
      const P = blk.pooled;
      if (kind === "rain") {
        h += `<p>${esc(blk.source)}. Each row compares the two on the days both have a value. A correlation of 1 means they rise and fall together; 0 means no relation. The ratio is the grid's rain total divided by the gauge's.</p>`;
        h += `<p><b>${P.stations} stations</b> had enough days. Median correlation of daily rain: <b>${f(P.median_r_daily)}</b>; of weekly totals: <b>${f(P.median_r_week)}</b>; median grid-to-gauge ratio: <b>${f(P.median_ratio)}</b>; both agree on whether it rained on <b>${P.median_agree == null ? "n/a" : Math.round(P.median_agree * 100) + "%"}</b> of days (median).</p>`;
        h += `<div class="scroll"><table><thead><tr><th>Station</th><th>Parish</th><th>Days compared</th><th>Daily correlation</th><th>Weekly correlation</th><th>Grid ÷ gauge</th><th>Agree rain / no rain</th></tr></thead><tbody>` +
          blk.stations.map(s => s.r_daily == null && s.n < 30 ? `<tr><td>${esc(s.name)}</td><td>${esc(s.parish)}</td><td class="r">${s.n}</td><td colspan="4">too few days</td></tr>` :
            `<tr><td>${esc(s.name)}</td><td>${esc(s.parish)}</td><td class="r">${s.n}</td><td class="r">${f(s.r_daily)}</td><td class="r">${f(s.r_week)}</td><td class="r">${f(s.ratio)}</td><td class="r">${s.agree == null ? "n/a" : Math.round(s.agree * 100) + "%"}</td></tr>`).join("") + `</tbody></table></div>`;
        h += `<p class="sub">The gauge is a point; the grid cell averages about 16 km². Differences in timing (the day is cut at different hours) lower the daily correlation more than the weekly one. A few stations have short records.</p>`;
      } else {
        h += `<p>${esc(blk.source)}. The rank correlation says whether the satellite and the sensors move together (1 = always, 0 = unrelated, negative = opposite). The difference is SMAP minus the sensors; sensors and satellite do not read the same level.</p>`;
        h += `<p><b>${P.stations} stations</b> had enough days. Median rank correlation, root zone: <b>${f(P.median_rho_root)}</b>; surface: <b>${f(P.median_rho_surf)}</b>; median difference in the root zone: <b>${f(P.median_bias_root, 3)} m³/m³</b>.</p>`;
        h += `<div class="scroll"><table><thead><tr><th>Station</th><th>Parish</th><th>Days (root zone)</th><th>Root-zone correlation</th><th>Surface correlation</th><th>Difference (SMAP − sensors)</th></tr></thead><tbody>` +
          blk.stations.map(s => s.rho_root == null ? `<tr><td>${esc(s.name)}</td><td>${esc(s.parish)}</td><td class="r">${s.n_root}</td><td colspan="3">too few days</td></tr>` :
            `<tr><td>${esc(s.name)}</td><td>${esc(s.parish)}</td><td class="r">${s.n_root}</td><td class="r">${f(s.rho_root)}</td><td class="r">${f(s.rho_surf)}</td><td class="r">${f(s.bias_root, 3)}</td></tr>`).join("") + `</tbody></table></div>`;
        h += `<p class="sub">SMAP is sampled about every five days and the stations have 6 to 21 months of record, so each row rests on few days. A 9 km cell is compared with one sensor profile. Treat this as a first check, not proof.</p>`;
      }
      box.innerHTML = h;
    };
    if (VAL !== undefined) return fill(VAL);
    getData("data/validation.json").then(v => { VAL = v; fill(v); }).catch(() => { VAL = null; fill(null); });
  }

  // ---------------------------------------------------------------- start
  Promise.all([getData("data/parishes.geojson"), getData("data/layers.json")]).then(([gj, man]) => {
    MANIFEST = man;
    LAYERS = man.layers.filter(l => l.page === PAGEKEY);
    geo = L.geoJSON(gj, {
      style: f => styleFor(f.properties.id),
      onEachFeature: (f, l) => {
        shapes[f.properties.id] = l;
        l.bindTooltip(() => { const p = D && D.parishes[f.properties.id]; return esc(f.properties.name) + " Parish" + (p ? "<br><b>" + esc(p.tip || p.big) + "</b>" : ""); }, { sticky: true });
        l.on("click", () => select(f.properties.id));
      },
    }).addTo(map);
    map.fitBounds(geo.getBounds(), { padding: [8, 8] });
    map.setMaxBounds(geo.getBounds().pad(0.5));
    map.setMinZoom(map.getZoom() - 0.5);
    show(location.hash.slice(1));
  }).catch(e => { $("title").textContent = "Could not load the data files"; $("subtitle").textContent = e.message; });
})();
