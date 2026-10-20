#!/usr/bin/env python3
"""
LaCADIAN site - build data/stations.json from the public LaCADIAN station data.

The LaCADIAN network (Louisiana Climate & Digital Ag Network, LSU SHaRE Lab) publishes daily station files in the
GitHub repository soil-hydrology/LaCADIAN (2025/Daily/*.txt and 2026/Daily/*.txt). The daily files have no header
row; their 39 columns are described in 2025/daily.txt of that repository and are listed in COLUMNS below.

This script reads those files and writes one small file for the website. It changes no values, except that a
reading outside what a sensor can physically report is left out (see CHECKS) and listed in "quality".

Run:
  python scripts/stations.py --repo PATH_TO_LaCADIAN_CHECKOUT            # writes data/stations.json
  python scripts/stations.py --repo PATH --out other.json
  python scripts/stations.py --self-test

Data: LaCADIAN network, LSU Soil Hydrology and Remote Sensing (SHaRE) Lab. The AgCenter page says the data are
CC BY-NC 4.0 and for academic, non-commercial use; keep the credit on the site.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "stations.json"

# The 39 columns of a daily file, in order (from 2025/daily.txt in the LaCADIAN repository)
COLUMNS = ["date", "lon", "lat", "precip", "lst_mean", "lst_min", "lst_max", "air_mean", "air_min", "air_max",
           "rh_mean", "rh_min", "rh_max", "pressure", "vapor_pressure", "solar", "wind", "gust", "vpd", "precip_ec",
           "sm5", "sm10", "sm20", "sm50", "sm100", "mp5", "mp20", "mp50",
           "ec5", "ec10", "ec20", "ec50", "ec100", "st5", "st10", "st20", "st50", "st100", "ndvi"]
DEPTHS = [5, 10, 20, 50, 100]
DRY_MM = 1.0              # a day under this is a dry day (the same rule as Tinga Lens)
SERIES_DAYS = 120         # days of history sent to the website for the charts
MIN_RECORD = 90           # days a station needs before its readings are ranked against its own record
SUSPECT_MM = 150.0        # a daily rainfall above this is kept but listed for the network team to check
STALE_DAYS = 3            # a station whose last reading is older than this (compared with the newest station) is shown as stale

# readings outside these limits cannot be real and are left out
CHECKS = {"precip": (0, 600), "air_mean": (-40, 55), "sm5": (0.0, 0.7), "sm10": (0.0, 0.7), "sm20": (0.0, 0.7),
          "sm50": (0.0, 0.7), "sm100": (0.0, 0.7)}

NAMES = {"Ben_Hur": "Ben Hur", "StGabriel": "St. Gabriel", "BossierCity": "Bossier City", "Alexandria_West": "Alexandria West",
         "Alexandria_East": "Alexandria East", "StJoseph": "St. Joseph", "LAHouse": "LA House", "LakeProvidence": "Lake Providence",
         "Deridder": "DeRidder", "StFrancisville": "St. Francisville", "OakGrove": "Oak Grove"}
FILE = re.compile(r"^(LAC\d{3})_(.+)_DAILY_(\d{4})\.txt$")


# ============================================================ pure functions (tested below)
def parse_line(line):
    """One daily row -> {column: float or None}, or None when the row is not a 39-column daily row."""
    p = line.rstrip("\r\n").split("\t")
    if len(p) != len(COLUMNS) or not re.match(r"^\d{4}-\d\d-\d\d$", p[0]):
        return None
    row = {"date": p[0]}
    for name, v in zip(COLUMNS[1:], p[1:]):
        try:
            x = float(v)
            row[name] = x if np.isfinite(x) else None
        except ValueError:
            row[name] = None                       # "NA" and anything else that is not a number
    return row


def clean(row, flags):
    """Blank readings outside what a sensor can report; list rainfall that is possible but large."""
    for k, (lo, hi) in CHECKS.items():
        v = row.get(k)
        if v is not None and not (lo <= v <= hi):
            flags.append({"date": row["date"], "what": k, "value": v, "action": "left out (outside the possible range)"})
            row[k] = None
    if row.get("precip") is not None and row["precip"] > SUSPECT_MM:
        flags.append({"date": row["date"], "what": "precip", "value": round(row["precip"], 1), "action": "kept; please check against the gauge log"})
    return row


def dry_runs(values):
    """[(start index, length)] of runs of days under DRY_MM; a missing day ends a run."""
    runs, start = [], None
    for i, v in enumerate(values):
        if v is not None and v < DRY_MM:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(values) - start))
    return runs


def rank_among(value, record):
    """Share (0-100) of recorded days with a value at or below this one, ties counted half."""
    a = np.array([x for x in record if x is not None], float)
    if len(a) == 0 or value is None:
        return None
    return float(((a < value).sum() + 0.5 * (a == value).sum()) / len(a) * 100)


def station_summary(rows):
    """rows: list of cleaned daily dicts for one station, sorted by date and without duplicates."""
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    last = dates[-1]
    full = {d: r for d, r in zip(dates, rows)}
    span = [last - dt.timedelta(i) for i in range(SERIES_DAYS - 1, -1, -1)]          # the days sent for the charts (gaps stay empty)
    ser = {"dates": [d.isoformat() for d in span]}
    for k in ("precip", "air_mean", "sm5", "sm10", "sm20", "sm50", "sm100"):
        ser[k] = [None if d not in full or full[d][k] is None else round(full[d][k], 3) for d in span]

    def total(days):
        vals = [full[last - dt.timedelta(i)]["precip"] if (last - dt.timedelta(i)) in full else None for i in range(days)]
        known = [v for v in vals if v is not None]
        return (round(sum(known), 1), days - len(known)) if known else (None, days)

    r7, miss7 = total(7)
    r30, miss30 = total(30)
    # dry days in a row up to the last day, and the longest dry spell since 1 March of the last year (point measurements)
    start_season = dt.date(last.year, 3, 1)
    season = [start_season + dt.timedelta(i) for i in range((last - start_season).days + 1)]
    sp = [full[d]["precip"] if d in full else None for d in season]
    while sp and sp[-1] is None:                       # no reading yet for the newest days: count up to the last day that has one
        sp.pop()
    runs = dry_runs(sp)
    now_run = runs[-1][1] if runs and runs[-1][0] + runs[-1][1] == len(sp) else 0
    longest = max(runs, key=lambda r: (r[1], -r[0])) if runs else None
    latest = rows[-1]
    out = {
        "last": last.isoformat(), "first": dates[0].isoformat(), "days": len(rows),
        "latest": {"precip": latest["precip"], "air": latest["air_mean"], "sm": {str(d): latest[f"sm{d}"] for d in DEPTHS}},
        "rain7": r7, "rain7_missing": miss7, "rain30": r30, "rain30_missing": miss30, "dry_now": now_run,
        "dry_longest": ({"days": longest[1], "from": season[longest[0]].isoformat(), "to": season[longest[0] + longest[1] - 1].isoformat()}
                        if longest else None),
        "series": ser,
    }
    rel = {}
    for d in DEPTHS:
        rec = [r[f"sm{d}"] for r in rows]
        have = sum(x is not None for x in rec)
        rel[str(d)] = rank_among(latest[f"sm{d}"], rec) if have >= MIN_RECORD else None
        if rel[str(d)] is not None:
            rel[str(d)] = round(rel[str(d)], 1)
    out["rel"] = rel
    out["sm_range"] = {str(d): ([round(min(x for x in (r[f"sm{d}"] for r in rows) if x is not None), 3),
                                round(max(x for x in (r[f"sm{d}"] for r in rows) if x is not None), 3)]
                                if any(r[f"sm{d}"] is not None for r in rows) else None) for d in DEPTHS}
    return out


def self_test():
    # 1. parsing: a good row, NA, a short row, a header row
    good = "\t".join(["2026-01-01", "-91.164", "30.373", "0.5"] + ["NA"] * 35)
    r = parse_line(good)
    assert r["date"] == "2026-01-01" and r["precip"] == 0.5 and r["sm20"] is None and r["lat"] == 30.373 and r["lon"] == -91.164
    assert parse_line("date\tlon") is None and parse_line("\t".join(["date"] + ["x"] * 38)) is None
    # 2. column map: the position of the soil moisture columns and of NDVI in the real file format
    assert COLUMNS.index("sm5") == 20 and COLUMNS.index("sm100") == 24 and COLUMNS.index("ndvi") == 38 and len(COLUMNS) == 39
    # 3. impossible values are left out, large rainfall is kept and listed
    flags = []
    row = {"date": "2026-02-02", "precip": 700.0, "air_mean": 10, "sm5": 0.9, "sm10": 0.3, "sm20": 0.3, "sm50": 0.3, "sm100": 0.3}
    clean(row, flags)
    assert row["precip"] is None and row["sm5"] is None and row["sm10"] == 0.3 and len(flags) == 2
    flags = []
    row = {"date": "2026-02-03", "precip": 279.2, "air_mean": 10, "sm5": 0.3, "sm10": 0.3, "sm20": 0.3, "sm50": 0.3, "sm100": 0.3}
    clean(row, flags)
    assert row["precip"] == 279.2 and flags[0]["action"].startswith("kept")
    # 4. dry runs: a missing day ends a run; the last run reaches the end
    assert dry_runs([0, 0, 5, 0, 0, 0, None, 0]) == [(0, 2), (3, 3), (7, 1)]
    assert dry_runs([1.0, 0.99]) == [(1, 1)]
    # 5. rank among own record: ties count half
    assert rank_among(5, [1, 2, 5, 5, 8]) == (2 + 1) / 5 * 100 and rank_among(None, [1]) is None and rank_among(3, []) is None
    # 6. a whole station summary on made-up days
    start = dt.date(2026, 3, 1)
    rows = []
    for i in range(130):
        d = start + dt.timedelta(i)
        p = 20.0 if i in (10, 60) else 0.0
        rows.append({"date": d.isoformat(), "precip": None if i == 129 else p, "air_mean": 20.0, "sm5": 0.2 + i / 1000, "sm10": 0.2, "sm20": 0.3 + i / 1000,
                     "sm50": 0.3, "sm100": 0.3})
    s = station_summary(rows)
    assert s["last"] == "2026-07-08" and s["days"] == 130 and s["rain7"] == 0.0 and s["rain7_missing"] == 1
    assert s["dry_now"] == 68                  # 61 .. 128 dry, day 129 has no reading, so the run ends at day 128
    assert s["dry_longest"]["days"] == 68, s["dry_longest"]
    assert s["rel"]["5"] > 99 and s["series"]["dates"][-1] == "2026-07-08" and len(s["series"]["precip"]) == SERIES_DAYS
    assert s["series"]["precip"][-1] is None and s["series"]["precip"][-2] == 0.0
    print("self-test passed: 6 groups")


# ============================================================ reading the repository
def station_files(repo):
    """{station id: [(year, path, name part)]} for the daily files that follow the naming of the network."""
    found = {}
    for f in sorted(glob.glob(str(Path(repo) / "20*" / "Daily" / "*.txt"))):
        m = FILE.match(os.path.basename(f))
        if m:
            found.setdefault(m.group(1), []).append((int(m.group(3)), f, m.group(2)))
    return found


def load_station(files):
    flags, by_date, coords = [], {}, []
    for year, f, _ in sorted(files):
        for line in open(f, encoding="utf-8", errors="replace"):
            row = parse_line(line)
            if row is None:
                continue
            clean(row, flags)
            by_date[row["date"]] = row                     # a later file overrides an earlier one for the same date
            if row.get("lat") is not None and row.get("lon") is not None:
                coords.append((row["lat"], row["lon"]))
    rows = [by_date[k] for k in sorted(by_date)]
    return rows, flags, coords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="a checkout of github.com/soil-hydrology/LaCADIAN")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.repo or not Path(args.repo).exists():
        sys.exit("Give --repo with a checkout of the LaCADIAN data repository (git clone --depth 1 https://github.com/soil-hydrology/LaCADIAN).")
    stations, quality, newest = [], [], None
    for sid, files in sorted(station_files(args.repo).items()):
        rows, flags, coords = load_station(files)
        if len(rows) < 3 or not coords:
            continue
        name_part = max(files, key=lambda x: (x[0], os.path.getsize(x[1])))[2]
        name = NAMES.get(name_part, name_part.replace("_", " "))
        lat = float(np.median([c[0] for c in coords])); lon = float(np.median([c[1] for c in coords]))
        s = {"id": sid, "name": name, "lat": round(lat, 4), "lon": round(lon, 4), **station_summary(rows)}
        stations.append(s)
        quality += [{"station": sid, "name": name, **q} for q in flags]
        newest = max(newest, s["last"]) if newest else s["last"]
    newest_d = dt.date.fromisoformat(newest)
    for s in stations:
        s["stale"] = (newest_d - dt.date.fromisoformat(s["last"])).days > STALE_DAYS
    payload = {
        "updated": dt.date.today().isoformat(), "data_through": newest, "n": len(stations),
        "source": "LaCADIAN network (Louisiana Climate & Digital Ag Network), LSU Soil Hydrology and Remote Sensing (SHaRE) Lab",
        "source_url": "https://github.com/soil-hydrology/LaCADIAN",
        "licence": "CC BY-NC 4.0 as stated on the LSU AgCenter LaCADIAN page; academic and non-commercial use",
        "depths_cm": DEPTHS, "dry_day_mm": DRY_MM, "min_record_days": MIN_RECORD,
        "quality": quality, "stations": stations,
    }
    Path(args.out).write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    print(f"Wrote {args.out}: {len(stations)} stations, data through {newest}, {len(quality)} quality notes")
    for q in quality:
        print("  note:", q)


if __name__ == "__main__":
    main()
