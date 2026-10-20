// LaCADIAN Environmental Intelligence - data page: one row per layer, with downloads.
(function () {
  "use strict";
  const { esc, getData, niceDate, saveText } = LC;
  const CH = LC.charts;
  const $ = id => document.getElementById(id);
  $("app").innerHTML = `
    <h1>Data</h1>
    <p class="lead">Every map layer as a table (CSV) or in full (JSON). Values are the latest update; the files are rewritten each time the site updates. Please keep the source credit with any use. Station data are for academic and non-commercial use (CC BY-NC 4.0 as stated by the network).</p>
    <div class="card"><div class="scroll"><table style="min-width:760px"><thead><tr><th>Layer</th><th>Source</th><th>Updated</th><th>Download</th></tr></thead><tbody id="rows"></tbody></table></div></div>
    <div class="card notes"><h2>Other files</h2><ul id="other"></ul></div>`;
  getData("data/layers.json").then(man => {
    $("rows").innerHTML = man.layers.map(l => l.built
      ? `<tr><td class="l">${esc(l.label)}</td><td class="l" id="src-${l.key}" style="white-space:normal">…</td><td>${esc(niceDate(l.updated))}</td><td><button class="btn" data-k="${l.key}" data-f="csv" type="button">CSV</button> <button class="btn" data-k="${l.key}" data-f="json" type="button">JSON</button></td></tr>`
      : `<tr><td class="l">${esc(l.label)}</td><td class="l" colspan="3">Not built yet</td></tr>`).join("");
    man.layers.filter(l => l.built).forEach(l => getData(l.file).then(d => { const e = $("src-" + l.key); if (e) e.textContent = d.source; }).catch(() => {}));
  }).catch(e => { $("rows").innerHTML = `<tr><td colspan="4">Could not load the layer list (${esc(e.message)}).</td></tr>`; });
  $("rows").addEventListener("click", e => {
    const b = e.target.closest("button[data-k]"); if (!b) return;
    getData("data/" + b.dataset.k + ".json").then(D => {
      if (b.dataset.f === "json") saveText(`lacadian-${b.dataset.k}-${D.updated}.json`, JSON.stringify(D), "application/json");
      else saveText(`lacadian-${b.dataset.k}-${D.updated}.csv`, CH.csvText(D));
    });
  });
  const links = [["data/stations.json", "LaCADIAN stations: latest values and recent series (JSON)"], ["data/validation.json", "Check of gridMET and SMAP against the stations (JSON)"],
    ["data/crops-by-parish.csv", "Crop acres by parish and year (CSV)"], ["data/parishes.geojson", "Parish boundaries, US Census Bureau (GeoJSON)"]];
  $("other").innerHTML = links.map(([u, t]) => `<li><a href="${LC.ROOT}${u}">${esc(t)}</a></li>`).join("");
})();
