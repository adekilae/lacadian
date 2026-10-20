#!/usr/bin/env python3
"""
LaCADIAN site - rainfall compared with normal, by parish.

Source: gridMET daily precipitation (4 km), averaged by parish by scripts/gridmet.py (cache/gridmet_rain.npz).

Indicator: rain over the last three complete months, compared with the same three months in each year of the
1991-2020 normal period (30 years). Three months is used because, in the Tinga Lens tests, three-month rainfall
matched soil moisture better than one month does. The pop-up also gives the last single month.

Rules (settings are at the top of this file):
  Complete month  every day of the month is in the record; a month with a missing day is not used
  Normal          the mean of the same three months in 1991-2020
  Colour          where this year ranks among those 30 years (ties count half): driest 10% = "very dry",
                  10-30% = "dry", 30-70% = "near normal", 70-90% = "wet", wettest 10% = "very wet"

Run:
  python scripts/rain.py
  python scripts/rain.py --self-test
"""
import argparse
import calendar
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import write_months, BOUNDARY_CREDIT, MON, WETNESS, load_parishes, pct_rank, wetness_category, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
REF_FIRST, REF_LAST = 1991, 2020        # the normal period
WINDOW = 3                              # months added up
MIN_REF = 25                            # reference years needed before a parish is rated
HISTORY_MONTHS = 12                     # months shown in the pop-up chart
# --------------------------------------------------------------------------


def ym_index(y, m):
    return y * 12 + (m - 1)


def ym_of(i):
    return i // 12, i % 12 + 1


def monthly_totals(dates, rain):
    """Complete months only -> {month index: total[parish]}. A parish with a missing day in the month gets NaN."""
    years = np.array([int(d[:4]) for d in dates])
    months = np.array([int(d[5:7]) for d in dates])
    out = {}
    for y, m in sorted({(a, b) for a, b in zip(years.tolist(), months.tolist())}):
        idx = np.nonzero((years == y) & (months == m))[0]
        if len(idx) != calendar.monthrange(y, m)[1]:
            continue
        out[ym_index(y, m)] = rain[idx].sum(axis=0)
    return out


def window_total(tot, end):
    """Sum of the WINDOW months ending at month index `end`, or None if one of them is missing."""
    if any((end - k) not in tot for k in range(WINDOW)):
        return None
    return sum(tot[end - k] for k in range(WINDOW))


def assess(tot, end, ref_years=None):
    """-> (current[parish], normal[parish], percent of normal, percentile, n reference years[parish]) or None."""
    cur = window_total(tot, end)
    if cur is None:
        return None
    y, m = ym_of(end)
    refs = []
    for ry in (ref_years or range(REF_FIRST, REF_LAST + 1)):
        w = window_total(tot, ym_index(ry, m))
        if w is not None:
            refs.append(w)
    n_par = len(cur)
    normal, pct, pctile, nref = (np.full(n_par, np.nan) for _ in range(4))
    if not refs:
        return cur, normal, pct, pctile, nref
    ref = np.stack(refs)
    cnt = (~np.isnan(ref)).sum(axis=0)
    for i in range(n_par):
        if cnt[i] >= MIN_REF and not np.isnan(cur[i]):
            col = ref[:, i][~np.isnan(ref[:, i])]
            normal[i] = col.mean()
            pct[i] = cur[i] / normal[i] * 100 if normal[i] > 0 else np.nan
            pctile[i] = pct_rank(cur[i], col)
            nref[i] = len(col)
    return cur, normal, pct, pctile, nref


def month_label(end):
    y, m = ym_of(end)
    a = end - WINDOW + 1
    ya, ma = ym_of(a)
    return f"{MON[ma - 1]}–{MON[m - 1]} {y}" if ya == y else f"{MON[ma - 1]} {ya}–{MON[m - 1]} {y}"


def self_test():
    # a record where every day of 1991-2020 has 2 mm, and the latest months are wetter / drier
    import datetime as dt
    d0, days = dt.date(1991, 1, 1), []
    d = d0
    while d <= dt.date(2026, 9, 30):
        days.append(d)
        d += dt.timedelta(1)
    dates = [x.isoformat() for x in days]
    rain = np.full((len(days), 3), 2.0, "float32")
    rain[:, 2] = 1.0
    last3 = [i for i, x in enumerate(days) if x >= dt.date(2026, 7, 1)]
    rain[last3, 0] = 4.0                                 # parish 0: double the normal
    rain[last3, 1] = 0.0                                 # parish 1: no rain at all
    # a 29-day February with a missing day is skipped
    j = dates.index("2005-02-10")
    rain[j, 2] = np.nan
    tot = monthly_totals(dates, rain)
    assert ym_index(2005, 2) in tot and np.isnan(tot[ym_index(2005, 2)][2]) and not np.isnan(tot[ym_index(2005, 2)][0])
    assert ym_index(2026, 9) in tot and ym_index(2026, 10) not in tot
    end = ym_index(2026, 9)
    assert round(float(window_total(tot, end)[0]), 1) == round(4.0 * (31 + 31 + 30), 1)
    cur, normal, pct, pctile, nref = assess(tot, end)
    assert round(pct[0]) == 200 and round(pct[1]) == 0 and round(pct[2]) == 100, pct         # parish 2 is at its own normal (1 mm/day all along)
    assert pctile[0] == 100 and pctile[1] == 0 and nref[0] == 30
    assert wetness_category(pctile[0]) == "very_wet" and wetness_category(pctile[1]) == "very_dry"
    # a window that crosses the new year uses the right reference months (Nov-Jan ends in January)
    tot2 = {ym_index(y, m): np.array([float(y)]) for y in range(1990, 2028) for m in range(1, 13)}
    w = window_total(tot2, ym_index(2026, 1))
    assert w[0] == 2025 + 2025 + 2026, w
    # a missing month makes the window empty
    del tot2[ym_index(2026, 12)]
    assert window_total(tot2, ym_index(2026, 12)) is None
    assert month_label(ym_index(2026, 9)) == "Jul–Sep 2026" and month_label(ym_index(2026, 1)) == "Nov 2025–Jan 2026"
    print("self-test passed: 6 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    from gridmet import load_cache
    z = load_cache()
    if z is None:
        sys.exit("No gridMET rainfall record yet (run scripts/gridmet.py first).")
    gdf = load_parishes()
    build(gdf, z["dates"].tolist(), z["rain"])


def build(gdf, dates, rain):
    tot = monthly_totals(dates, rain)
    ends = [i for i in sorted(tot) if window_total(tot, i) is not None]
    if not ends:
        sys.exit("Not enough complete months of rainfall yet.")
    end = ends[-1]
    now = assess(tot, end)
    cur, normal, pct, pctile, nref = now
    y, m = ym_of(end)
    label = month_label(end)
    # the last single month and the 12-month history, each against its own normal for that month
    hist = []
    for k in range(HISTORY_MONTHS - 1, -1, -1):
        mi = end - k
        if mi not in tot:
            hist.append(None)
            continue
        refs = [tot[ym_index(ry, ym_of(mi)[1])] for ry in range(REF_FIRST, REF_LAST + 1) if ym_index(ry, ym_of(mi)[1]) in tot]
        if len(refs) < MIN_REF:
            hist.append(None)
            continue
        ref = np.stack(refs)
        hist.append((tot[mi], ref.mean(axis=0), np.array([pct_rank(tot[mi][i], ref[:, i]) if not np.isnan(tot[mi][i]) else np.nan
                                                          for i in range(ref.shape[1])])))
    one = hist[-1]
    rated = int((~np.isnan(pctile)).sum())
    print(f"latest three months: {label}; {rated} of {len(gdf)} parishes rated; mean {np.nanmean(pct):.0f}% of normal")

    notes = ["driest 10% of years", "driest 10 to 30% of years", "middle 40% of years", "wettest 10 to 30% of years", "wettest 10% of years"]
    cats = [dict(c, note=t) for c, t in zip(WETNESS, notes)] + [{"key": "not_rated", "label": "Not rated", "note": "too few years or days missing", "color": "#bdbdbd"}]
    names = {c["key"]: c["label"] for c in cats}
    parishes = {}
    for i, row in gdf.iterrows():
        pid = row["id"]
        if np.isnan(pctile[i]):
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "big_note": "Not enough rainfall record to rate this parish.",
                             "tip": "Not rated", "rows": [], "rv": None, "v": [], "c": []}
            continue
        cat = wetness_category(pctile[i])
        rows = [[f"Rain, {label}", f"{cur[i]:.0f} mm"], [f"Normal for these months (1991–2020)", f"{normal[i]:.0f} mm"],
                ["Earlier years that were drier", f"{round(pctile[i] / 100 * nref[i])} of {int(nref[i])}"]]
        if one is not None and not np.isnan(one[0][i]):
            nm = one[1][i]
            rows.append([f"Last month ({MON[m - 1]})", f"{one[0][i]:.0f} mm" + (f" ({one[0][i] / nm * 100:.0f}% of normal)" if nm > 0 else "")])
        parishes[pid] = {
            "name": row["name"], "cat": cat, "big": f"{pct[i]:.0f}%",
            "big_note": f"of normal rainfall, {label}", "tip": f"{names[cat]} · {pct[i]:.0f}% of normal",
            "rows": rows, "rv": round(float(pct[i]), 1),
            "v": [None if (h is None or np.isnan(h[2][i]) or h[1][i] <= 0) else round(float(h[0][i] / h[1][i] * 100 - 100), 1) for h in hist],
            "c": ["not_rated" if (h is None or np.isnan(h[2][i])) else wetness_category(h[2][i]) for h in hist],
        }
    rows_m = []
    for e in ends:
        r = assess(tot, e)
        if r is None:
            continue
        _, _, pc, pt, _ = r
        yy, mm = ym_of(e)
        rows_m.append((f"{yy}-{mm:02d}", month_label(e), list(pc), [None if np.isnan(x) else wetness_category(x) for x in pt]))
    write_months("rain", list(gdf["id"]), rows_m, [c["key"] for c in cats], "not_rated", "against the same months in 1991–2020",
                 "{v}%", "of normal rainfall, {label}", "{cat} · {v}% of normal", "Rain as % of normal")
    write_layer("rain", {
        "label": "Rainfall", "title": "Rainfall compared with normal", "subtitle": f"{label}, against the same months in 1991–2020",
        "source": "gridMET daily precipitation, averaged by parish", "demo": False, "build": BUILD, "categories": cats,
        "validation": "rain",
        "rank": {"high": "Wettest compared with normal", "low": "Driest compared with normal", "note": "Ranked by rain as a percentage of normal."},
        "how": (f"Each parish shows the rain that fell over the last three complete months ({label}) compared with the same three months in each of "
                "the 30 years from 1991 to 2020. \"Very dry\" means this year ranks among the driest 10% of those years; \"dry\" the driest 30%; "
                "and the same in reverse for \"wet\" and \"very wet\". Click a parish for the amounts and the last 12 months."),
        "limits": [
            "gridMET is a 4 km grid made by blending PRISM, which is built from rain gauges, with a land-model reanalysis. It is an estimate, not a gauge reading.",
            "The value for a parish is the mean of the grid cells inside it. A storm that hit part of a large parish is smoothed out.",
            "The newest days are provisional and are revised for a few weeks. A month is used only when every day of it is in the record.",
            "Rain amounts are compared with the 1991–2020 normal, which was a particular 30 years. They do not say whether the soil or crops are short of water.",
            "The 'Check against the stations' table under the map compares gridMET with the rain gauges of the LaCADIAN stations where both have data.",
        ],
        "credits": [{"text": "Rainfall: gridMET, Abatzoglou, J.T. (2013), Int. J. Climatology 33: 121-131", "url": "https://www.climatologylab.org/gridmet.html"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 100, "unit": "% vs normal", "x": [MON[ym_of(end - HISTORY_MONTHS + 1 + k)[1] - 1] for k in range(HISTORY_MONTHS)],
                  "caption": "Rain each of the last 12 months", "top": "wetter than normal", "bottom": "drier"},
        "parishes": parishes,
    })


if __name__ == "__main__":
    main()
