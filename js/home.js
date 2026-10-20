// LaCADIAN - home page: shows what has been built and how fresh the data are.
(function () {
  "use strict";
  const { getData, niceDate, esc } = LC;
  const set = (id, t) => { const e = document.getElementById(id); if (e) e.textContent = t; };
  getData("data/stations.json").then(d => set("st-state", `${d.n} stations, data through ${niceDate(d.data_through)}.`))
    .catch(() => set("st-state", "Station data not available yet."));
  getData("data/layers.json").then(m => {
    for (const page of ["drought", "agriculture", "land"]) {
      const ls = m.layers.filter(l => l.page === page), built = ls.filter(l => l.built);
      const newest = built.map(l => l.updated).filter(Boolean).sort().pop();
      set("st-" + page, built.length ? `${built.length} of ${ls.length} layers built; newest ${niceDate(newest)}.` : "Not built yet. It appears after the first full update.");
    }
  }).catch(() => ["drought", "agriculture", "land"].forEach(p => set("st-" + p, "Not built yet.")));
})();
