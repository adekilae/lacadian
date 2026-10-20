// LaCADIAN Environmental Intelligence - parish report: every built layer for one parish, with sources.
(function () {
  "use strict";
  const { esc, getData, niceDate, saveText, csvQuote } = LC;
  const CH = LC.charts;
  const $ = id => document.getElementById(id);
  const SECTIONS = [
    ["Climate & weather", ["rain", "dryspell"]],
    ["Soil & hydrology", ["soil"]],
    ["Drought", ["usdm"]],
    ["Agriculture & vegetation", ["cropland", "crops", "crop_rice", "crop_cane", "crop_soy", "crop_corn", "crop_cotton", "crop_sweetpotato", "crop_wheat", "crop_pasture", "crop_aqua", "vegetation", "soilph", "soilom", "soilclay", "soilsand", "soilbd", "soildrain"]],
    ["Water & flooding", ["flood", "water"]],
  ];
  const PLAIN = ["rain", "soil", "usdm", "dryspell", "vegetation", "flood", "water"];

  $("app").innerHTML = `
    <h1>Parish report</h1>
    <p class="lead">Everything the site has on one parish: recent rainfall, soil water, drought, crops, soils and flood risk, with the source of each number.</p>
    <div class="card noprint"><div class="controls"><label for="psel">Parish</label><select id="psel"></select>
      <button class="btn" id="print" type="button">Print or save as PDF</button><button class="btn" id="csv" type="button">Download this parish (CSV)</button></div></div>
    <div id="rep"></div>`;

  let GJ, MAN, DATA = {};
  Promise.all([getData("data/parishes.geojson"), getData("data/layers.json")]).then(([gj, man]) => {
    GJ = gj; MAN = man;
    const names = GJ.features.map(f => f.properties).sort((a, b) => a.name.localeCompare(b.name));
    $("psel").innerHTML = `<option value="">Choose a parish…</option>` + names.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    return Promise.allSettled(MAN.layers.filter(l => l.built).map(l => getData(l.file).then(d => (DATA[l.key] = d))));
  }).then(() => {
    const id = location.hash.slice(1);
    if (id) { $("psel").value = id; }
    draw();
  }).catch(e => { $("rep").innerHTML = `<p class="stale">Could not load the data files (${esc(e.message)}).</p>`; });

  $("psel").addEventListener("change", e => { history.replaceState(null, "", "#" + e.target.value); draw(); });
  $("print").addEventListener("click", () => window.print());

  function cardFor(k, id) {
    const D = DATA[k], p = D && D.parishes[id];
    if (!p) return "";
    if (/^crop_/.test(k) && p.cat === "none") return "";
    const color = CH.maps(D).color[p.cat] || "#bdbdbd", label = CH.maps(D).label[p.cat] || "";
    const div = document.createElement("div");
    div.className = "card";
    div.innerHTML = `<h3>${esc(D.title)}</h3><p class="big"><span class="chip" style="background:${esc(color)}"></span>${esc(p.big)}</p><p class="sub">${esc(p.big_note || "")}</p><p class="sub"><b>${esc(label)}</b></p>` +
      (p.rows && p.rows.length ? `<dl class="kv">${p.rows.map(r => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl>` : "") + (p.table ? CH.tableHtml(p.table) : "");
    const box = CH.chartBox(D, p); if (box) div.appendChild(box);
    const s = document.createElement("p"); s.className = "src"; s.textContent = `Source: ${D.source}. Updated ${niceDate(D.updated)}.`; div.appendChild(s);
    return div;
  }

  function draw() {
    const id = $("psel").value, rep = $("rep");
    rep.innerHTML = "";
    $("csv").disabled = $("print").disabled = !id;
    if (!id) { rep.innerHTML = `<p class="sub" style="margin-top:14px">Choose a parish to see its report.</p>`; return; }
    const f = GJ.features.find(f => f.properties.id === id).properties;
    const built = Object.keys(DATA).length;
    const head = document.createElement("div");
    head.innerHTML = `<h2 style="margin-top:18px;font-size:1.5rem">${esc(f.name)} Parish</h2><p class="meta">Land area ${Math.round(f.land_sqmi).toLocaleString()} sq mi · FIPS ${esc(id)} · report built from ${built} map layer${built === 1 ? "" : "s"}</p>`;
    rep.appendChild(head);
    const plain = PLAIN.filter(k => DATA[k] && DATA[k].parishes[id]).map(k => {
      const D = DATA[k], p = D.parishes[id];
      return `<li><b>${esc(D.label)}:</b> ${esc(p.big)}${p.big_note ? ", " + esc(p.big_note) : ""}</li>`;
    }).join("");
    if (plain) { const s = document.createElement("div"); s.className = "card"; s.innerHTML = `<h3>In plain words</h3><ul class="plain">${plain}</ul><p class="sub" style="margin-top:6px">Each line is the value on that layer's map, as measured or mapped. It is not advice and does not say when to plant, irrigate or spray.</p>`; rep.appendChild(s); }
    SECTIONS.forEach(([title, keys]) => {
      const cards = keys.map(k => cardFor(k, id)).filter(Boolean);
      if (!cards.length) return;
      const h = document.createElement("h2"); h.className = "sechead"; h.textContent = title; rep.appendChild(h);
      const grid = document.createElement("div"); grid.className = "rep"; cards.forEach(c => grid.appendChild(c)); rep.appendChild(grid);
    });
    if (!built) rep.insertAdjacentHTML("beforeend", `<p class="stale">No map layers have been built yet, so there is nothing to report.</p>`);
  }

  $("csv").addEventListener("click", () => {
    const id = $("psel").value; if (!id) return;
    const f = GJ.features.find(f => f.properties.id === id).properties;
    const lines = [["Layer", "Value", "Class", "Note", "Detail", "Detail value", "Source", "Updated"].map(csvQuote).join(",")];
    Object.keys(DATA).forEach(k => {
      const D = DATA[k], p = D.parishes[id]; if (!p) return;
      const cls = CH.maps(D).label[p.cat] || "";
      const rows = p.rows && p.rows.length ? p.rows : [["", ""]];
      rows.forEach((r, i) => lines.push((i === 0 ? [D.label, p.big, cls, p.big_note || ""] : ["", "", "", ""]).concat([r[0], r[1]], i === 0 ? [D.source, D.updated] : ["", ""]).map(csvQuote).join(",")));
    });
    lines.push("", csvQuote(`LaCADIAN Environmental Intelligence (unofficial prototype). ${f.name} Parish. Not for farm decisions.`));
    saveText(`lacadian-parish-${id}.csv`, lines.join("\n"));
  });
})();
