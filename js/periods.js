// LaCADIAN Environmental Intelligence - choosing a past month for layers that keep a monthly record (data/<layer>_months.json).
(function () {
  "use strict";
  const MON = LC.MONTHS;
  const cache = {};
  const load = key => cache[key] || (cache[key] = LC.getData("data/" + key + "_months.json"));

  function years(M) { return Array.from(new Set(M.months.map(m => m.slice(0, 4)))).sort().reverse(); }
  function monthsIn(M, year) { return M.months.map((m, i) => ({ i, m, mo: +m.slice(5, 7) })).filter(x => x.m.slice(0, 4) === year); }
  const indexOf = (M, ym) => M.months.indexOf(ym);

  // The layer as it was for month index i: same shape as the latest payload, so the map, ranking, CSV and PNG work unchanged.
  function overlay(D, M, i) {
    const o = JSON.parse(JSON.stringify(D));
    const label = M.labels[i], catLabel = {};
    o.categories.forEach(c => { catLabel[c.key] = c.label; });
    const counts = {};
    const from = Math.max(0, i - 11);
    Object.keys(o.parishes).forEach(id => {
      const p = o.parishes[id], mp = M.parishes[id];
      if (!mp) return;
      const v = mp.v[i], cat = M.cats[mp.k[i]];
      const off = M.offset == null ? 100 : M.offset, suf = M.suffix == null ? "%" : M.suffix, sv = v == null ? "" : (M.plus && v > 0 ? "+" : "") + v;
      p.cat = cat; p.rv = v;
      p.big = v == null ? "–" : M.big.replace("{v}", sv);
      p.big_note = v == null ? "Not rated for this period." : M.note.replace("{label}", label);
      p.tip = v == null ? (catLabel[cat] || "Not rated") : M.tip.replace("{cat}", catLabel[cat] || "").replace("{v}", sv);
      p.rows = [["Period", label], [M.value_label, v == null ? "n/a" : sv + suf]];
      delete p.table;
      p.v = mp.v.slice(from, i + 1).map(x => x == null ? null : Math.round((x - off) * 100) / 100);
      p.c = mp.k.slice(from, i + 1).map(k => M.cats[k]);
      counts[cat] = (counts[cat] || 0) + 1;
    });
    o.counts = counts;
    o.subtitle = label + ", " + M.basis;
    o.period = M.months[i];
    o.period_label = label;
    if (o.chart) o.chart.x = M.months.slice(from, i + 1).map(m => MON[+m.slice(5, 7) - 1]);
    o.how = (o.how || "") + " This is the map for " + label + "; the ranking and the 12-month chart end at that period.";
    return o;
  }

  // ---- one interface for both kinds of history
  // months file (rain, soil, vegetation): the picked month is computed from data/<layer>_months.json
  // saved versions (crops by year, Drought Monitor by month): data/<layer>@<period>.json, listed in layers.json as meta.periods
  const periodLabel = p => p.length === 7 ? MON[+p.slice(5, 7) - 1] + " " + p.slice(0, 4) : p;
  function source(meta, base) {
    if (meta.months) {
      return load(meta.key).then(M => ({
        years: years(M),
        months: y => monthsIn(M, y).map(x => ({ v: String(x.i), label: M.labels[x.i] })),
        single: () => null,
        find: ym => { const i = indexOf(M, ym); return i < 0 ? null : String(i); },
        fetch: v => Promise.resolve(overlay(base, M, +v)),
      }));
    }
    if (meta.periods && meta.periods.length) {
      const list = meta.periods;
      return Promise.resolve({
        years: Array.from(new Set(list.map(p => p.slice(0, 4)))).sort().reverse(),
        months: y => list.filter(p => p.length === 7 && p.slice(0, 4) === y).sort().map(p => ({ v: p, label: periodLabel(p) })),
        single: y => (list.includes(y) ? y : null),
        find: p => (list.includes(p) ? p : null),
        fetch: v => LC.getData("data/" + meta.key + "@" + v + ".json"),
      });
    }
    return Promise.resolve(null);
  }

  window.LC = window.LC || {};
  LC.periods = { load, years, monthsIn, indexOf, overlay, source };
})();
