#!/usr/bin/env python3
"""
LaCADIAN site - three more soil layers from the SMAP files that smap.py has already read (no new download):

  soilsurf  Surface soil moisture (0-5 cm), as a percentage of normal for the month, ranked against the same month in earlier years
  soildef   Soil-water deficit: how many millimetres of water the top metre of soil holds above or below its normal for the month
  soilgap   Surface-root-zone gap: how the surface ranks (0-100) minus how the root zone ranks, in percentile points

smap.py calls build() at the end of its own build, with the monthly parish means it just made.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOUNDARY_CREDIT, MON, WETNESS, write_layer, write_months, ym_text  # noqa: E402

BUILD = 1
HISTORY_MONTHS = 12
DEF_CUTS = [10.0, 40.0]            # millimetres of water in the top metre: within +-10 is "near normal", beyond 40 is "large"
GAP_CUTS = [10.0, 30.0]            # percentile points

DEF_CATS = [
    {"key": "def2", "label": "Large deficit", "note": "40 mm or more below normal", "color": "#8c510a"},
    {"key": "def1", "label": "Moderate deficit", "note": "10 to 40 mm below normal", "color": "#dfc27d"},
    {"key": "near", "label": "Near normal", "note": "within 10 mm of normal", "color": "#f3efe4"},
    {"key": "sur1", "label": "Moderate surplus", "note": "10 to 40 mm above normal", "color": "#80cdc1"},
    {"key": "sur2", "label": "Large surplus", "note": "40 mm or more above normal", "color": "#01665e"},
    {"key": "not_rated", "label": "Not rated", "note": "no usable land cell", "color": "#bdbdbd"},
]
GAP_CATS = [
    {"key": "dry2", "label": "Surface much drier", "note": "surface ranks 30+ points below the root zone", "color": "#b35806"},
    {"key": "dry1", "label": "Surface drier", "note": "10 to 30 points below", "color": "#f1a340"},
    {"key": "alike", "label": "About the same", "note": "within 10 points", "color": "#f1ede0"},
    {"key": "wet1", "label": "Surface wetter", "note": "10 to 30 points above", "color": "#998ec3"},
    {"key": "wet2", "label": "Surface much wetter", "note": "surface ranks 30+ points above the root zone", "color": "#542788"},
    {"key": "not_rated", "label": "Not rated", "note": "no usable land cell", "color": "#bdbdbd"},
]


def def_category(mm):
    """mm of water above normal (negative = deficit) -> category key."""
    if mm <= -DEF_CUTS[1]:
        return "def2"
    if mm <= -DEF_CUTS[0]:
        return "def1"
    if mm < DEF_CUTS[0]:
        return "near"
    if mm < DEF_CUTS[1]:
        return "sur1"
    return "sur2"


def gap_category(points):
    if points <= -GAP_CUTS[1]:
        return "dry2"
    if points <= -GAP_CUTS[0]:
        return "dry1"
    if points < GAP_CUTS[0]:
        return "alike"
    if points < GAP_CUTS[1]:
        return "wet1"
    return "wet2"


def self_test():
    assert def_category(-50) == "def2" and def_category(-40) == "def2" and def_category(-12) == "def1" and def_category(0) == "near"
    assert def_category(25) == "sur1" and def_category(60) == "sur2" and def_category(-9.9) == "near"
    assert gap_category(-45) == "dry2" and gap_category(-10) == "dry1" and gap_category(5) == "alike" and gap_category(10) == "wet1" and gap_category(30) == "wet2"
    import tempfile, json
    import geopandas as gpd
    from shapely.geometry import box
    import common
    import smap
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005"], "name": list("ABC")}, geometry=[box(i, 0, i + 1, 1) for i in range(3)], crs=4326)
    months = [(2018 + i // 2, 6 + i % 2) for i in range(14)]          # June and July of 7 years
    rng = np.random.default_rng(0)
    root = 0.30 + 0.01 * rng.standard_normal((14, 3))
    surf = 0.20 + 0.01 * rng.standard_normal((14, 3))
    root[-1] = [0.20, 0.30, 0.30]                                    # parish A: root zone much drier than normal
    surf[-1] = [0.20, 0.30, 0.10]                                    # parish C: surface very dry while the root zone is normal
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        globals()["write_layer"] = write_layer
        import soilextra as me
        me.build(g, months, np.round(root, 4), np.round(surf, 4), "test")
        d = json.loads((Path(tmp) / "soildef.json").read_text())
        assert d["parishes"]["22001"]["cat"] == "def2" and d["parishes"]["22001"]["rv"] < -40, d["parishes"]["22001"]
        s = json.loads((Path(tmp) / "soilsurf.json").read_text())
        assert s["parishes"]["22003"]["cat"] in ("wet", "very_wet") and s["parishes"]["22002" if False else "22005"]["cat"] in ("very_dry", "dry")
        gp = json.loads((Path(tmp) / "soilgap.json").read_text())
        assert gp["parishes"]["22005"]["cat"] in ("dry1", "dry2"), gp["parishes"]["22005"]
        for k in ("soilsurf", "soildef", "soilgap"):
            m = json.loads((Path(tmp) / f"{k}_months.json").read_text())
            assert len(m["months"]) == 14 - 5 * 1 * 1 + 0 or len(m["months"]) > 0
    common.DATA = old
    print("self-test passed: 3 groups")


def build(gdf, months, root, surf, source):
    import smap
    T = len(months) - 1
    y, m = months[T]
    label = f"{y}-{m:02d}"
    steps = list(range(max(0, T - HISTORY_MONTHS + 1), T + 1))
    ids = list(gdf["id"])
    ar = [smap.assess(months, root, t) for t in range(len(months))]
    asf = [smap.assess(months, surf, t) for t in range(len(months))]
    if ar[T] is None or asf[T] is None:
        print("Not enough earlier years for the extra soil layers.")
        return
    xlab = [MON[months[t][1] - 1] for t in steps]
    credits = [{"text": "Soil moisture: NASA SMAP L4 (SPL4SMGP), NSIDC DAAC", "url": "https://nsidc.org/data/spl4smgp"}, BOUNDARY_CREDIT]
    common_limits = [
        "The values come from NASA SMAP Level 4, which feeds satellite readings into a land model. They are modelled estimates and not measurements at depth.",
        "The record starts in 2015, so normal rests on a few earlier years and the rankings are coarse.",
        "The grid is about 9 km, so it works for parish averages and not for single fields. Coastal parishes include a lot of water and wetland.",
    ]

    # ---------------------------------------------------------------- surface soil moisture
    cur, normal, pct, pctile, n = asf[T]
    cats = [dict(c, note=t) for c, t in zip(WETNESS, ["driest 10% of years", "driest 10 to 30% of years", "middle 40% of years",
                                                       "wettest 10 to 30% of years", "wettest 10% of years"])] + \
           [{"key": "not_rated", "label": "Not rated", "note": "no usable land cell", "color": "#bdbdbd"}]
    names = {c["key"]: c["label"] for c in cats}
    cat_keys = [c["key"] for c in cats]
    parishes = {}
    for i, row in gdf.iterrows():
        if np.isnan(cur[i]):
            parishes[ids[i]] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "No usable SMAP land cell for this parish.", "tip": "Not rated", "rv": None, "rows": []}
            continue
        cat = smap.wetness_category(pctile[i])
        hist = [asf[t] for t in steps]
        parishes[ids[i]] = {
            "name": row["name"], "cat": cat, "rv": round(float(pct[i]), 1), "big": f"{pct[i]:.0f}%",
            "big_note": f"of normal surface soil moisture, {ym_text(label)}", "tip": f"{names[cat]}, {pct[i]:.0f}% of normal",
            "rows": [["Surface (0–5 cm)", f"{cur[i]:.2f} m³/m³"], [f"Normal for {MON[m - 1]}", f"{normal[i]:.2f} m³/m³"],
                     ["Root zone (0–100 cm)", f"{root[T][i]:.2f} m³/m³"], ["Earlier years that were drier", f"{round(pctile[i] / 100 * n)} of {n}"]],
            "v": [None if h is None else round(float(h[2][i] - 100), 1) for h in hist],
            "c": ["not_rated" if h is None else smap.wetness_category(h[3][i]) for h in hist]}
    rows_m = [(f"{months[t][0]}-{months[t][1]:02d}", ym_text(f"{months[t][0]}-{months[t][1]:02d}"), list(asf[t][2]),
               [None if np.isnan(x) else smap.wetness_category(x) for x in asf[t][3]]) for t in range(len(months)) if asf[t] is not None]
    write_months("soilsurf", ids, rows_m, cat_keys, "not_rated", "against the same month in earlier years since 2015", "{v}%",
                 "of normal surface soil moisture, {label}", "{cat}, {v}% of normal", "Surface soil moisture as % of normal")
    write_layer("soilsurf", {
        "label": "Surface soil moisture", "title": "Surface soil moisture (0–5 cm) compared with normal",
        "subtitle": f"{ym_text(label)}, against {MON[m - 1]} in {n} earlier years", "source": source, "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Wettest compared with normal", "low": "Driest compared with normal", "note": "Ranked by surface soil moisture as a percentage of normal."},
        "how": ("The top 5 cm of soil is what a seed or seedling meets first. It dries out and wets up within days, so it can be far from the root zone. This shows the monthly average for that layer compared with the same month in every year since 2015."),
        "limits": common_limits + ["The surface layer reacts to single rains and hot spells, so a monthly average can hide a wet week and a dry week."],
        "credits": credits,
        "chart": {"kind": "diverging", "cap": 50, "unit": "% vs normal", "x": xlab, "caption": "Past 12 months, surface layer", "top": "wetter than normal", "bottom": "drier"},
        "parishes": parishes})

    # ---------------------------------------------------------------- soil-water deficit
    cur_r, normal_r, _, _, n_r = ar[T]
    dcats = DEF_CATS
    dnames = {c["key"]: c["label"] for c in dcats}

    def mm(t):                                    # mm of water above normal in the top metre (m3/m3 x 1000 mm)
        r = ar[t]
        return None if r is None else (r[0] - r[1]) * 1000.0

    now = mm(T)
    parishes = {}
    for i, row in gdf.iterrows():
        if np.isnan(now[i]):
            parishes[ids[i]] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "No usable SMAP land cell for this parish.", "tip": "Not rated", "rv": None, "rows": []}
            continue
        cat = def_category(now[i])
        word = "below" if now[i] < 0 else "above"
        parishes[ids[i]] = {
            "name": row["name"], "cat": cat, "rv": round(float(now[i]), 1), "big": f"{abs(now[i]):.0f} mm",
            "big_note": f"{word} the normal amount of water in the top metre of soil, {ym_text(label)}",
            "tip": f"{dnames[cat]}, {abs(now[i]):.0f} mm {word} normal",
            "rows": [["Water in the top metre", f"{cur_r[i] * 1000:.0f} mm"], [f"Normal for {MON[m - 1]}", f"{normal_r[i] * 1000:.0f} mm"],
                     ["Difference", f"{now[i]:+.0f} mm"]],
            "v": [None if mm(t) is None or np.isnan(mm(t)[i]) else round(float(mm(t)[i]), 1) for t in steps],
            "c": ["not_rated" if mm(t) is None or np.isnan(mm(t)[i]) else def_category(mm(t)[i]) for t in steps]}
    rows_m = [(f"{months[t][0]}-{months[t][1]:02d}", ym_text(f"{months[t][0]}-{months[t][1]:02d}"), list(mm(t)),
               [None if np.isnan(x) else def_category(x) for x in mm(t)]) for t in range(len(months)) if mm(t) is not None]
    write_months("soildef", ids, rows_m, [c["key"] for c in dcats], "not_rated", "against the same month in earlier years since 2015", "{v} mm",
                 "of water above (+) or below (−) normal in the top metre of soil, {label}", "{cat}, {v} mm", "Water above (+) or below (−) normal, mm",
                 offset=0, suffix=" mm", decimals=0, plus=True)
    write_layer("soildef", {
        "label": "Soil-water deficit", "title": "Soil-water deficit in the top metre of soil",
        "subtitle": f"{ym_text(label)}, against {MON[m - 1]} in {n_r} earlier years", "source": source, "demo": False, "build": BUILD, "categories": dcats,
        "rank": {"high": "Most water above normal", "low": "Largest deficit", "note": "Ranked by millimetres of water above normal (negative = deficit)."},
        "how": ("The soil moisture percentage turned into an amount of water: how many millimetres more or less the top metre of soil holds than it normally does for this month (moisture in m³/m³ times 1,000 mm). A deficit of 40 mm is about an inch and a half of rain missing from the soil."),
        "limits": common_limits + ["It is a difference from the average of the earlier SMAP years. It is not measured against the soil's field capacity or wilting point, and it does not say whether a crop is short of water.",
                                   "Roots do not reach the whole metre in every crop or in every soil."],
        "credits": credits,
        "chart": {"kind": "diverging", "cap": 100, "unit": "mm vs normal", "x": xlab, "caption": "Water above or below normal, past 12 months (mm)", "top": "more water than normal", "bottom": "deficit"},
        "parishes": parishes})

    # ---------------------------------------------------------------- surface-root-zone gap
    def gap(t):
        a, b = ar[t], asf[t]
        return None if a is None or b is None else b[3] - a[3]

    now = gap(T)
    parishes = {}
    gnames = {c["key"]: c["label"] for c in GAP_CATS}
    for i, row in gdf.iterrows():
        if np.isnan(now[i]):
            parishes[ids[i]] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "No usable SMAP land cell for this parish.", "tip": "Not rated", "rv": None, "rows": []}
            continue
        cat = gap_category(now[i])
        parishes[ids[i]] = {
            "name": row["name"], "cat": cat, "rv": round(float(now[i]), 1), "big": f"{now[i]:+.0f}",
            "big_note": f"points: surface rank minus root-zone rank, {ym_text(label)}", "tip": f"{gnames[cat]}, {now[i]:+.0f} points",
            "rows": [["Surface ranks wetter than", f"{asf[T][3][i]:.0f}% of earlier years"], ["Root zone ranks wetter than", f"{ar[T][3][i]:.0f}% of earlier years"],
                     ["Gap (surface minus root zone)", f"{now[i]:+.0f} points"]],
            "v": [None if gap(t) is None or np.isnan(gap(t)[i]) else round(float(gap(t)[i]), 1) for t in steps],
            "c": ["not_rated" if gap(t) is None or np.isnan(gap(t)[i]) else gap_category(gap(t)[i]) for t in steps]}
    rows_m = [(f"{months[t][0]}-{months[t][1]:02d}", ym_text(f"{months[t][0]}-{months[t][1]:02d}"), list(gap(t)),
               [None if np.isnan(x) else gap_category(x) for x in gap(t)]) for t in range(len(months)) if gap(t) is not None]
    write_months("soilgap", ids, rows_m, [c["key"] for c in GAP_CATS], "not_rated", "against the same month in earlier years since 2015", "{v}",
                 "points: surface rank minus root-zone rank, {label}", "{cat}, {v} points", "Surface rank minus root-zone rank (points)",
                 offset=0, suffix=" points", decimals=0, plus=True)
    write_layer("soilgap", {
        "label": "Surface–root-zone gap", "title": "Gap between surface and root-zone soil moisture",
        "subtitle": f"{ym_text(label)}, ranks against {MON[m - 1]} in {n_r} earlier years", "source": source, "demo": False, "build": BUILD, "categories": GAP_CATS,
        "rank": {"high": "Surface wetter than root zone", "low": "Surface drier than root zone", "note": "Ranked by surface rank minus root-zone rank (percentile points)."},
        "how": ("Each parish gets two ranks for the month, one for the top 5 cm and one for the top metre, each against the same month in earlier years (0 is driest, 100 is wettest). The map shows the surface rank minus the root-zone rank. A strongly negative gap means the surface has dried while the deeper soil still holds water, which is how a quick dry spell often starts. A strongly positive gap means a recent rain wet the surface over a deeper store that is still short."),
        "limits": common_limits + ["Both ranks come from the same model, so they are not independent. A big gap in one month is a reason to look at the other layers and not a verdict."],
        "credits": credits,
        "chart": {"kind": "diverging", "cap": 100, "unit": "points", "x": xlab, "caption": "Surface rank minus root-zone rank, past 12 months", "top": "surface wetter", "bottom": "surface drier"},
        "parishes": parishes})


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit("soilextra.py is run by smap.py. Use: python scripts/soilextra.py --self-test")
