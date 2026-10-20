(function () {
  "use strict";

  var NA = "#bdbdbd";
  var DRY_BINS = [ // brown (dry) to blue (wet)
    { max: 10, c: "#8c510a", t: "Driest 10% of its record" },
    { max: 25, c: "#d8b365", t: "Drier than usual (10–25%)" },
    { max: 75, c: "#f1ede0", t: "Middle of its record (25–75%)" },
    { max: 90, c: "#80b1d3", t: "Wetter than usual (75–90%)" },
    { max: 101, c: "#2166ac", t: "Wettest 10% of its record" }
  ];
  var RAIN7 = [
    { max: 2, c: "#f1ede0", t: "Under 2 mm" }, { max: 12, c: "#c6dbef", t: "2–12 mm" },
    { max: 25, c: "#6baed6", t: "12–25 mm" }, { max: 50, c: "#2171b5", t: "25–50 mm" },
    { max: 1e9, c: "#08306b", t: "50 mm or more" }
  ];
  var RAIN30 = [
    { max: 20, c: "#f1ede0", t: "Under 20 mm" }, { max: 50, c: "#c6dbef", t: "20–50 mm" },
    { max: 100, c: "#6baed6", t: "50–100 mm" }, { max: 150, c: "#2171b5", t: "100–150 mm" },
    { max: 1e9, c: "#08306b", t: "150 mm or more" }
  ];
  var DRYDAYS = [
    { max: 2, c: "#f1ede0", t: "0–1 days" }, { max: 5, c: "#fdd49e", t: "2–4 days" },
    { max: 10, c: "#fc8d59", t: "5–9 days" }, { max: 15, c: "#d7301f", t: "10–14 days" },
    { max: 1e9, c: "#7f0000", t: "15 days or more" }
  ];
  var MODES = [
    { id: "sm10", label: "Soil moisture at 10 cm, compared with its own record", bins: DRY_BINS, get: function (s) { return s.rel ? s.rel["10"] : null; },
      note: "Colour shows how the latest reading ranks within that station's own record, not the raw value." },
    { id: "sm20", label: "Soil moisture at 20 cm, compared with its own record", bins: DRY_BINS, get: function (s) { return s.rel ? s.rel["20"] : null; },
      note: "Colour shows how the latest reading ranks within that station's own record, not the raw value." },
    { id: "sm50", label: "Soil moisture at 50 cm, compared with its own record", bins: DRY_BINS, get: function (s) { return s.rel ? s.rel["50"] : null; },
      note: "Colour shows how the latest reading ranks within that station's own record, not the raw value." },
    { id: "rain7", label: "Rain in the last 7 days (mm)", bins: RAIN7, get: function (s) { return s.rain7; },
      note: "Point measurement at the station's gauge." },
    { id: "rain30", label: "Rain in the last 30 days (mm)", bins: RAIN30, get: function (s) { return s.rain30; },
      note: "Point measurement at the station's gauge." },
    { id: "dry", label: "Days in a row with under 1 mm of rain", bins: DRYDAYS, get: function (s) { return s.dry_now; },
      note: "Counted back from the station's last day with a rainfall reading." }
  ];

  var data = null, map = null, markers = {}, mode = MODES[1], selected = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function fmt(v, d) { return v == null || isNaN(v) ? "n/a" : Number(v).toFixed(d == null ? 1 : d); }
  function nice(iso) {
    if (!iso) return "n/a";
    var m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var p = iso.split("-");
    return parseInt(p[2], 10) + " " + m[parseInt(p[1], 10) - 1] + " " + p[0];
  }
  function binFor(mo, v) {
    if (v == null) return null;
    for (var i = 0; i < mo.bins.length; i++) if (v < mo.bins[i].max) return mo.bins[i];
    return mo.bins[mo.bins.length - 1];
  }
  function ordinal(r) { return r == null ? "not ranked" : "wetter than " + Math.round(r) + "% of its record"; }

  function colourOf(s) {
    var b = binFor(mode, mode.get(s));
    return b ? b.c : NA;
  }

  function drawMarkers() {
    data.stations.forEach(function (s) {
      var m = markers[s.id];
      var c = colourOf(s);
      m.setStyle({
        fillColor: s.stale ? "#ffffff" : c,
        color: s.stale ? "#555555" : "#222222",
        dashArray: s.stale ? "3 3" : null,
        weight: s.id === selected ? 3.5 : 1.5,
        fillOpacity: s.stale ? 0.9 : 0.95
      });
      if (s.id === selected) m.bringToFront();
    });
  }

  function drawLegend() {
    var ul = document.getElementById("legend");
    ul.textContent = "";
    var counts = {};
    data.stations.forEach(function (s) {
      var b = binFor(mode, mode.get(s));
      var k = b ? b.t : "na";
      counts[k] = (counts[k] || 0) + 1;
    });
    mode.bins.forEach(function (b) {
      var li = el("li");
      var sw = el("span", "sw"); sw.style.background = b.c; li.appendChild(sw);
      li.appendChild(el("span", null, b.t));
      li.appendChild(el("span", "n", "(" + (counts[b.t] || 0) + ")"));
      ul.appendChild(li);
    });
    var na = el("li");
    var s1 = el("span", "sw"); s1.style.background = NA; na.appendChild(s1);
    na.appendChild(el("span", null, "No value or not ranked"));
    na.appendChild(el("span", "n", "(" + (counts.na || 0) + ")"));
    ul.appendChild(na);
    var anyStale = data.stations.some(function (s) { return s.stale; });
    if (anyStale) {
      var st = el("li");
      st.appendChild(el("span", "sw stale"));
      st.appendChild(el("span", null, "Dashed white ring: no recent data from this station"));
      ul.appendChild(st);
    }
    document.getElementById("mapnote").textContent = mode.note + " Data through " + nice(data.data_through) + ".";
  }

  function svgEl(name, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function rainChart(ser) {
    var W = 320, H = 110, L = 28, R = 4, T = 6, B = 16;
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Daily rain over the last " + ser.dates.length + " days" });
    var vals = ser.precip, n = vals.length;
    var mx = Math.max(10, Math.max.apply(null, vals.filter(function (v) { return v != null; }).concat([0])));
    var bw = (W - L - R) / n;
    function y(v) { return T + (H - T - B) * (1 - v / mx); }
    svg.appendChild(svgEl("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: "#9aa5a0", "stroke-width": 1 }));
    var t = svgEl("text", { x: L - 3, y: T + 7, "text-anchor": "end" }); t.textContent = Math.round(mx); svg.appendChild(t);
    var t0 = svgEl("text", { x: L - 3, y: H - B, "text-anchor": "end" }); t0.textContent = "0"; svg.appendChild(t0);
    vals.forEach(function (v, i) {
      if (v == null) {
        svg.appendChild(svgEl("rect", { x: L + i * bw, y: H - B - 3, width: Math.max(bw - 0.4, 0.6), height: 3, fill: "#d9a5a0" }));
        return;
      }
      if (v <= 0) return;
      svg.appendChild(svgEl("rect", { x: L + i * bw, y: y(v), width: Math.max(bw - 0.4, 0.6), height: H - B - y(v), fill: "#2171b5" }));
    });
    [0, Math.floor(n / 2), n - 1].forEach(function (i, k) {
      var tx = svgEl("text", { x: L + i * bw + (k === 2 ? bw : 0), y: H - 3, "text-anchor": k === 0 ? "start" : (k === 2 ? "end" : "middle") });
      tx.textContent = nice(ser.dates[i]).replace(/ \d{4}$/, ""); svg.appendChild(tx);
    });
    return svg;
  }

  var SMCOL = { "5": "#d95f02", "10": "#e6ab02", "20": "#1b9e77", "50": "#7570b3", "100": "#666666" };
  function smChart(ser, depths) {
    var W = 320, H = 130, L = 28, R = 4, T = 6, B = 16;
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Soil moisture by depth over the last " + ser.dates.length + " days" });
    var all = [];
    depths.forEach(function (d) { (ser["sm" + d] || []).forEach(function (v) { if (v != null) all.push(v); }); });
    if (!all.length) return null;
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = Math.max((hi - lo) * 0.08, 0.01); lo = Math.max(0, lo - pad); hi = hi + pad;
    var n = ser.dates.length;
    function x(i) { return L + (W - L - R) * (n > 1 ? i / (n - 1) : 0); }
    function y(v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); }
    svg.appendChild(svgEl("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: "#9aa5a0", "stroke-width": 1 }));
    var a = svgEl("text", { x: L - 3, y: T + 7, "text-anchor": "end" }); a.textContent = hi.toFixed(2); svg.appendChild(a);
    var b = svgEl("text", { x: L - 3, y: H - B, "text-anchor": "end" }); b.textContent = lo.toFixed(2); svg.appendChild(b);
    depths.forEach(function (d) {
      var arr = ser["sm" + d] || [], path = "", pen = false;
      arr.forEach(function (v, i) {
        if (v == null) { pen = false; return; }
        path += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true;
      });
      if (path) svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: SMCOL[d] || "#333", "stroke-width": 1.6 }));
    });
    [0, Math.floor(n / 2), n - 1].forEach(function (i, k) {
      var tx = svgEl("text", { x: x(i), y: H - 3, "text-anchor": k === 0 ? "start" : (k === 2 ? "end" : "middle") });
      tx.textContent = nice(ser.dates[i]).replace(/ \d{4}$/, ""); svg.appendChild(tx);
    });
    return svg;
  }

  function showDetail(s) {
    var p = document.getElementById("detail");
    p.textContent = "";
    var h = el("h2", null, s.name);
    if (s.stale) h.appendChild(el("span", "badge", "No recent data"));
    p.appendChild(h);
    p.appendChild(el("p", "sub", s.id + " · latest reading " + nice(s.last) + " · record since " + nice(s.first) + " (" + s.days + " days)"));

    var kv = el("dl", "kv");
    function row(k, v) { kv.appendChild(el("dt", null, k)); kv.appendChild(el("dd", null, v)); }
    row("Rain, last 7 days", fmt(s.rain7) + " mm" + (s.rain7_missing ? " (" + s.rain7_missing + " days missing)" : ""));
    row("Rain, last 30 days", fmt(s.rain30) + " mm" + (s.rain30_missing ? " (" + s.rain30_missing + " days missing)" : ""));
    row("Days in a row under 1 mm", s.dry_now == null ? "n/a" : String(s.dry_now));
    if (s.dry_longest) row("Longest dry spell since 1 March", s.dry_longest.days + " days (" + nice(s.dry_longest.from) + " to " + nice(s.dry_longest.to) + ")");
    data.depths_cm.forEach(function (d) {
      var v = s.latest && s.latest.sm ? s.latest.sm[String(d)] : null;
      var r = s.rel ? s.rel[String(d)] : null;
      row("Soil moisture " + d + " cm", v == null ? "n/a" : fmt(v, 3) + " m³/m³ (" + ordinal(r) + ")");
    });
    p.appendChild(kv);

    var ser = s.series;
    if (ser && ser.dates && ser.dates.length) {
      var c1 = el("div", "chart");
      c1.appendChild(el("p", null, "Daily rain, last " + ser.dates.length + " days (mm)"));
      c1.appendChild(rainChart(ser));
      p.appendChild(c1);
      var sm = smChart(ser, data.depths_cm);
      if (sm) {
        var c2 = el("div", "chart");
        c2.appendChild(el("p", null, "Soil moisture by depth (m³/m³)"));
        c2.appendChild(sm);
        var lg = el("div", "lg");
        data.depths_cm.forEach(function (d) {
          var item = el("span");
          var i = el("i"); i.style.background = SMCOL[String(d)] || "#333";
          item.appendChild(i); item.appendChild(document.createTextNode(d + " cm"));
          lg.appendChild(item);
        });
        c2.appendChild(lg);
        p.appendChild(c2);
      }
    }
  }

  function select(id, pan) {
    selected = id;
    var s = data.stations.filter(function (x) { return x.id === id; })[0];
    if (!s) return;
    showDetail(s);
    drawMarkers();
    Array.prototype.forEach.call(document.querySelectorAll("#tbl tbody tr"), function (tr) {
      tr.classList.toggle("on", tr.getAttribute("data-id") === id);
    });
    if (pan && map) map.panTo([s.lat, s.lon]);
  }

  var COLS = [
    { k: "name", h: "Station", g: function (s) { return s.name + (s.stale ? " (no recent data)" : ""); }, num: false },
    { k: "rain7", h: "Rain 7 d (mm)", g: function (s) { return s.rain7; } },
    { k: "rain30", h: "Rain 30 d (mm)", g: function (s) { return s.rain30; } },
    { k: "dry", h: "Days under 1 mm", g: function (s) { return s.dry_now; } },
    { k: "sm10", h: "Soil 10 cm rank (%)", g: function (s) { return s.rel ? s.rel["10"] : null; } },
    { k: "sm20", h: "Soil 20 cm rank (%)", g: function (s) { return s.rel ? s.rel["20"] : null; } },
    { k: "sm50", h: "Soil 50 cm rank (%)", g: function (s) { return s.rel ? s.rel["50"] : null; } },
    { k: "last", h: "Last reading", g: function (s) { return s.last; }, text: true }
  ];
  var sortKey = "name", sortDir = 1;

  function drawTable() {
    var thead = document.querySelector("#tbl thead"), tbody = document.querySelector("#tbl tbody");
    thead.textContent = ""; tbody.textContent = "";
    var tr = el("tr");
    COLS.forEach(function (c) {
      var th = el("th", null, c.h);
      th.setAttribute("scope", "col");
      th.setAttribute("aria-sort", sortKey === c.k ? (sortDir > 0 ? "ascending" : "descending") : "none");
      var b = el("button", "btn", null);
      b.type = "button"; b.style.cssText = "border:0;background:none;padding:0;font:inherit;font-weight:600;cursor:pointer;color:inherit";
      b.textContent = c.h + (sortKey === c.k ? (sortDir > 0 ? " ▲" : " ▼") : "");
      b.addEventListener("click", function () {
        if (sortKey === c.k) sortDir = -sortDir; else { sortKey = c.k; sortDir = 1; }
        drawTable();
      });
      th.textContent = ""; th.appendChild(b);
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    var col = COLS.filter(function (c) { return c.k === sortKey; })[0];
    var rows = data.stations.slice().sort(function (a, b) {
      var x = col.g(a), y = col.g(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
    });
    rows.forEach(function (s) {
      var r = el("tr");
      r.setAttribute("data-id", s.id); r.tabIndex = 0;
      if (s.id === selected) r.className = "on";
      COLS.forEach(function (c) {
        var v = c.g(s);
        r.appendChild(el("td", null, c.k === "name" ? v : c.text ? (v ? nice(v) : "n/a") : (v == null ? "n/a" : fmt(v, c.k === "dry" ? 0 : (c.k.indexOf("sm") === 0 ? 0 : 1)))));
      });
      r.addEventListener("click", function () { select(s.id, true); });
      r.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(s.id, true); } });
      tbody.appendChild(r);
    });
  }

  function csv() {
    var q = function (v) { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var head = ["id", "name", "lat", "lon", "last_reading", "rain_7d_mm", "rain_30d_mm", "days_under_1mm"];
    data.depths_cm.forEach(function (d) { head.push("soil_" + d + "cm_m3m3"); head.push("soil_" + d + "cm_rank_pct"); });
    var lines = [head.join(",")];
    data.stations.forEach(function (s) {
      var r = [s.id, s.name, s.lat, s.lon, s.last, s.rain7, s.rain30, s.dry_now];
      data.depths_cm.forEach(function (d) {
        r.push(s.latest && s.latest.sm ? s.latest.sm[String(d)] : "");
        r.push(s.rel ? s.rel[String(d)] : "");
      });
      lines.push(r.map(q).join(","));
    });
    lines.push("");
    lines.push(q("Source: " + data.source + ". " + data.licence + ". Data through " + data.data_through + ". Prototype; not for farm decisions."));
    var blob = new Blob([lines.join("\n")], { type: "text/csv" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "lacadian-stations-" + data.data_through + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
  }

  function initMap() {
    map = L.map("map", { scrollWheelZoom: false }).setView([31.0, -91.8], 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12, attribution: "© OpenStreetMap contributors"
    }).addTo(map);
    var pts = [];
    data.stations.forEach(function (s) {
      var m = L.circleMarker([s.lat, s.lon], { radius: 9, weight: 1.5 }).addTo(map);
      m.bindTooltip(s.name, { direction: "top" });
      m.on("click", function () { select(s.id, false); });
      markers[s.id] = m;
      pts.push([s.lat, s.lon]);
    });
    if (pts.length) map.fitBounds(pts, { padding: [24, 24] });
  }

  function initText() {
    var lim = document.getElementById("limits");
    [
      "Soil moisture ranks use only the days each station has been reporting (between about 6 months and 21 months), so a rank is not a comparison with a long climate record.",
      "Each value is one sensor at one point. Nearby fields can differ because of soil type, drainage and local showers.",
      "Readings are as published by the network. Impossible values are blanked; large but possible values are kept and listed below.",
      "This page shows measurements, not advice. It does not say when to plant, irrigate or spray."
    ].forEach(function (t) { lim.appendChild(el("li", null, t)); });
    var q = document.getElementById("quality");
    if (!data.quality || !data.quality.length) q.appendChild(el("li", null, "None flagged in this update."));
    else data.quality.forEach(function (x) {
      q.appendChild(el("li", null, x.name + " (" + x.station + "): " + x.value + " mm of rain recorded on " + nice(x.date) + ". Kept as published; to be checked against the gauge log."));
    });
    document.getElementById("foot").textContent = "Prototype, page built " + nice(data.updated) + " from data through " + nice(data.data_through) + ". Station data: " + data.source + ". " + data.licence + ".";
    var latest = data.stations.reduce(function (m, s) { return s.last > m ? s.last : m; }, "");
    var age = Math.round((new Date(data.updated) - new Date(latest)) / 86400000);
    if (age >= 3) {
      var f = document.getElementById("fresh");
      f.textContent = "The newest reading in the public data is from " + nice(latest) + " (" + age + " days before this page was built). Values below are the last ones received, not current conditions.";
      f.hidden = false;
    }
  }

  function boot(d) {
    data = d;
    var sel = document.getElementById("mode");
    MODES.forEach(function (m) {
      var o = el("option", null, m.label); o.value = m.id; if (m === mode) o.selected = true; sel.appendChild(o);
    });
    sel.addEventListener("change", function () {
      mode = MODES.filter(function (m) { return m.id === sel.value; })[0];
      drawMarkers(); drawLegend();
    });
    document.getElementById("csv").addEventListener("click", csv);
    initMap(); initText(); drawMarkers(); drawLegend(); drawTable();
  }

  if (window.LACADIAN_DATA) { boot(window.LACADIAN_DATA); return; }
  fetch("data/stations.json?v=" + Date.now()).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(boot).catch(function (e) {
    var p = document.getElementById("detail");
    p.textContent = "";
    p.appendChild(el("p", "empty", "Could not load the station data (" + e.message + "). Please try again later."));
  });
})();
