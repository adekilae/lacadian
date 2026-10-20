#!/usr/bin/env python3
"""
LaCADIAN site - check the satellite and gridded layers against the LaCADIAN stations.

The 24 field stations measure rain and soil moisture directly. This script compares them, station by station, with the
values the Rainfall and Soil moisture layers are built from, taken at the station's location:

  Rain        gridMET daily precipitation in the grid cell nearest the station, against the station's rain gauge
              (cache/gridmet_rain.npz, from scripts/gridmet.py)
  Soil        SMAP L4 soil moisture in the 9 km cell containing the station, against the station's sensors
              (cache/smap_l4.npz, from scripts/smap.py). SMAP "root zone" (0-100 cm) is compared with the five sensor
              depths weighted by the thickness each represents; SMAP "surface" (0-5 cm) with the 5 cm sensor.

It writes data/validation.json, which the Drought page shows as a table under the Rainfall and Soil moisture maps.

How the numbers are made (all settings at the top):
  Rain   only days with a gauge reading and a grid value. Daily correlation, correlation of 7-day totals (the two
         sources do not cut the day at the same hour, so single days disagree more), the ratio of grid total to gauge total,
         and the share of days on which both agree whether it rained (1 mm or more).
  Soil   only days on which SMAP was sampled and every sensor depth had a reading. Spearman rank correlation (it does not
         need the sensor and the satellite to read the same value, only to move together), and the mean difference
         (SMAP minus sensors, m3/m3), which also shows that sensors and satellite differ in level.
  Both   a station is shown with its numbers only when it has at least MIN_DAYS matched days.

Run:
  python scripts/validate.py --repo PATH_TO_LaCADIAN_CHECKOUT      # the checkout the stations script reads
  python scripts/validate.py --self-test
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CACHE, DATA, load_parishes, write_json  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
MIN_DAYS = 30                  # matched days a station needs before its numbers are shown (rain)
MIN_SOIL_DAYS = 20             # matched SMAP sample days a station needs (soil)
RAIN_MM = 1.0                  # a rain day
DEPTH_WEIGHTS = {5: 7.5, 10: 7.5, 20: 20.0, 50: 40.0, 100: 25.0}      # cm of soil each sensor stands for in 0-100 cm
# --------------------------------------------------------------------------


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    from scipy.stats import rankdata
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    return pearson(rankdata(x), rankdata(y))


def weekly(dates, a, b, min_days=6):
    """Non-overlapping 7-day totals of two daily series (NaN = missing); a block needs min_days days with both values."""
    out_a, out_b = [], []
    for s in range(0, len(dates) - 6, 7):
        xa, xb = a[s:s + 7], b[s:s + 7]
        ok = ~(np.isnan(xa) | np.isnan(xb))
        if ok.sum() >= min_days:
            out_a.append(float(np.where(ok, xa, 0).sum() * 7 / ok.sum()))
            out_b.append(float(np.where(ok, xb, 0).sum() * 7 / ok.sum()))
    return out_a, out_b


def rain_stats(dates, gauge, grid):
    """gauge, grid: daily arrays aligned on `dates` (NaN where missing). -> dict of numbers, or {"n": n} when too few days."""
    gauge, grid = np.asarray(gauge, float), np.asarray(grid, float)
    ok = ~(np.isnan(gauge) | np.isnan(grid))
    n = int(ok.sum())
    if n < MIN_DAYS:
        return {"n": n}
    g, m = gauge[ok], grid[ok]
    wg, wm = weekly(dates, np.where(ok, gauge, np.nan), np.where(ok, grid, np.nan))
    return {"n": n, "r_daily": pearson(g, m), "r_week": pearson(wg, wm) if len(wg) >= 5 else None, "n_weeks": len(wg),
            "gauge_mm": float(g.sum()), "grid_mm": float(m.sum()), "ratio": float(m.sum() / g.sum()) if g.sum() > 0 else None,
            "agree": float(((g >= RAIN_MM) == (m >= RAIN_MM)).mean())}


def soil_stats(station_root, smap_root, station_surf, smap_surf):
    """Aligned arrays on the SMAP sample days (NaN = missing)."""
    out = {}
    for tag, s, m in (("root", station_root, smap_root), ("surf", station_surf, smap_surf)):
        s, m = np.asarray(s, float), np.asarray(m, float)
        ok = ~(np.isnan(s) | np.isnan(m))
        out[f"n_{tag}"] = int(ok.sum())
        if ok.sum() >= MIN_SOIL_DAYS:
            out[f"rho_{tag}"] = spearman(s[ok], m[ok])
            out[f"bias_{tag}"] = float((m[ok] - s[ok]).mean())
    return out


def root_zone(row):
    """The station's 0-100 cm soil moisture from its five sensors, or None if one is missing that day."""
    vals = [row.get(f"sm{d}") for d in DEPTH_WEIGHTS]
    if any(v is None for v in vals):
        return None
    return float(sum(v * w for v, w in zip(vals, DEPTH_WEIGHTS.values())) / sum(DEPTH_WEIGHTS.values()))


def nearest(lat, lon, la, lo, valid=None):
    """Index (row, col) of the grid cell nearest a point; only cells where `valid` is True if given."""
    d = (la[:, None] - lat) ** 2 + (lo[None, :] - lon) ** 2
    if valid is not None:
        d = np.where(valid, d, np.inf)
    return np.unravel_index(int(np.argmin(d)), d.shape)


def median(xs):
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def self_test():
    # rain: a grid that equals the gauge plus noise; a ratio of 1.2; missing days are left out
    rng = np.random.default_rng(3)
    n = 140
    dates = [(dt.date(2026, 1, 1) + dt.timedelta(i)).isoformat() for i in range(n)]
    gauge = np.where(rng.random(n) < 0.3, rng.gamma(2, 6, n), 0.0)
    grid = gauge * 1.2
    gauge2 = gauge.copy()
    gauge2[:5] = np.nan
    r = rain_stats(dates, gauge2, grid)
    assert r["n"] == n - 5 and abs(r["r_daily"] - 1) < 1e-9 and abs(r["ratio"] - 1.2) < 1e-9 and r["agree"] == 1.0 and r["n_weeks"] >= 18
    assert rain_stats(dates[:20], gauge[:20], grid[:20]) == {"n": 20}
    # constant series give no correlation instead of an error
    assert pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None and pearson([1, 2], [1, 2]) is None
    # soil: a monotone relation has Spearman 1 even when the levels differ
    s = np.linspace(0.1, 0.4, 40)
    m = 0.5 * s + 0.2
    st = soil_stats(s, m, s, m[::-1])
    assert st["n_root"] == 40 and abs(st["rho_root"] - 1) < 1e-9 and abs(st["rho_surf"] + 1) < 1e-9 and abs(st["bias_root"] - (m - s).mean()) < 1e-12
    assert "rho_root" not in soil_stats(s[:10], m[:10], s[:10], m[:10])
    # root zone from the sensors: equal readings give that reading; a missing depth gives None
    row = {f"sm{d}": 0.3 for d in DEPTH_WEIGHTS}
    assert abs(root_zone(row) - 0.3) < 1e-12
    row["sm50"] = None
    assert root_zone(row) is None
    # nearest cell, skipping invalid ones
    la, lo = np.array([31.0, 30.0]), np.array([-92.0, -91.0])
    assert nearest(30.9, -91.9, la, lo) == (0, 0)
    assert nearest(30.9, -91.9, la, lo, valid=np.array([[False, True], [True, True]])) == (0, 1) or nearest(30.9, -91.9, la, lo, valid=np.array([[False, True], [True, True]])) == (1, 0)
    assert median([1, None, 3]) == 2.0 and median([None]) is None
    print("self-test passed: 5 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("LACADIAN_SRC", "_source"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    import geopandas as gpd
    import stations as st
    sj = DATA / "stations.json"
    if not sj.exists() or not Path(args.repo).exists():
        sys.exit("Needs data/stations.json and a checkout of the LaCADIAN data repository (--repo).")
    meta = json.loads(sj.read_text())["stations"]
    gdf = load_parishes()
    pts = gpd.GeoDataFrame({"id": [m["id"] for m in meta]}, geometry=gpd.points_from_xy([m["lon"] for m in meta], [m["lat"] for m in meta]), crs=4326)
    parish_of = dict(zip(pts["id"], gpd.sjoin(pts, gdf[["name", "geometry"]], how="left", predicate="within")["name"].fillna("")))
    files = st.station_files(args.repo)
    daily = {}
    for m in meta:
        rows, _, _ = st.load_station(files[m["id"]])
        daily[m["id"]] = {r["date"]: r for r in rows}

    out = {"updated": dt.date.today().isoformat(), "build": BUILD, "rain": None, "soil": None}
    # ---- rain
    f = CACHE / "gridmet_rain.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        gd = z["dates"].tolist()
        sid = z["station_ids"].tolist()
        index = {d: i for i, d in enumerate(gd)}
        res = []
        for m in meta:
            if m["id"] not in sid:
                continue
            col = sid.index(m["id"])
            days = [d for d in sorted(daily[m["id"]]) if d in index]
            if not days:
                continue
            gauge = np.array([np.nan if daily[m["id"]][d]["precip"] is None else daily[m["id"]][d]["precip"] for d in days])
            grid = np.array([z["station_rain"][index[d], col] for d in days])
            r = rain_stats(days, gauge, grid)
            res.append({"id": m["id"], "name": m["name"], "parish": parish_of.get(m["id"], ""), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}})
        rated = [r for r in res if "r_daily" in r]
        out["rain"] = {"stations": res, "pooled": {"stations": len(rated), "median_r_daily": median([r["r_daily"] for r in rated]), "median_r_week": median([r.get("r_week") for r in rated]),
                                                   "median_ratio": median([r.get("ratio") for r in rated]), "median_agree": median([r.get("agree") for r in rated])},
                       "source": "gridMET daily precipitation (4 km) at the cell nearest the station, against the station's rain gauge"}
        print(f"rain: {len(rated)} of {len(res)} stations with enough matched days")
    else:
        print("No gridMET cache: the rain check is skipped.")
    # ---- soil
    f = CACHE / "smap_l4.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        days, lat, lon = z["days"].tolist(), z["lat"], z["lon"]
        valid = ~np.isnan(z["root"][0])
        res = []
        for m in meta:
            r0, c0 = nearest(m["lat"], m["lon"], lat, lon, valid)
            keys = [k for k in days if f"{k[:4]}-{k[4:6]}-{k[6:]}" in daily[m["id"]]]
            if not keys:
                continue
            sr, sf, mr, mf = [], [], [], []
            for k in keys:
                row = daily[m["id"]][f"{k[:4]}-{k[4:6]}-{k[6:]}"]
                i = days.index(k)
                v = root_zone(row)
                sr.append(np.nan if v is None else v)
                sf.append(np.nan if row.get("sm5") is None else row["sm5"])
                mr.append(float(z["root"][i][r0, c0]))
                mf.append(float(z["surf"][i][r0, c0]))
            s = soil_stats(sr, mr, sf, mf)
            res.append({"id": m["id"], "name": m["name"], "parish": parish_of.get(m["id"], ""), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}})
        rated = [r for r in res if "rho_root" in r]
        out["soil"] = {"stations": res, "pooled": {"stations": len(rated), "median_rho_root": median([r["rho_root"] for r in rated]), "median_rho_surf": median([r.get("rho_surf") for r in rated]),
                                                   "median_bias_root": median([r.get("bias_root") for r in rated])},
                       "source": "SMAP L4 (9 km cell containing the station) on the days it is sampled, against the station's soil sensors"}
        print(f"soil: {len(rated)} of {len(res)} stations with enough matched days")
    else:
        print("No SMAP cache: the soil check is skipped.")
    if out["rain"] is None and out["soil"] is None:
        sys.exit("Neither the gridMET nor the SMAP record exists yet, so there is nothing to compare.")
    write_json("validation.json", out)
    print("Wrote data/validation.json")


if __name__ == "__main__":
    main()
