#!/usr/bin/env python3
"""
LaCADIAN site - US Drought Monitor, by parish.

The US Drought Monitor is a weekly map made by the National Drought Mitigation Center (University of Nebraska-Lincoln),
the USDA and NOAA. Experts draw it from many sources, including local reports, and it is the official drought
map of the United States. This script downloads the weekly percentage of each parish's area in each drought
category (D0 to D4) from the Drought Monitor's data service and shows the latest week.

Rules (settings are at the top of this file):
  Parish colour   the most severe category that covers at least 25% of the parish's area. The pop-up gives the
                  full breakdown, because a parish can have a small part in a worse category.

Run:
  python scripts/usdm.py
  python scripts/usdm.py --self-test

Data: US Drought Monitor, National Drought Mitigation Center at the University of Nebraska-Lincoln, USDA and NOAA.
"""
import argparse
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOUNDARY_CREDIT, get_url, load_parishes, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
STATE = "LA"
WEEKS = 14                         # weeks requested (12 are drawn in the chart)
SHARE = 25.0                       # a category colours a parish when it covers at least this % of the parish
ENDPOINT = "https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent"
# --------------------------------------------------------------------------

CATEGORIES = [
    {"key": "d4", "label": "D4 Exceptional drought", "note": "", "color": "#730000"},
    {"key": "d3", "label": "D3 Extreme drought", "note": "", "color": "#E60000"},
    {"key": "d2", "label": "D2 Severe drought", "note": "", "color": "#FFAA00"},
    {"key": "d1", "label": "D1 Moderate drought", "note": "", "color": "#FCD37F"},
    {"key": "d0", "label": "D0 Abnormally dry", "note": "", "color": "#FFFF00"},
    {"key": "none", "label": "No drought area", "note": f"under {SHARE:.0f}% of the parish in D0 or worse", "color": "#f1ede0"},
    {"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"},
]
NAMES = {c["key"]: c["label"] for c in CATEGORIES}
COLORS = {c["key"]: c["color"] for c in CATEGORIES}
LEVELS = ["d0", "d1", "d2", "d3", "d4"]


def parse(text):
    """Reply of the service (JSON, or CSV) -> list of {map date (YYYY-MM-DD), fips, none, d0..d4}."""
    text = text.strip()
    if not text:
        return []
    if text[:1] in "[{":
        data = json.loads(text)
        data = data if isinstance(data, list) else next(v for v in data.values() if isinstance(v, list))
    else:
        data = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in data:
        low = {str(k).strip().lower(): v for k, v in r.items()}
        raw = str(low.get("mapdate") or low.get("validstart") or "").strip()
        digits = "".join(ch for ch in raw[:10] if ch.isdigit())
        if len(digits) < 8:
            continue
        date = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        fips = str(low.get("fips") or "").strip().zfill(5)
        try:
            vals = {k: float(low[k]) for k in ["none"] + LEVELS}
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"date": date, "fips": fips, **vals})
    return out


def cumulative(rec):
    """Percent of the parish in D0 or worse, D1 or worse ... D4: the service can return either cumulative or separate shares."""
    v = [rec[k] for k in LEVELS]
    if abs(rec["none"] + sum(v) - 100) <= 1.5:              # shares that add up to 100: separate categories
        return [sum(v[k:]) for k in range(5)]
    return v                                                  # already cumulative (D0 includes D1 ... D4)


def category(cum):
    for k in (4, 3, 2, 1, 0):
        if cum[k] >= SHARE:
            return LEVELS[k]
    return "none"


def fetch():
    end = dt.date.today()
    start = end - dt.timedelta(weeks=WEEKS)
    url = (f"{ENDPOINT}?aoi={STATE}&startdate={start.month}/{start.day}/{start.year}"
           f"&enddate={end.month}/{end.day}/{end.year}&statisticsType=1")
    r = get_url(url, tries=4, timeout=180, headers={"Accept": "application/json"})
    return parse(r.text)


def self_test():
    js = json.dumps([
        {"MapDate": "20261006", "FIPS": "22001", "County": "Acadia Parish", "State": "LA", "None": 100, "D0": 0, "D1": 0, "D2": 0, "D3": 0, "D4": 0},
        {"MapDate": "20261013", "FIPS": "22001", "County": "Acadia Parish", "State": "LA", "None": 20, "D0": 30, "D1": 30, "D2": 20, "D3": 0, "D4": 0},
        {"MapDate": "20261013", "FIPS": "22003", "County": "Allen Parish", "State": "LA", "None": 0, "D0": 100, "D1": 80, "D2": 30, "D3": 5, "D4": 0},
        {"MapDate": "bad", "FIPS": "22005"}])
    recs = parse(js)
    assert len(recs) == 3 and recs[1]["date"] == "2026-10-13" and recs[1]["fips"] == "22001"
    assert cumulative(recs[1]) == [80, 50, 20, 0, 0]          # separate shares -> cumulative
    assert cumulative(recs[2]) == [100, 80, 30, 5, 0]         # already cumulative
    assert category([80, 50, 20, 0, 0]) == "d1" and category([100, 80, 30, 5, 0]) == "d2" and category([20, 0, 0, 0, 0]) == "none"
    assert category([100, 100, 100, 100, 25]) == "d4" and category([30, 24.9, 0, 0, 0]) == "d0"
    csvtext = "MapDate,FIPS,County,State,None,D0,D1,D2,D3,D4\n2026-10-13,22001,Acadia,LA,50,50,0,0,0,0\n"
    r2 = parse(csvtext)
    assert r2[0]["date"] == "2026-10-13" and r2[0]["d0"] == 50
    print("self-test passed: 3 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    recs = fetch()
    if not recs:
        sys.exit("The Drought Monitor service returned no usable rows.")
    build(load_parishes(), recs)


def build(gdf, recs):
    weeks = sorted({r["date"] for r in recs})
    latest = weeks[-1]
    chart_weeks = weeks[-12:]
    by = {}
    for r in recs:
        by[(r["fips"], r["date"])] = cumulative(r)
    when = dt.date.fromisoformat(latest)
    parishes = {}
    for i, row in gdf.iterrows():
        pid = row["id"]
        cum = by.get((pid, latest))
        if cum is None:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [],
                             "big_note": "The Drought Monitor returned nothing for this parish."}
            continue
        cat = category(cum)
        hist = [by.get((pid, w)) for w in chart_weeks]
        rows = [["Area in D0 or worse (abnormally dry)", f"{cum[0]:.0f}%"], ["Area in D1 or worse (moderate)", f"{cum[1]:.0f}%"],
                ["Area in D2 or worse (severe)", f"{cum[2]:.0f}%"], ["Area in D3 or worse (extreme)", f"{cum[3]:.0f}%"],
                ["Area in D4 (exceptional)", f"{cum[4]:.0f}%"]]
        parishes[pid] = {
            "name": row["name"], "cat": cat, "rv": round(cum[1], 1),
            "big": NAMES[cat].split(" ")[0].upper() if cat != "none" else "None",
            "big_note": (f"is the most severe category covering at least {SHARE:.0f}% of the parish, map of {when.day} {when:%b %Y}" if cat != "none"
                         else f"No drought category covers {SHARE:.0f}% of the parish, map of {when.day} {when:%b %Y}"),
            "tip": f"{NAMES[cat]} · {cum[1]:.0f}% of the parish in D1 or worse",
            "rows": rows,
            "v": [None if h is None else round(h[1], 1) for h in hist],
            "bc": ["#b8c4bd" if h is None else COLORS[category(h)] for h in hist],
        }
    n_drought = sum(1 for p in parishes.values() if p["cat"] in LEVELS)
    print(f"map of {latest}: {n_drought} of {len(gdf)} parishes coloured")
    write_layer("usdm", {
        "label": "Drought Monitor", "title": "US Drought Monitor",
        "subtitle": f"Weekly map valid {when.day} {when:%b %Y}, official US drought categories",
        "source": "US Drought Monitor, National Drought Mitigation Center (University of Nebraska-Lincoln), USDA and NOAA", "demo": False, "build": BUILD,
        "categories": CATEGORIES,
        "rank": {"high": "Most area in drought (D1 or worse)", "low": "Least area in drought", "note": "Ranked by the share of the parish in D1 or worse."},
        "how": (f"Each parish is coloured by the most severe drought category that covers at least {SHARE:.0f}% of its area, from the latest weekly US Drought "
                "Monitor. The pop-up gives the share of the parish in each category and the last 12 weeks. This is the official map, drawn by "
                "experts, and is a separate source from the other layers on this page."),
        "limits": [
            "The Drought Monitor is made by experts from many sources, including local reports. It does not use only the data shown in the other layers, so the maps can differ.",
            f"A parish takes the colour of the worst category covering {SHARE:.0f}% or more of it. A smaller area in a worse category is shown only in the pop-up.",
            "It is a weekly map valid on Tuesdays and released on Thursdays. It describes conditions over the weeks before, mostly long-term dryness.",
            "It is not a forecast and does not describe a single field.",
        ],
        "credits": [{"text": "US Drought Monitor, National Drought Mitigation Center at the University of Nebraska-Lincoln, the USDA and NOAA", "url": "https://droughtmonitor.unl.edu/"}, BOUNDARY_CREDIT],
        "chart": {"kind": "bars", "unit": "%", "x": [f"{int(w[8:])} {dt.date.fromisoformat(w):%b}" for w in chart_weeks],
                  "caption": "Share of the parish in D1 or worse, last 12 weeks", "top": "", "bottom": ""},
        "parishes": parishes,
    })


if __name__ == "__main__":
    main()
