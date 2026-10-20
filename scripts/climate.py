#!/usr/bin/env python3
"""
LaCADIAN site - air temperature and evaporative demand compared with normal, by parish.

Source: gridMET daily maximum and minimum temperature and reference evapotranspiration, averaged by parish by gridmet_extra.py.

Both layers use the same rules as the rainfall layer: the last three complete months, compared with the same three months in each year
of 1991-2020 (30 years); the colour is where this year ranks among those years.
  airtemp  mean air temperature = average of the daily maximum and minimum; shown as the difference from the 1991-2020 mean, in degrees C
  et0      evaporative demand = the total reference evapotranspiration of the three months; shown as a percentage of the 1991-2020 mean

Run:
  python scripts/climate.py
  python scripts/climate.py --self-test
"""
import argparse
import calendar
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOUNDARY_CREDIT, MON, load_parishes, pct_rank, write_layer, write_months  # noqa: E402

BUILD = 1
REF_FIRST, REF_LAST = 1991, 2020
WINDOW = 3
MIN_REF = 25
HISTORY_MONTHS = 12

TEMP_CATS = [
    {"key": "very_cool", "label": "Much cooler", "note": "coldest 10% of years", "color": "#2c7bb6"},
    {"key": "cool", "label": "Cooler", "note": "coldest 10 to 30% of years", "color": "#abd9e9"},
    {"key": "normal", "label": "Near normal", "note": "middle 40% of years", "color": "#f3efe4"},
    {"key": "warm", "label": "Warmer", "note": "warmest 10 to 30% of years", "color": "#fdae61"},
    {"key": "very_warm", "label": "Much warmer", "note": "warmest 10% of years", "color": "#d7191c"},
    {"key": "not_rated", "label": "Not rated", "note": "too few years or days missing", "color": "#bdbdbd"},
]
ET_CATS = [
    {"key": "very_low", "label": "Much lower demand", "note": "lowest 10% of years", "color": "#2166ac"},
    {"key": "low", "label": "Lower demand", "note": "lowest 10 to 30% of years", "color": "#92c5de"},
    {"key": "normal", "label": "Near normal", "note": "middle 40% of years", "color": "#f3efe4"},
    {"key": "high", "label": "Higher demand", "note": "highest 10 to 30% of years", "color": "#e08214"},
    {"key": "very_high", "label": "Much higher demand", "note": "highest 10% of years", "color": "#8c510a"},
    {"key": "not_rated", "label": "Not rated", "note": "too few years or days missing", "color": "#bdbdbd"},
]


def category(p, keys):
    """Rank among reference years (0 = lowest) -> category key from `keys` (5 names, low to high)."""
    if p <= 10:
        return keys[0]
    if p <= 30:
        return keys[1]
    if p < 70:
        return keys[2]
    if p < 90:
        return keys[3]
    return keys[4]


def ymi(y, m):
    return y * 12 + (m - 1)


def ymo(i):
    return i // 12, i % 12 + 1


def monthly(dates, x):
    """Complete months only -> {month index: (sum[parish], days)}. A parish with a missing day in the month gets NaN."""
    years = np.array([int(d[:4]) for d in dates])
    months = np.array([int(d[5:7]) for d in dates])
    out = {}
    for y, m in sorted({(a, b) for a, b in zip(years.tolist(), months.tolist())}):
        idx = np.nonzero((years == y) & (months == m))[0]
        if len(idx) != calendar.monthrange(y, m)[1]:
            continue
        out[ymi(y, m)] = (x[idx].sum(axis=0), len(idx))
    return out


def window_value(mon, end, how, width=WINDOW):
    if any((end - k) not in mon for k in range(width)):
        return None
    s = sum(mon[end - k][0] for k in range(width))
    return s / sum(mon[end - k][1] for k in range(width)) if how == "mean" else s


def label_for(end):
    y, m = ymo(end)
    ya, ma = ymo(end - WINDOW + 1)
    return f"{MON[ma - 1]}–{MON[m - 1]} {y}" if ya == y else f"{MON[ma - 1]} {ya}–{MON[m - 1]} {y}"


def assess(mon, end, how, width=WINDOW):
    """-> (current[parish], normal[parish], percentile[parish], n reference years[parish]) or None."""
    cur = window_value(mon, end, how, width)
    if cur is None:
        return None
    m = ymo(end)[1]
    refs = [w for w in (window_value(mon, ymi(ry, m), how, width) for ry in range(REF_FIRST, REF_LAST + 1)) if w is not None]
    n = len(cur)
    normal, pc, nref = (np.full(n, np.nan) for _ in range(3))
    if refs:
        ref = np.stack(refs)
        for i in range(n):
            col = ref[:, i][~np.isnan(ref[:, i])]
            if len(col) >= MIN_REF and not np.isnan(cur[i]):
                normal[i], pc[i], nref[i] = col.mean(), pct_rank(cur[i], col), len(col)
    return cur, normal, pc, nref


def f_text(c):
    return f"{c * 9 / 5 + 32:.0f} °F"


def build_pair(gdf, dates, tmax, tmin, pet):
    if tmax is not None and tmin is not None:
        n = min(len(tmax), len(tmin))
        build_temp(gdf, dates[:n], tmax[:n], tmin[:n])
    if pet is not None:
        build_et(gdf, dates, pet)


def build_temp(gdf, dates, tmax, tmin):
    t = (tmax + tmin) / 2.0
    if np.nanmedian(t) > 200:
        t = t - 273.15                                         # gridMET gives kelvin
    mon = monthly(dates, t)
    ends = [i for i in sorted(mon) if window_value(mon, i, "mean") is not None]
    if not ends:
        print("airtemp: not enough complete months yet")
        return
    end = ends[-1]
    cur, normal, pc, nref = assess(mon, end, "mean")
    label = label_for(end)
    y, m = ymo(end)
    keys = ["very_cool", "cool", "normal", "warm", "very_warm"]
    names = {c["key"]: c["label"] for c in TEMP_CATS}
    hist = []
    for k in range(HISTORY_MONTHS - 1, -1, -1):
        r = assess(mon, end - k, "mean", 1)
        hist.append(r)
    one = hist[-1]
    parishes = {}
    for i, row in gdf.iterrows():
        pid = row["id"]
        if np.isnan(pc[i]):
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "Not enough temperature record to rate this parish.", "tip": "Not rated", "rows": [], "rv": None}
            continue
        d = cur[i] - normal[i]
        cat = category(pc[i], keys)
        rows = [[f"Mean temperature, {label}", f"{cur[i]:.1f} °C ({f_text(cur[i])})"], ["Normal for these months (1991–2020)", f"{normal[i]:.1f} °C ({f_text(normal[i])})"],
                ["Earlier years that were cooler", f"{round(pc[i] / 100 * nref[i])} of {int(nref[i])}"]]
        if one is not None and not np.isnan(one[0][i]) and not np.isnan(one[1][i]):
            rows.append([f"Last month ({MON[m - 1]})", f"{one[0][i] - one[1][i]:+.1f} °C from normal"])
        parishes[pid] = {
            "name": row["name"], "cat": cat, "rv": round(float(d), 2), "big": f"{d:+.1f} °C",
            "big_note": f"compared with the normal mean temperature, {label} ({d * 9 / 5:+.1f} °F)", "tip": f"{names[cat]} · {d:+.1f} °C",
            "rows": rows,
            "v": [None if (h is None or np.isnan(h[2][i]) or np.isnan(h[1][i])) else round(float(h[0][i] - h[1][i]), 2) for h in hist],
            "c": ["not_rated" if (h is None or np.isnan(h[2][i])) else category(h[2][i], keys) for h in hist]}
    rows_m = []
    for e in ends:
        r = assess(mon, e, "mean")
        if r is None:
            continue
        yy, mm = ymo(e)
        rows_m.append((f"{yy}-{mm:02d}", label_for(e), list(r[0] - r[1]), [None if np.isnan(x) else category(x, keys) for x in r[2]]))
    write_months("airtemp", list(gdf["id"]), rows_m, [c["key"] for c in TEMP_CATS], "not_rated", "against the same months in 1991–2020", "{v} °C",
                 "compared with the normal mean temperature, {label}", "{cat} · {v} °C", "Difference from normal (°C)", offset=0, suffix=" °C", decimals=1, plus=True)
    ranked = int((~np.isnan(pc)).sum())
    print(f"air temperature, {label}: {ranked} of {len(gdf)} parishes rated; mean difference {np.nanmean(cur - normal):+.2f} °C")
    write_layer("airtemp", {
        "label": "Air temperature", "title": "Air temperature compared with normal", "subtitle": f"{label}, against the same months in 1991–2020",
        "source": "gridMET daily maximum and minimum temperature, averaged by parish", "demo": False, "build": BUILD, "categories": TEMP_CATS,
        "rank": {"high": "Warmest compared with normal", "low": "Coolest compared with normal", "note": "Ranked by the difference from the 1991–2020 mean temperature (°C)."},
        "how": (f"Each parish shows how far the average air temperature of the last three complete months ({label}) is from the average of the same months in 1991–2020. "
                "The mean temperature is the average of each day's maximum and minimum. The colour is where this year ranks among the 30 normal years: "
                "\"much warmer\" means among the warmest 10%, and the same in reverse for \"cooler\". Click a parish for the figures and the last 12 months."),
        "limits": [
            "gridMET is a 4 km grid that blends PRISM, which is built from weather stations, with a land-model reanalysis. It is an estimate, not a thermometer reading.",
            "The value for a parish is the mean of the grid cells inside it.",
            "Mean temperature hides hot afternoons and cool nights. It does not count heat days or frost.",
            "The newest days are provisional and are revised for a few weeks. A month is used only when every day of it is in the record.",
        ],
        "credits": [{"text": "Temperature: gridMET, Abatzoglou, J.T. (2013), Int. J. Climatology 33: 121-131", "url": "https://www.climatologylab.org/gridmet.html"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 4, "unit": "°C vs normal", "x": [MON[ymo(end - HISTORY_MONTHS + 1 + k)[1] - 1] for k in range(HISTORY_MONTHS)],
                  "caption": "Mean temperature, difference from normal, each of the last 12 months", "top": "warmer than normal", "bottom": "cooler"},
        "parishes": parishes})


def build_et(gdf, dates, pet):
    mon = monthly(dates, pet)
    ends = [i for i in sorted(mon) if window_value(mon, i, "sum") is not None]
    if not ends:
        print("et0: not enough complete months yet")
        return
    end = ends[-1]
    cur, normal, pc, nref = assess(mon, end, "sum")
    label = label_for(end)
    y, m = ymo(end)
    keys = ["very_low", "low", "normal", "high", "very_high"]
    names = {c["key"]: c["label"] for c in ET_CATS}
    hist = [assess(mon, end - k, "sum", 1) for k in range(HISTORY_MONTHS - 1, -1, -1)]
    pctn = cur / normal * 100
    parishes = {}
    for i, row in gdf.iterrows():
        pid = row["id"]
        if np.isnan(pc[i]) or not normal[i] > 0:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "Not enough record to rate this parish.", "tip": "Not rated", "rows": [], "rv": None}
            continue
        cat = category(pc[i], keys)
        parishes[pid] = {
            "name": row["name"], "cat": cat, "rv": round(float(pctn[i]), 1), "big": f"{pctn[i]:.0f}%",
            "big_note": f"of normal evaporative demand, {label}", "tip": f"{names[cat]} · {pctn[i]:.0f}% of normal",
            "rows": [[f"Evaporative demand, {label}", f"{cur[i]:.0f} mm"], ["Normal for these months (1991–2020)", f"{normal[i]:.0f} mm"],
                     ["Earlier years with less demand", f"{round(pc[i] / 100 * nref[i])} of {int(nref[i])}"]],
            "v": [None if (h is None or np.isnan(h[2][i]) or not h[1][i] > 0) else round(float(h[0][i] / h[1][i] * 100 - 100), 1) for h in hist],
            "c": ["not_rated" if (h is None or np.isnan(h[2][i])) else category(h[2][i], keys) for h in hist]}
    rows_m = []
    for e in ends:
        r = assess(mon, e, "sum")
        if r is None:
            continue
        yy, mm = ymo(e)
        with np.errstate(divide="ignore", invalid="ignore"):
            rows_m.append((f"{yy}-{mm:02d}", label_for(e), list(r[0] / r[1] * 100), [None if np.isnan(x) else category(x, keys) for x in r[2]]))
    write_months("et0", list(gdf["id"]), rows_m, [c["key"] for c in ET_CATS], "not_rated", "against the same months in 1991–2020", "{v}%",
                 "of normal evaporative demand, {label}", "{cat} · {v}% of normal", "Evaporative demand as % of normal")
    print(f"evaporative demand, {label}: {int((~np.isnan(pc)).sum())} of {len(gdf)} parishes rated; mean {np.nanmean(pctn):.0f}% of normal")
    write_layer("et0", {
        "label": "Evaporative demand", "title": "Evaporative demand (ET₀) compared with normal", "subtitle": f"{label}, against the same months in 1991–2020",
        "source": "gridMET reference evapotranspiration (grass), averaged by parish", "demo": False, "build": BUILD, "categories": ET_CATS,
        "rank": {"high": "Highest demand compared with normal", "low": "Lowest demand compared with normal", "note": "Ranked by evaporative demand as a percentage of normal."},
        "how": (f"Reference evapotranspiration (ET₀) is how much water a well-watered grass surface would lose to the air in a day, worked out from temperature, sunshine, humidity and wind. "
                f"Each parish shows the total for the last three complete months ({label}) compared with the same months in 1991–2020. "
                "A high figure means the air is pulling more water from soil and plants than usual, which dries the soil faster for the same rain."),
        "limits": [
            "ET₀ is a demand figure for a reference grass surface, not the water a particular crop or field actually uses.",
            "It comes from gridMET, a 4 km grid that blends PRISM with a land-model reanalysis, using modelled sunshine, humidity and wind. It is an estimate.",
            "The value for a parish is the mean of the grid cells inside it.",
            "High demand is not drought by itself. Read it with the rainfall and soil-moisture layers.",
        ],
        "credits": [{"text": "Evaporative demand: gridMET, Abatzoglou, J.T. (2013), Int. J. Climatology 33: 121-131", "url": "https://www.climatologylab.org/gridmet.html"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 50, "unit": "% vs normal", "x": [MON[ymo(end - HISTORY_MONTHS + 1 + k)[1] - 1] for k in range(HISTORY_MONTHS)],
                  "caption": "Evaporative demand each of the last 12 months", "top": "higher than normal", "bottom": "lower"},
        "parishes": parishes})


def self_test():
    import datetime as dt
    import json
    import tempfile
    import geopandas as gpd
    import common
    from shapely.geometry import box
    g = gpd.GeoDataFrame({"id": ["22001", "22003"], "name": ["A", "B"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs=4326)
    d, days = dt.date(1991, 1, 1), []
    while d <= dt.date(2026, 9, 30):
        days.append(d)
        d += dt.timedelta(1)
    dates = [x.isoformat() for x in days]
    tmax = np.full((len(days), 2), 300.0, "float32")           # kelvin
    tmin = np.full((len(days), 2), 290.0, "float32")
    pet = np.full((len(days), 2), 4.0, "float32")
    last = [i for i, x in enumerate(days) if x >= dt.date(2026, 7, 1)]
    tmax[last, 0] += 3; tmin[last, 0] += 3                    # parish A: 3 degrees warmer
    pet[last, 1] = 6.0                                         # parish B: 50% more demand
    mon = monthly(dates, (tmax + tmin) / 2)
    assert window_value(mon, ymi(2026, 9), "mean") is not None and ymi(2026, 10) not in mon
    cur, normal, pc, nref = assess(mon, ymi(2026, 9), "mean")
    assert abs((cur[0] - normal[0]) - 3.0) < 1e-3 and abs(cur[1] - normal[1]) < 1e-3 and pc[0] == 100 and nref[0] == 30
    assert category(100, ["a", "b", "c", "d", "e"]) == "e" and category(0, list("abcde")) == "a" and category(50, list("abcde")) == "c"
    assert label_for(ymi(2026, 9)) == "Jul–Sep 2026" and label_for(ymi(2026, 1)) == "Nov 2025–Jan 2026"
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        build_pair(g, dates, tmax, tmin, pet)
        a = json.loads((Path(tmp) / "airtemp.json").read_text())
        assert a["parishes"]["22001"]["cat"] == "very_warm" and abs(a["parishes"]["22001"]["rv"] - 3.0) < 0.01 and a["parishes"]["22003"]["cat"] == "normal"
        e = json.loads((Path(tmp) / "et0.json").read_text())
        assert e["parishes"]["22003"]["cat"] == "very_high" and round(e["parishes"]["22003"]["rv"]) == 150
        mo = json.loads((Path(tmp) / "airtemp_months.json").read_text())
        assert mo["offset"] == 0 and mo["parishes"]["22001"]["v"][-1] == 3.0
    common.DATA = old
    print("self-test passed: 4 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    import gridmet_extra as ge
    z = {k: ge.load(k) for k in ("tmmx", "tmmn", "pet")}
    if all(v is None for v in z.values()):
        sys.exit("No temperature or evaporative-demand record yet (run scripts/gridmet_extra.py first).")
    gdf = load_parishes()
    t = z["tmmx"], z["tmmn"]
    if t[0] is not None and t[1] is not None:
        common_dates = sorted(set(t[0]["dates"].tolist()) & set(t[1]["dates"].tolist()))
        ix = {d: i for i, d in enumerate(t[0]["dates"].tolist())}
        iy = {d: i for i, d in enumerate(t[1]["dates"].tolist())}
        tmax = np.stack([t[0]["values"][ix[d]] for d in common_dates])
        tmin = np.stack([t[1]["values"][iy[d]] for d in common_dates])
        build_temp(gdf, common_dates, tmax, tmin)
    else:
        print("No temperature record yet; the air temperature layer is not built.")
    if z["pet"] is not None:
        build_et(gdf, z["pet"]["dates"].tolist(), z["pet"]["values"])
    else:
        print("No evaporative-demand record yet; that layer is not built.")


if __name__ == "__main__":
    main()
