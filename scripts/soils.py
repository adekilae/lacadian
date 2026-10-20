#!/usr/bin/env python3
"""
LaCADIAN site - soil properties by parish, from the USDA soil survey (SSURGO).

Source: USDA Natural Resources Conservation Service, Soil Data Access (SDA). It serves the official US soil survey
(SSURGO / gSSURGO). For each soil survey area the script asks SDA for the area-weighted average, in the top 30 cm, of:
  soil pH (1:1 in water), organic matter (%), clay (%), sand (%), bulk density (g/cm3, at 1/3 bar),
and the share of land in each natural drainage class.
Louisiana soil survey areas follow parish lines (a few cover two parishes); the script matches them to parishes by name,
and averages when a parish is covered by more than one survey area, weighting by the area of each.

It publishes six layers: soilph, soilom, soilclay, soilsand, soilbd, soildrain. The soil survey does not change quickly, so the
layers are built once and rebuilt only when asked (SOILS=true) or when this script's BUILD number goes up.

Averaging: each map unit counts by its area; each soil component in it by its percentage; each horizon by the thickness
that lies within 0-30 cm. Horizons with no value for a property are left out of that property's average.

Run:
  python scripts/soils.py
  python scripts/soils.py --self-test
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BOUNDARY_CREDIT, DATA, load_parishes, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
TOP_CM = 30
# --------------------------------------------------------------------------

PROPS = [
    # key, column, label, unit, decimals, cut points, class labels, colours, description
    ("soilph", "ph", "Soil pH", "", 1, [5.0, 5.6, 6.1, 6.6],
     ["Under 5.0 (very strongly acid)", "5.0–5.5 (strongly acid)", "5.6–6.0 (moderately acid)", "6.1–6.5 (slightly acid)", "6.6 or more (neutral to alkaline)"],
     ["#8c2d04", "#d94801", "#f1a340", "#a1d99b", "#238b45"], "soil pH measured in water; lower is more acid"),
    ("soilom", "om", "Organic matter", "%", 1, [1, 2, 4, 10],
     ["Under 1%", "1–2%", "2–4%", "4–10%", "10% or more"],
     ["#f6efe7", "#e0c9a6", "#b98a5c", "#7a5230", "#3b2314"], "organic matter as a percent of the soil"),
    ("soilclay", "clay", "Clay", "%", 0, [10, 20, 30, 40],
     ["Under 10%", "10–20%", "20–30%", "30–40%", "40% or more"],
     ["#fff1e0", "#fdd0a2", "#fd8d3c", "#d94801", "#7f2704"], "clay (particles under 0.002 mm) as a percent of the soil"),
    ("soilsand", "sand", "Sand", "%", 0, [10, 25, 40, 60],
     ["Under 10%", "10–25%", "25–40%", "40–60%", "60% or more"],
     ["#fffbe0", "#f7e9a0", "#e6c65a", "#c99a2e", "#8a6212"], "sand (particles 0.05 to 2 mm) as a percent of the soil"),
    ("soilbd", "bd", "Bulk density", "g/cm³", 2, [1.2, 1.35, 1.5, 1.6],
     ["Under 1.20", "1.20–1.35", "1.35–1.50", "1.50–1.60", "1.60 or more"],
     ["#f2f0f7", "#cbc9e2", "#9e9ac8", "#756bb1", "#54278f"], "dry weight of soil per volume at field capacity (1/3 bar); higher means more compact"),
]
DRAIN = ["Excessively drained", "Somewhat excessively drained", "Well drained", "Moderately well drained",
         "Somewhat poorly drained", "Poorly drained", "Very poorly drained"]
DRAIN_COLORS = ["#8c510a", "#bf812d", "#dfc27d", "#c7eae5", "#80cdc1", "#35978f", "#01665e"]
DRAIN_DESC = {"Excessively drained": "water moves through very fast", "Somewhat excessively drained": "water moves through fast",
              "Well drained": "water moves through readily", "Moderately well drained": "wet for a short time in the growing season",
              "Somewhat poorly drained": "wet for significant periods", "Poorly drained": "wet for much of the year; usually needs drainage for field crops",
              "Very poorly drained": "wet most of the year"}

SQL_PROPS = f"""
SELECT areasymbol, MAX(areaname) AS areaname,
  SUM(CASE WHEN ph IS NOT NULL THEN w * ph ELSE 0 END) / NULLIF(SUM(CASE WHEN ph IS NOT NULL THEN w ELSE 0 END), 0) AS ph,
  SUM(CASE WHEN om IS NOT NULL THEN w * om ELSE 0 END) / NULLIF(SUM(CASE WHEN om IS NOT NULL THEN w ELSE 0 END), 0) AS om,
  SUM(CASE WHEN clay IS NOT NULL THEN w * clay ELSE 0 END) / NULLIF(SUM(CASE WHEN clay IS NOT NULL THEN w ELSE 0 END), 0) AS clay,
  SUM(CASE WHEN sand IS NOT NULL THEN w * sand ELSE 0 END) / NULLIF(SUM(CASE WHEN sand IS NOT NULL THEN w ELSE 0 END), 0) AS sand,
  SUM(CASE WHEN bd IS NOT NULL THEN w * bd ELSE 0 END) / NULLIF(SUM(CASE WHEN bd IS NOT NULL THEN w ELSE 0 END), 0) AS bd
FROM (
  SELECT l.areasymbol AS areasymbol, l.areaname AS areaname,
    mu.muacres * c.comppct_r * (CASE WHEN ch.hzdepb_r > {TOP_CM} THEN {TOP_CM} ELSE ch.hzdepb_r END
                                - CASE WHEN ch.hzdept_r < 0 THEN 0 ELSE ch.hzdept_r END) AS w,
    ch.ph1to1h2o_r AS ph, ch.om_r AS om, ch.claytotal_r AS clay, ch.sandtotal_r AS sand, ch.dbthirdbar_r AS bd
  FROM legend l
  INNER JOIN mapunit mu ON mu.lkey = l.lkey
  INNER JOIN component c ON c.mukey = mu.mukey
  INNER JOIN chorizon ch ON ch.cokey = c.cokey
  WHERE l.areasymbol LIKE 'LA%' AND ch.hzdept_r < {TOP_CM} AND ch.hzdepb_r > 0
    AND mu.muacres IS NOT NULL AND c.comppct_r IS NOT NULL
) t
GROUP BY areasymbol
"""
SQL_DRAIN = """
SELECT l.areasymbol AS areasymbol, c.drainagecl AS drainagecl, SUM(mu.muacres * c.comppct_r / 100.0) AS acres
FROM legend l
INNER JOIN mapunit mu ON mu.lkey = l.lkey
INNER JOIN component c ON c.mukey = mu.mukey
WHERE l.areasymbol LIKE 'LA%' AND c.drainagecl IS NOT NULL AND mu.muacres IS NOT NULL AND c.comppct_r IS NOT NULL
GROUP BY l.areasymbol, c.drainagecl
"""
SQL_ACRES = """
SELECT l.areasymbol AS areasymbol, SUM(mu.muacres) AS acres
FROM legend l INNER JOIN mapunit mu ON mu.lkey = l.lkey
WHERE l.areasymbol LIKE 'LA%'
GROUP BY l.areasymbol
"""


def ask(sql):
    """Run a query on Soil Data Access -> list of dicts. An empty result is an empty list."""
    import requests
    last = None
    for attempt in range(1, 5):
        try:
            r = requests.post(SDA, json={"query": " ".join(sql.split()), "format": "JSON+COLUMNNAME"}, timeout=300)
            if r.status_code == 200:
                try:
                    js = r.json()
                except ValueError:
                    last = RuntimeError("not JSON: " + r.text[:200])
                    raise last
                rows = parse_table(js)
                if not rows:
                    print("  (empty reply: " + r.text[:200].replace("\n", " ") + ")")
                return rows
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            last = e
        import time
        time.sleep(10 * attempt)
    raise last


def parse_table(js):
    t = js.get("Table") if isinstance(js, dict) else None
    if not t or len(t) < 2:
        return []
    head = t[0]
    return [dict(zip(head, row)) for row in t[1:]]


def norm(name):
    """'St. John the Baptist Parish' -> 'stjohnthebaptist'; 'De Soto' and 'DeSoto' agree."""
    s = name.lower().replace("saint", "st")
    s = re.sub(r"\b(parish|parishes|louisiana|county)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def parishes_of(areaname, by_norm):
    """Parish ids named in a soil survey area name such as 'Ouachita Parish, Louisiana' or 'Union and Morehouse Parishes, Louisiana'."""
    base = areaname.split(", Louisiana")[0]
    ids = []
    for part in re.split(r"\s+and\s+|,\s*", base):
        n = norm(part)
        if n in by_norm:
            ids.append(by_norm[n])
    return ids


def to_parish(gdf, props, acres, drain):
    """Survey-area values -> {parish id: {"vals": {prop: value}, "drain": {class: acres}, "surveys": [areasymbol]}}."""
    by_norm = {norm(n): i for i, n in zip(gdf["id"], gdf["name"])}
    acc = {}
    unmatched = []
    for r in props:
        ids = parishes_of(r["areaname"], by_norm)
        if not ids:
            unmatched.append(r["areaname"])
            continue
        w = float(acres.get(r["areasymbol"], 1.0)) / len(ids)
        for pid in ids:
            a = acc.setdefault(pid, {"w": {}, "s": {}, "surveys": []})
            a["surveys"].append(r["areasymbol"])
            for k in ("ph", "om", "clay", "sand", "bd"):
                if r.get(k) is not None:
                    a["s"][k] = a["s"].get(k, 0.0) + w * float(r[k])
                    a["w"][k] = a["w"].get(k, 0.0) + w
    sym2 = {}
    for r in props:
        sym2[r["areasymbol"]] = parishes_of(r["areaname"], by_norm)
    dr = {}
    for r in drain:
        ids = sym2.get(r["areasymbol"], [])
        for pid in ids:
            dr.setdefault(pid, {})
            dr[pid][r["drainagecl"]] = dr[pid].get(r["drainagecl"], 0.0) + float(r["acres"]) / len(ids)
    out = {}
    for pid, a in acc.items():
        out[pid] = {"vals": {k: a["s"][k] / a["w"][k] for k in a["s"]}, "drain": dr.get(pid, {}), "surveys": a["surveys"]}
    return out, unmatched


def classify(v, cuts):
    return int(np.searchsorted(cuts, v, side="right"))


def build(gdf, data):
    names = dict(zip(gdf["id"], gdf["name"]))
    ids = list(gdf["id"])
    credits = [{"text": "Soils: USDA Natural Resources Conservation Service, Soil Survey Geographic Database (SSURGO), through Soil Data Access", "url": "https://sdmdataaccess.nrcs.usda.gov/"},
               BOUNDARY_CREDIT]
    limits = [
        f"Values are averages of the top {TOP_CM} cm, over every soil map unit in the parish weighted by its area. One parish holds many different soils, so a field can differ a lot from the parish average.",
        "The soil survey describes soils from field surveys and lab samples. The numbers are the survey's representative values, not measurements of a particular field.",
        "Some soil survey areas cover two parishes or part of a parish; those values are shared between the parishes they cover.",
        "Soil changes slowly, but liming, fertiliser, drainage and flooding change pH, organic matter and salinity locally. Soil tests are the reliable guide for a field.",
    ]
    for key, col, label, unit, dec, cuts, labs, colors, desc in PROPS:
        cats = [{"key": f"s{k}", "label": labs[k], "note": "", "color": colors[k]} for k in range(5)] + [{"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"}]
        parishes = {}
        for pid in ids:
            v = data.get(pid, {}).get("vals", {}).get(col)
            if v is None:
                parishes[pid] = {"name": names[pid], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [],
                                 "big_note": "The soil survey has no value for this parish."}
                continue
            k = classify(v, cuts)
            fmt = f"{v:.{dec}f}" + (f" {unit}" if unit else "")
            rows = [[label + f", top {TOP_CM} cm", fmt], ["Class", labs[k]], ["Soil survey areas used", ", ".join(data[pid]["surveys"])]]
            if col in ("clay", "sand") and "clay" in data[pid]["vals"] and "sand" in data[pid]["vals"]:
                clay, sand = data[pid]["vals"]["clay"], data[pid]["vals"]["sand"]
                rows.append(["Clay, silt, sand", f"{clay:.0f}%, {max(0, 100 - clay - sand):.0f}%, {sand:.0f}%"])
            p = {"name": names[pid], "cat": f"s{k}", "rv": round(v, 3), "big": fmt, "big_note": f"average {desc}, top {TOP_CM} cm",
                 "tip": f"{label}: {fmt}", "rows": rows}
            if col in ("clay", "sand") and "clay" in data[pid]["vals"] and "sand" in data[pid]["vals"]:
                clay, sand = data[pid]["vals"]["clay"], data[pid]["vals"]["sand"]
                p["v"] = [round(clay, 1), round(max(0, 100 - clay - sand), 1), round(sand, 1)]
                p["bc"] = ["#8c510a", "#b8c4bd", "#e6c65a"]
            parishes[pid] = p
        payload = {"label": label, "title": f"{label} of the soil, by parish", "subtitle": f"USDA soil survey (SSURGO), average of the top {TOP_CM} cm",
                   "source": "USDA NRCS Soil Survey Geographic Database (SSURGO)", "demo": False, "build": BUILD, "categories": cats,
                   "rank": {"high": f"Highest {label.lower()}", "low": f"Lowest {label.lower()}", "note": f"Ranked by {label.lower()}."},
                   "how": (f"Each parish is coloured by its average {desc}, from the official USDA soil survey, for the top {TOP_CM} cm of soil. Each map unit is weighted by its area."),
                   "limits": limits, "credits": credits, "parishes": parishes}
        if col in ("clay", "sand"):
            payload["chart"] = {"kind": "bars", "unit": "%", "x": ["Clay", "Silt", "Sand"], "caption": "Soil texture, top 30 cm (%)", "top": "", "bottom": ""}
        write_layer(key, payload)

    # drainage class: the class that covers most of the parish
    cats = [{"key": f"d{k}", "label": DRAIN[k], "note": DRAIN_DESC[DRAIN[k]], "color": DRAIN_COLORS[k]} for k in range(7)] + [{"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"}]
    parishes = {}
    for pid in ids:
        dr = data.get(pid, {}).get("drain", {})
        tot = sum(dr.values())
        if tot <= 0:
            parishes[pid] = {"name": names[pid], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": "The soil survey has no drainage class for this parish."}
            continue
        top = max(dr, key=dr.get)
        if top not in DRAIN:
            parishes[pid] = {"name": names[pid], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": f"Unusual drainage class: {top}"}
            continue
        k = DRAIN.index(top)
        poor = (dr.get("Poorly drained", 0) + dr.get("Very poorly drained", 0)) / tot * 100
        good = (dr.get("Well drained", 0) + dr.get("Excessively drained", 0) + dr.get("Somewhat excessively drained", 0)) / tot * 100
        table = {"caption": f"Drainage classes in {names[pid]}", "head": ["Class", "Share of the soil"],
                 "rows": [[c, f"{dr[c] / tot * 100:.0f}%"] for c in sorted(dr, key=lambda c: -dr[c]) if dr[c] / tot >= 0.005],
                 "note": "Natural drainage class of each soil component, weighted by the area of its map unit."}
        parishes[pid] = {"name": names[pid], "cat": f"d{k}", "rv": round(poor, 1), "big": top, "big_note": f"covers the most land ({dr[top] / tot * 100:.0f}% of the parish's soil)",
                         "tip": f"{top} ({dr[top] / tot * 100:.0f}%)",
                         "rows": [["Poorly or very poorly drained", f"{poor:.0f}%"], ["Well or excessively drained", f"{good:.0f}%"]], "table": table}
    write_layer("soildrain", {
        "label": "Drainage class", "title": "Natural soil drainage, by parish", "subtitle": "The drainage class that covers the most land, USDA soil survey",
        "source": "USDA NRCS Soil Survey Geographic Database (SSURGO)", "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Most poorly drained soil", "low": "Least poorly drained soil", "note": "Ranked by the share of poorly or very poorly drained soil."},
        "how": ("Each parish is coloured by the natural drainage class that covers most of its soil: how fast water leaves the soil in its natural state, "
                "from excessively drained (sandy, dries quickly) to very poorly drained (wet most of the year). Click a parish for every class."),
        "limits": limits + ["Natural drainage describes the soil before ditches, tile or levees. Many Louisiana fields are drained or flooded on purpose, for example rice."],
        "credits": credits, "parishes": parishes})


def self_test():
    import geopandas as gpd
    import tempfile
    from shapely.geometry import box
    # the reply format
    assert parse_table({"Table": [["areasymbol", "ph"], ["LA001", "5.5"]]}) == [{"areasymbol": "LA001", "ph": "5.5"}]
    assert parse_table({"Table": [["a"]]}) == [] and parse_table({}) == []
    # name matching
    assert norm("St. John the Baptist Parish") == norm("Saint John the Baptist") == "stjohnthebaptist"
    assert norm("De Soto") == norm("DeSoto Parish, Louisiana") == "desoto" and norm("La Salle") == norm("LaSalle Parish")
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005", "22007"], "name": ["Acadia", "Jefferson", "Jefferson Davis", "De Soto"]},
                         geometry=[box(i, 0, i + 1, 1) for i in range(4)], crs=4326)
    by = {norm(n): i for i, n in zip(g["id"], g["name"])}
    assert parishes_of("Acadia Parish, Louisiana", by) == ["22001"]
    assert parishes_of("Jefferson Davis Parish, Louisiana", by) == ["22005"]               # not Jefferson
    assert parishes_of("Acadia and Jefferson Parishes, Louisiana", by) == ["22001", "22003"]
    assert parishes_of("Calcasieu Parish, Louisiana", by) == []
    assert parishes_of("DeSoto Parish, Louisiana", by) == ["22007"]
    # survey values -> parish: a parish with two surveys is averaged by acres; a shared survey goes to both
    props = [{"areasymbol": "LA001", "areaname": "Acadia Parish, Louisiana", "ph": 5.0, "om": 1.0, "clay": 20.0, "sand": 30.0, "bd": 1.4},
             {"areasymbol": "LA002", "areaname": "Acadia Parish, Louisiana", "ph": 7.0, "om": None, "clay": 40.0, "sand": 10.0, "bd": 1.5},
             {"areasymbol": "LA003", "areaname": "Jefferson and Jefferson Davis Parishes, Louisiana", "ph": 6.0, "om": 2.0, "clay": 10.0, "sand": 60.0, "bd": 1.3},
             {"areasymbol": "LA999", "areaname": "Somewhere Else, Louisiana", "ph": 1, "om": 1, "clay": 1, "sand": 1, "bd": 1}]
    acres = {"LA001": 3000.0, "LA002": 1000.0, "LA003": 500.0}
    drain = [{"areasymbol": "LA001", "drainagecl": "Poorly drained", "acres": "2000"}, {"areasymbol": "LA001", "drainagecl": "Well drained", "acres": "1000"},
             {"areasymbol": "LA003", "drainagecl": "Moderately well drained", "acres": "400"}]
    out, unmatched = to_parish(g, props, acres, drain)
    assert unmatched == ["Somewhere Else, Louisiana"]
    assert abs(out["22001"]["vals"]["ph"] - (3000 * 5 + 1000 * 7) / 4000) < 1e-9 and abs(out["22001"]["vals"]["om"] - 1.0) < 1e-9     # a survey with no organic matter is left out of that average
    assert out["22003"]["vals"]["ph"] == 6.0 and out["22005"]["vals"]["clay"] == 10.0 and out["22003"]["drain"] == {"Moderately well drained": 200.0}
    # classes
    assert classify(4.9, [5.0, 5.6, 6.1, 6.6]) == 0 and classify(5.0, [5.0, 5.6, 6.1, 6.6]) == 1 and classify(7.9, [5.0, 5.6, 6.1, 6.6]) == 4
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        build(g, out)
        for k in ("soilph", "soilom", "soilclay", "soilsand", "soilbd", "soildrain"):
            assert (Path(tmp) / f"{k}.json").exists()
        ph = json.loads((Path(tmp) / "soilph.json").read_text())
        assert ph["parishes"]["22001"]["cat"] == "s1" and ph["parishes"]["22007"]["cat"] == "not_rated"
        dr = json.loads((Path(tmp) / "soildrain.json").read_text())
        assert dr["parishes"]["22001"]["cat"] == "d5" and dr["parishes"]["22001"]["big"] == "Poorly drained" and dr["parishes"]["22003"]["cat"] == "d3"
        cl = json.loads((Path(tmp) / "soilclay.json").read_text())
        assert cl["parishes"]["22001"]["v"] == [25.0, 30.0, 45.0] or sum(cl["parishes"]["22001"]["v"]) == 100.0, cl["parishes"]["22001"]["v"]
    common.DATA = old
    print("self-test passed: 6 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    gdf = load_parishes()
    areas = ask("SELECT areasymbol, areaname FROM legend WHERE areasymbol LIKE 'LA%'")
    print(f"{len(areas)} Louisiana soil survey areas listed")
    props, drain, acres = [], [], {}
    for a in areas:
        sym = a["areasymbol"]
        where = f"l.areasymbol = '{sym}'"
        props += ask(SQL_PROPS.replace("l.areasymbol LIKE 'LA%'", where))
        drain += ask(SQL_DRAIN.replace("l.areasymbol LIKE 'LA%'", where))
        for r in ask(SQL_ACRES.replace("l.areasymbol LIKE 'LA%'", where)):
            acres[r["areasymbol"]] = float(r["acres"])
    if not props:
        sys.exit("Soil Data Access returned no Louisiana soil survey areas.")
    data, unmatched = to_parish(gdf, props, acres, drain)
    print(f"{len(props)} soil survey areas, {len(data)} of {len(gdf)} parishes matched")
    if unmatched:
        print("Survey areas that matched no parish name (left out): " + "; ".join(unmatched))
    if len(data) < 0.5 * len(gdf):
        sys.exit("Fewer than half of the parishes matched a soil survey area; the soil layers are kept as they were.")
    build(gdf, data)


if __name__ == "__main__":
    main()
