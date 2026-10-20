#!/usr/bin/env python3
"""
LaCADIAN site - dry spells by parish (experimental).

For every parish: what was the longest run of dry days in the last 60 days, and is that longer or shorter than
usual for the same 60 calendar days? It uses the daily gridMET rainfall that scripts/gridmet.py saved
(cache/gridmet_rain.npz), so it downloads nothing.

Rules (settings are at the top of this file):
  Dry day      a day with less than 1 mm of rain (the same as the station pages); a day with no data ends a run
  Window       the last SPAN days up to the newest day with data, and the same calendar days in each year of 1991-2020
  Usual        the median of the longest dry spell in those years
  Colour       where this year's longest spell ranks among those years (ties count half), except that a spell within
               2 days of the usual is always "about usual": where spells are short, one day more or less can move the
               rank a long way and means nothing
  Not rated    fewer than 90% of the window's days have data, or fewer than 25 reference years

Run:
  python scripts/dryspell.py
  python scripts/dryspell.py --self-test
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOUNDARY_CREDIT, dry_runs, load_parishes, pct_rank, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
REF_FIRST, REF_LAST = 1991, 2020
SPAN = 60                        # days in the window
DRY_MM = 1.0
LONG_SPELL = 10                  # a spell this long or longer is counted separately
MIN_DIFF = 2                     # a spell within this many days of the usual counts as "about usual"
MIN_DATA = 0.9                   # share of the window's days that must have data
MIN_REF = 25
CHART_YEARS = 8                  # years shown in the pop-up chart
# --------------------------------------------------------------------------

CATEGORIES = [
    {"key": "much_long", "label": "Much longer than usual", "note": "longest 10% of years", "color": "#8c510a"},
    {"key": "long", "label": "Longer than usual", "note": "longest 10 to 30%", "color": "#d8b365"},
    {"key": "usual", "label": "About usual", "note": "middle 40%, or within 2 days of usual", "color": "#f3efe4"},
    {"key": "short", "label": "Shorter than usual", "note": "shortest 10 to 30%", "color": "#5ab4ac"},
    {"key": "much_short", "label": "Much shorter than usual", "note": "shortest 10% of years", "color": "#01665e"},
    {"key": "not_rated", "label": "Not rated", "note": "too many days missing, or too few years", "color": "#bdbdbd"},
]
NAMES = {c["key"]: c["label"] for c in CATEGORIES}


def classify(pct):
    if pct >= 90:
        return "much_long"
    if pct >= 70:
        return "long"
    if pct <= 10:
        return "much_short"
    if pct <= 30:
        return "short"
    return "usual"


def rate(length, base):
    """Category for a longest spell, given the baseline values: its rank, unless it is within MIN_DIFF days of the median."""
    if abs(length - float(np.median(base))) <= MIN_DIFF:
        return "usual"
    return classify(pct_rank(length, base))


def longest(x):
    """(longest run, index it starts at, number of runs of LONG_SPELL days or more, run that reaches the end) for a window of daily rain."""
    runs = dry_runs(x, DRY_MM)
    if not runs:
        return 0, None, 0, 0
    start, length = max(runs, key=lambda r: (r[1], -r[0]))
    ends_now = runs[-1][1] if runs[-1][0] + runs[-1][1] == len(x) else 0
    return length, start, sum(1 for _, n in runs if n >= LONG_SPELL), ends_now


def window_for_year(index, end_date, year, span=SPAN):
    """Indices of the `span` days ending on the same calendar day in `year`, or None if they are not all in the record."""
    try:
        e = dt.date(year, end_date.month, end_date.day)
    except ValueError:                           # 29 February in a year that has none
        e = dt.date(year, end_date.month, 28)
    ix = [index.get((e - dt.timedelta(k)).isoformat()) for k in range(span - 1, -1, -1)]
    return None if any(i is None for i in ix) else ix


def newest_day(dates, rain):
    """The newest day on which most parishes have data (the last day or two can be empty)."""
    for i in range(len(dates) - 1, -1, -1):
        if np.isfinite(rain[i]).mean() > 0.5:
            return i
    return len(dates) - 1


def self_test():
    nan = np.nan
    assert dry_runs(np.array([0, 0, 5, 0, 0, 0, nan, 0], "float32")) == [(0, 2), (3, 3), (7, 1)]
    x = np.array([0] * 4 + [8] + [0] * 12 + [3] + [0] * 10 + [6] + [0] * 2, "float32")
    assert longest(x) == (12, 5, 2, 2), longest(x)
    assert longest(np.array([5, 6, 7], "float32")) == (0, None, 0, 0)
    base = [3, 4, 5, 5, 5, 6, 7, 8, 9, 10]
    assert pct_rank(5, base) == (2 + 1.5) / 10 * 100
    assert [classify(p) for p in (100, 90, 89.9, 70, 69.9, 50, 30.1, 30, 10.1, 10, 0)] == \
        ["much_long", "much_long", "long", "long", "usual", "usual", "usual", "short", "short", "much_short", "much_short"]
    b = [3] * 5 + [4] * 10 + [5] * 8 + [6] * 4 + [8] * 3                      # median 4
    assert rate(3, b) == "usual" and rate(6, b) == "usual" and classify(pct_rank(3, b)) == "much_short"
    assert rate(7, b) == "much_long" and rate(1, b) == "much_short"
    # windows: the same calendar days in another year; 29 February falls back to 28 February; gaps give None
    days, d = [], dt.date(2019, 1, 1)
    while d <= dt.date(2021, 12, 31):
        days.append(d.isoformat())
        d += dt.timedelta(1)
    idx = {k: i for i, k in enumerate(days)}
    w = window_for_year(idx, dt.date(2020, 2, 29), 2021, span=3)
    assert [days[i] for i in w] == ["2021-02-26", "2021-02-27", "2021-02-28"]
    assert window_for_year(idx, dt.date(2021, 1, 2), 2018, span=3) is None
    # newest day skips empty trailing days
    r = np.full((5, 4), 1.0, "float32")
    r[4] = np.nan
    r[3, :3] = np.nan
    assert newest_day(["a"] * 5, r) == 2
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
    build(load_parishes(), z["dates"].tolist(), z["rain"])


def build(gdf, dates, rain):
    index = {d: i for i, d in enumerate(dates)}
    last_i = newest_day(dates, rain)
    end = dt.date.fromisoformat(dates[last_i])
    cur_ix = window_for_year(index, end, end.year)
    if cur_ix is None:
        sys.exit("The newest 60 days are not all in the rainfall record.")
    first = dt.date.fromisoformat(dates[cur_ix[0]])
    ref_years = [y for y in range(REF_FIRST, REF_LAST + 1) if window_for_year(index, end, y) is not None]
    chart_years = [y for y in range(end.year - CHART_YEARS + 1, end.year + 1) if window_for_year(index, end, y) is not None]
    print(f"window {first} to {end}; {len(ref_years)} reference years")
    cur_label = f"{first.day} {first:%b} to {end.day} {end:%b %Y}"
    parishes = {}
    n_rated = 0
    for i, row in gdf.iterrows():
        x = rain[cur_ix, i]
        valid = np.isfinite(x).mean()
        base, by_year = [], {}
        for y in set(ref_years) | set(chart_years):
            ix = window_for_year(index, end, y)
            w = rain[ix, i]
            by_year[y] = longest(w)[0] if np.isfinite(w).mean() >= MIN_DATA else None
        base = [by_year[y] for y in ref_years if by_year.get(y) is not None]
        if valid < MIN_DATA or len(base) < MIN_REF:
            parishes[row["id"]] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "Not rated", "rv": None, "rows": [],
                                   "big_note": "Too many days are missing in the last 60 days, or too few earlier years have data."}
            continue
        length, start, nlong, now_run = longest(x)
        cat = rate(length, base)
        n_rated += 1
        med = float(np.median(base))
        s_date = first + dt.timedelta(start) if start is not None else None
        rows = [["Longest dry spell, last 60 days", f"{length} days" + (f" ({s_date.day} {s_date:%b} to {(s_date + dt.timedelta(length - 1)).day} {(s_date + dt.timedelta(length - 1)):%b})" if s_date else "")],
                ["Usual longest spell in this window (1991–2020)", f"{med:.0f} days"],
                ["Earlier years with a shorter spell", f"{round(pct_rank(length, base) / 100 * len(base))} of {len(base)}"],
                ["Dry days in a row up to " + f"{end.day} {end:%b}", f"{now_run} days"],
                ["Spells of 10 days or more", str(nlong)]]
        if abs(length - med) <= MIN_DIFF and classify(pct_rank(length, base)) != "usual":
            rows.append(["Note", "Within 2 days of the usual, so shown as about usual even though its rank is high or low."])
        parishes[row["id"]] = {
            "name": row["name"], "cat": cat, "big": f"{length} days", "rv": length,
            "big_note": f"longest run of days under 1 mm of rain in the last 60 days (usual: {med:.0f})",
            "tip": f"{NAMES[cat]}, {length} days (usual {med:.0f})", "rows": rows,
            "v": [by_year.get(y) for y in chart_years],
            "bc": ["#8c510a" if y == end.year else "#b8c4bd" for y in chart_years],
        }
    print(f"{n_rated} of {len(gdf)} parishes rated")
    write_layer("dryspell", {
        "label": "Dry spells", "title": "Longest dry spell, last 60 days",
        "subtitle": f"{cur_label}, compared with the same days in 1991–2020 (experimental)",
        "source": "gridMET daily precipitation, averaged by parish", "demo": False, "build": BUILD, "categories": CATEGORIES,
        "rank": {"high": "Longest spells", "low": "Shortest spells", "note": "Ranked by the longest dry spell in days."},
        "how": ("The longest run of days with under 1 mm of rain in the last 60 days, compared with the same 60 days in each year from 1991 to 2020. A parish counts as about usual when its longest spell is in the middle 40% of those years or within 2 days of the usual."),
        "limits": [
            "Experimental. This has not been checked against the station gauges yet.",
            "Rain is averaged over a 4 km grid, and light drizzle in the grid breaks up dry spells, so spells at a single field can be longer.",
            "It shows the longest spell in the window, which may not match the stage a crop is at.",
            "A difference of 2 days or less always shows as about usual, because one day moves the rank a lot in parishes with short spells.",
            "A parish is left unrated when more than 10% of the days in the window are missing.",
        ],
        "credits": [{"text": "Rainfall: gridMET, Abatzoglou, J.T. (2013), Int. J. Climatology 33: 121-131", "url": "https://www.climatologylab.org/gridmet.html"}, BOUNDARY_CREDIT],
        "chart": {"kind": "bars", "unit": "days", "x": [str(y) for y in chart_years],
                  "caption": "Longest dry spell in the same 60 days, each year (dark bar: this year)", "top": "", "bottom": ""},
        "parishes": parishes,
    })


if __name__ == "__main__":
    main()
