// LaCADIAN - shared drawing and export helpers (SVG charts, tables, CSV, PNG, station-check block).
(function () {
  "use strict";
  const esc = LC.esc;
  const NS = "http://www.w3.org/2000/svg";
  const sv = (n, a) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };

  // category key -> colour / label for one layer payload
  function maps(D) {
    const color = {}, label = {};
    (D.categories || []).forEach(c => { color[c.key] = c.color; label[c.key] = c.label; });
    return { color, label };
  }

  // chart.kind "diverging" (bars up/down from a middle line, coloured by class) or "bars"
  function chartSvg(c, p, color) {
    if (!c || !p || !p.v || !p.v.length) return null;
    const W = 320, H = 150, L = 6, R = 6, T = 14, B = 30, n = p.v.length, bw = (W - L - R) / n;
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": c.caption || "chart" });
    const txt = (x, y, s, anchor, extra) => { const t = sv("text", Object.assign({ x, y, "text-anchor": anchor || "middle" }, extra || {})); t.textContent = s; svg.appendChild(t); };
    const rotate = n > 8 || (c.x || []).some(x => String(x).length > 6);
    const lab = (i, y) => {
      const x = L + i * bw + bw / 2;
      if (rotate) txt(x, y, String(c.x[i]), "end", { transform: `rotate(-40 ${x} ${y})` });
      else txt(x, y, String(c.x[i]), "middle");
    };
    if (c.kind === "diverging") {
      const mid = T + (H - T - B) / 2, half = (H - T - B) / 2, cap = c.cap || 50;
      svg.appendChild(sv("line", { x1: L, x2: W - R, y1: mid, y2: mid, stroke: "#8a948f", "stroke-width": 1 }));
      p.v.forEach((v, i) => {
        if (v == null) svg.appendChild(sv("rect", { x: L + i * bw + 2, y: mid - 1, width: bw - 4, height: 2, fill: "#bdbdbd" }));
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
          svg.appendChild(sv("rect", { x: L + i * bw + 3, y: base - hgt, width: bw - 6, height: Math.max(hgt, 0.5), fill: (p.bc || [])[i] || "#237A57" }));
          if (n <= 12) txt(L + i * bw + bw / 2, base - hgt - 3, v >= 1000 ? Math.round(v).toLocaleString() : (Math.abs(v) < 10 && v % 1 ? v.toFixed(1) : String(Math.round(v * 10) / 10)), "middle", { class: "val" });
        }
        lab(i, base + 11);
      });
      if (c.unit) txt(W - R, T - 3, c.unit, "end");
    }
    return svg;
  }

  // a chart with its caption, ready to append (or null)
  function chartBox(D, p) {
    const svg = chartSvg(D.chart, p, maps(D).color);
    if (!svg) return null;
    const box = document.createElement("div");
    box.className = "chart";
    box.innerHTML = `<p>${esc(D.chart.caption || "")}</p>`;
    box.appendChild(svg);
    return box;
  }

  function tableHtml(t) {
    return `<div class="ptable"><p><b>${esc(t.caption || "")}</b></p><table><thead><tr>${t.head.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${
      t.rows.map(r => `<tr>${r.map((x, i) => `<td${i ? ' class="r"' : ""}>${esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>${t.note ? `<p class="sub">${esc(t.note)}</p>` : ""}</div>`;
  }

  // one layer as CSV text
  function csvText(D) {
    const { label } = maps(D);
    const labels = [];
    Object.values(D.parishes).forEach(p => (p.rows || []).forEach(r => { if (!labels.includes(r[0])) labels.push(r[0]); }));
    const lines = [["Parish FIPS", "Parish", "Class", "Main figure", "Note"].concat(labels).map(LC.csvQuote).join(",")];
    Object.entries(D.parishes).forEach(([id, p]) => {
      const m = Object.fromEntries((p.rows || []).map(r => [r[0], r[1]]));
      lines.push([id, p.name, label[p.cat] || "", p.big, p.big_note || ""].concat(labels.map(l => m[l] == null ? "" : m[l])).map(LC.csvQuote).join(","));
    });
    lines.push("", LC.csvQuote(`LaCADIAN Environmental Intelligence (unofficial prototype). ${D.title}. Source: ${D.source}. ${D.period ? "Period " + D.period + "." : "Updated " + D.updated + "."} Not for farm decisions.`));
    return lines.join("\n");
  }

  // the map as a PNG data URL (title, legend, source line)
  function pngUrl(D, gj) {
    const { color } = maps(D);
    const polys = [];
    gj.features.forEach(f => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates).forEach(poly => polys.push([f.properties.id, poly])));
    let w = 1e9, e = -1e9, s = 1e9, n = -1e9;
    polys.forEach(([, poly]) => poly[0].forEach(([x, y]) => { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }));
    const k = Math.cos((s + n) / 2 * Math.PI / 180), mw = 1500, sc = mw / ((e - w) * k), mh = Math.round((n - s) * sc);
    const cats = D.categories.filter(c => (D.counts[c.key] || 0) > 0);
    const top = 190, legendH = 70 + cats.length * 46, foot = 150, W = mw + 160, H = top + Math.max(mh, legendH) + foot;
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H; const g = cv.getContext("2d");
    const SANS = "Arial, Helvetica, sans-serif";
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#16324F"; g.font = `700 54px ${SANS}`; g.fillText(D.title, 80, 90, W - 160);
    g.fillStyle = "#566670"; g.font = `34px ${SANS}`; g.fillText(D.subtitle || "", 80, 145, W - 160);
    polys.forEach(([id, poly]) => {
      g.beginPath();
      poly.forEach(ring => ring.forEach(([x, y], i) => { const px = 80 + (x - w) * k * sc, py = top + (n - y) * sc; i ? g.lineTo(px, py) : g.moveTo(px, py); }));
      const p = D.parishes[id]; g.fillStyle = p ? color[p.cat] || "#ccc" : "#ccc"; g.fill("evenodd"); g.strokeStyle = "#55605c"; g.lineWidth = 1.2; g.stroke();
    });
    let ly = top + 20; g.font = `600 32px ${SANS}`;
    cats.forEach(c => { g.fillStyle = c.color; g.fillRect(W - 640, ly, 34, 34); g.strokeStyle = "#555"; g.strokeRect(W - 640, ly, 34, 34); g.fillStyle = "#17232d"; g.fillText(`${c.label} (${D.counts[c.key]})`, W - 590, ly + 27, 520); ly += 46; });
    g.fillStyle = "#566670"; g.font = `28px ${SANS}`;
    g.fillText(`Source: ${D.source}. ${D.period ? "Period " + D.period + "." : "Updated " + D.updated + "."}`, 80, H - 90, W - 160);
    g.fillText("LaCADIAN Environmental Intelligence (unofficial prototype, not approved by the network team). Not for farm decisions. Boundaries: US Census Bureau.", 80, H - 45, W - 160);
    return cv.toDataURL("image/png");
  }
  function savePng(D, gj) {
    const a = document.createElement("a"); a.href = pngUrl(D, gj); a.download = `lacadian-${D.key}-${D.period || D.updated}.png`;
    document.body.appendChild(a); a.click(); a.remove();
  }

  // the "check against the stations" block as HTML (v = data/validation.json or null)
  function validationHtml(v, kind) {
    const blk = v && v[kind];
    const f = (x, dec) => x == null ? "n/a" : Number(x).toFixed(dec == null ? 2 : dec);
    let h = `<h2>Check against the LaCADIAN stations</h2>`;
    if (!blk) return h + "<p>The check has not been run yet. It needs the rainfall and soil moisture records and the station data; it appears after the next full update.</p>";
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
    return h;
  }

  LC.charts = { maps, chartSvg, chartBox, tableHtml, csvText, pngUrl, savePng, validationHtml };
})();
