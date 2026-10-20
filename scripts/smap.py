#!/usr/bin/env python3
"""
LaCADIAN site - soil moisture by parish.

Source: NASA SMAP Level-4 (SPL4SMGP), 9 km, surface (0-5 cm) and root zone (0-100 cm) soil moisture. It merges SMAP
satellite observations into a land model, so it has no gaps.

Indicator: average root-zone soil moisture for the latest complete month, compared with the same calendar month in
every earlier year of the SMAP record (2015 onwards).

To keep downloads small, each month is sampled on SAMPLE_DAYS at one time of day, and only the Louisiana window of
each file is read. The window of every sampled day is kept in cache/smap_l4.npz; scripts/validate.py reads it to
compare SMAP with the LaCADIAN soil sensors.

Needs a free NASA Earthdata login, given through environment variables (set them as GitHub repository secrets):
  EARTHDATA_USERNAME and EARTHDATA_PASSWORD   (or EARTHDATA_TOKEN)

Run:
  python scripts/smap.py
  python scripts/smap.py --self-test
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import write_months, BBOX, BOUNDARY_CREDIT, CACHE, MON, WETNESS, load_parishes, wetness_category, write_json, write_layer, ym_text  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
SHORT_NAME = "SPL4SMGP"
VERSION = "008"                         # change here if NASA releases a new version
FIRST_MONTH = (2015, 4)                 # first full month of SMAP L4
SAMPLE_DAYS = [3, 8, 13, 18, 23, 28]    # days of each month that are read
SAMPLE_TIME = "T103000"                 # one 3-hourly file per sampled day (10:30 UTC)
MIN_REF_YEARS = 5                       # earlier years needed before a month is rated
HISTORY_MONTHS = 12
SAVE_EVERY = 25                         # save progress after this many files
RETRIES = 3                             # tries per file before it is skipped
MIN_SAMPLES = 4                         # sampled days a month needs before it is used
# --------------------------------------------------------------------------
CACHE_FILE = CACHE / "smap_l4.npz"


def month_list(first, last):
    out, (y, m) = [], first
    while (y, m) <= last:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def day_key(y, m, d):
    return f"{y}{m:02d}{d:02d}"


def load_cache():
    if not CACHE_FILE.exists():
        return {}, None
    z = np.load(CACHE_FILE, allow_pickle=False)
    root, surf = z["root"], z["surf"]
    have = {k: (root[i], surf[i]) for i, k in enumerate(z["days"].tolist())}
    return have, (z["lat"], z["lon"])


def save_cache(have, grid):
    CACHE.mkdir(exist_ok=True)
    days = sorted(have)
    np.savez_compressed(CACHE_FILE, days=np.array(days), lat=grid[0], lon=grid[1],
                        root=np.stack([have[k][0] for k in days]), surf=np.stack([have[k][1] for k in days]))


def read_window(fobj, grid_slices):
    """Read the Louisiana window of one SMAP file. Returns root, surface, (rows, cols, lat, lon)."""
    import h5py
    with h5py.File(fobj, "r") as f:
        if grid_slices is None:
            lat = f["cell_lat"][:, 0]
            lon = f["cell_lon"][0, :]
            rows = np.nonzero((lat >= BBOX[1]) & (lat <= BBOX[3]))[0]
            cols = np.nonzero((lon >= BBOX[0]) & (lon <= BBOX[2]))[0]
            grid_slices = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1),
                           lat[rows[0]:rows[-1] + 1], lon[cols[0]:cols[-1] + 1])
        r, c = grid_slices[0], grid_slices[1]
        out = []
        for name in ("sm_rootzone", "sm_surface"):
            a = f["Geophysical_Data"][name][r, c].astype("float32")
            a[(a < 0) | (a > 1)] = np.nan          # fill value is -9999
            out.append(a)
    return out[0], out[1], grid_slices


def read_with_retry(earthaccess, granule, slices, key):
    """Open and read one file, trying again if the server sends a bad response."""
    import time
    for attempt in range(1, RETRIES + 1):
        try:
            fobj = earthaccess.open([granule])[0]
            try:
                return read_window(fobj, slices)
            finally:
                try:
                    fobj.close()
                except Exception:
                    pass
        except Exception as e:                       # network hiccup, expired login, damaged file
            print(f"  {key}: attempt {attempt} failed ({type(e).__name__}: {str(e)[:120]})", flush=True)
            if attempt < RETRIES:
                time.sleep(20 * attempt)
                try:
                    earthaccess.login(strategy="environment")    # refresh the login
                except Exception:
                    pass
    return None


def load_real(today):
    import earthaccess
    from common import cmr_search, earthdata_login
    earthdata_login()                                  # tries several times; exits with a plain message if NASA is unreachable
    have, grid = load_cache()
    slices = None
    months = month_list(FIRST_MONTH, (today.year, today.month))
    done, skipped = 0, []
    for (y, m) in months:
        wanted = [day_key(y, m, d) for d in SAMPLE_DAYS]
        missing = [k for k in wanted if k not in have]
        if not missing:
            continue
        last_day = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
        found = cmr_search(short_name=SHORT_NAME, version=VERSION, count=-1,
                                        temporal=(f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last_day}"))
        pick = {}
        for g in found:
            name = g.data_links()[0].rsplit("/", 1)[1]
            for k in missing:
                if f"_{k}{SAMPLE_TIME}_" in name:
                    pick[k] = g
        if not pick:
            continue
        for k in sorted(pick):
            got = read_with_retry(earthaccess, pick[k], slices, k)
            if got is None:
                skipped.append(k)
                continue
            root, surf, slices_new = got
            if slices is None:
                slices = slices_new
                if grid is not None and (len(grid[0]) != len(slices[2]) or len(grid[1]) != len(slices[3])):
                    sys.exit("SMAP grid differs from the cache; delete the cache folder and run again.")
                grid = (slices[2], slices[3])
            have[k] = (root, surf)
            done += 1
            if done % SAVE_EVERY == 0:
                save_cache(have, grid)
                print(f"  {done} files read (up to {k})", flush=True)
    if skipped:
        print(f"Could not read {len(skipped)} file(s), they will be tried again next run: {', '.join(skipped)}")
    if not have:
        sys.exit(f"No {SHORT_NAME} v{VERSION} files were found. Check VERSION in scripts/smap.py.")
    save_cache(have, grid)
    print(f"{done} new file(s) read, {len(have)} in total")
    return have, grid, f"NASA SMAP L4 ({SHORT_NAME} v{VERSION})"


def cells_per_parish(gdf, lat, lon, valid):
    """For each parish, the land grid cells whose centre falls inside it (or the nearest one)."""
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    ok = np.nonzero(valid.ravel())[0]                  # cells that hold data (not open water)
    la, lo = la.ravel()[ok], lo.ravel()[ok]
    pts = gpd.GeoDataFrame({"cell": ok}, geometry=gpd.points_from_xy(lo, la), crs=gdf.crs)
    hit = gpd.sjoin(pts, gdf[["geometry"]], predicate="within")
    groups = hit.groupby("index_right")["cell"].apply(np.array).to_dict()
    out = []
    for i, geom in enumerate(gdf.geometry):
        if i in groups:
            out.append(groups[i])
        else:   # parish smaller than a grid cell, or with no land cell inside: use the nearest land cell centre
            p = geom.representative_point()
            out.append(np.array([ok[np.argmin((la - p.y) ** 2 + (lo - p.x) ** 2)]]))
    return out


def monthly_parish_means(have, cells, this_month):
    """Finished months with enough sample days -> (months, root[time, parish], surf[time, parish])."""
    months, root, surf = [], [], []
    ym = sorted({(int(k[:4]), int(k[4:6])) for k in have})
    for (y, m) in ym:
        keys = [k for k in (day_key(y, m, d) for d in SAMPLE_DAYS) if k in have]
        if (y, m) >= this_month or len(keys) < MIN_SAMPLES:    # month still running, or too few samples
            continue
        r = np.mean(np.stack([have[k][0] for k in keys]), axis=0).ravel()
        s = np.mean(np.stack([have[k][1] for k in keys]), axis=0).ravel()
        months.append((y, m))
        root.append([np.nanmean(r[c]) for c in cells])
        surf.append([np.nanmean(s[c]) for c in cells])
    return months, np.array(root), np.array(surf)


def assess(months, x, t):
    """Compare month t with the same calendar month in all earlier years."""
    y, m = months[t]
    ref_i = [i for i, (yy, mm) in enumerate(months) if mm == m and yy < y]
    if len(ref_i) < MIN_REF_YEARS:
        return None
    ref, cur = x[ref_i], x[t]
    normal = ref.mean(axis=0)
    pctile = ((ref < cur).sum(axis=0) + 0.5 * (ref == cur).sum(axis=0)) / len(ref_i) * 100
    return cur, normal, cur / normal * 100, pctile, len(ref_i)


def self_test():
    assert month_list((2015, 11), (2016, 2)) == [(2015, 11), (2015, 12), (2016, 1), (2016, 2)]
    # a tiny grid with two parishes: a cell holds data unless it is NaN (open water)
    from shapely.geometry import box
    lat, lon = np.array([31.0, 30.0]), np.array([-92.0, -91.0])
    valid = np.array([[True, True], [False, True]])
    g = gpd.GeoDataFrame({"id": ["a", "b", "c"]}, geometry=[box(-92.5, 30.5, -91.5, 31.5), box(-91.5, 29.5, -90.5, 30.5), box(-91.8, 29.6, -91.6, 29.8)], crs=4326)
    cells = cells_per_parish(g, lat, lon, valid)
    assert list(cells[0]) == [0] and list(cells[1]) == [3] and list(cells[2]) == [3], cells       # c has no land cell inside: nearest land cell
    # six years of one calendar month, the last one wetter than all earlier ones in parish 0, drier in parish 1
    months = [(2018 + i, 6) for i in range(7)]
    x = np.array([[10 + i, 30 - i] for i in range(7)], float)
    cur, normal, pct, pctile, n = assess(months, x, 6)
    assert n == 6 and pctile[0] == 100 and pctile[1] == 0 and round(pct[0]) == round(16 / 12.5 * 100)
    assert assess(months[:5], x[:5], 4) is None                               # only 4 earlier years
    assert wetness_category(pctile[0]) == "very_wet"
    # the month still running, and a month with too few sample days, are left out
    have = {}
    for d in SAMPLE_DAYS:
        have[day_key(2026, 8, d)] = (np.full((2, 2), 0.3, "float32"), np.full((2, 2), 0.2, "float32"))
    for d in SAMPLE_DAYS[:2]:
        have[day_key(2026, 7, d)] = (np.full((2, 2), 0.3, "float32"), np.full((2, 2), 0.2, "float32"))
    mo, r, s = monthly_parish_means(have, [np.array([0]), np.array([3])], (2026, 9))
    assert mo == [(2026, 8)] and abs(r[0, 0] - 0.3) < 1e-6 and abs(s[0, 1] - 0.2) < 1e-6
    print("self-test passed: 4 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    today = dt.date.today()
    have, (lat, lon), source = load_real(today)
    build(load_parishes(), have, lat, lon, source, today)


def build(gdf, have, lat, lon, source, today):
    valid = ~np.isnan(next(iter(have.values()))[0])
    cells = cells_per_parish(gdf, lat, lon, valid)
    months, root, surf = monthly_parish_means(have, cells, (today.year, today.month))
    # rate the same numbers the history file holds (4 decimals), so the summary text and the map never disagree on ties
    root, surf = np.round(root, 4), np.round(surf, 4)
    if not months:
        sys.exit("No complete month of SMAP data yet.")
    T = len(months) - 1
    now = assess(months, root, T)
    if now is None:
        sys.exit("Not enough earlier years to compare with.")
    cur, normal, pct, pctile, n = now
    s_now = assess(months, surf, T)
    steps = list(range(max(0, T - HISTORY_MONTHS + 1), T + 1))
    hist = [assess(months, root, t) for t in steps]
    y, m = months[T]
    label = f"{y}-{m:02d}"
    print(f"{len(months)} complete months, latest = {label}, compared with {n} earlier years, grid {len(lat)}x{len(lon)}")

    notes = ["driest 10% of years", "driest 10 to 30% of years", "middle 40% of years",
             "wettest 10 to 30% of years", "wettest 10% of years"]
    cats = [dict(c, note=t) for c, t in zip(WETNESS, notes)] + [{"key": "not_rated", "label": "Not rated", "note": "no usable land cell", "color": "#bdbdbd"}]
    names = {c["key"]: c["label"] for c in cats}
    parishes = {}
    for i, row in gdf.iterrows():
        if np.isnan(cur[i]):
            parishes[row["id"]] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "Not rated", "rv": None, "rows": [],
                                   "big_note": "No usable SMAP land cell for this parish."}
            continue
        cat = wetness_category(pctile[i])
        parishes[row["id"]] = {
            "name": row["name"], "cat": cat, "rv": round(float(pct[i]), 1),
            "big": f"{pct[i]:.0f}%",
            "big_note": f"of normal root-zone soil moisture, {ym_text(label)}",
            "tip": f"{names[cat]} · {pct[i]:.0f}% of normal",
            "rows": [
                ["Root zone (0–100 cm)", f"{cur[i]:.2f} m³/m³"],
                [f"Normal for {MON[m - 1]}", f"{normal[i]:.2f} m³/m³"],
                ["Surface (0–5 cm)", f"{s_now[0][i]:.2f} m³/m³ ({s_now[2][i]:.0f}% of normal)" if s_now else "n/a"],
                ["Earlier years that were drier", f"{round(pctile[i] / 100 * n)} of {n}"],
            ],
            "v": [None if h is None else round(float(h[2][i] - 100), 1) for h in hist],
            "c": ["not_rated" if h is None else wetness_category(h[3][i]) for h in hist],
        }

    def series(x):
        return {row["id"]: [None if np.isnan(v) else round(float(v), 4) for v in x[:, i]] for i, row in gdf.iterrows()}

    write_json("soil_history.json", {
        "months": [f"{yy}-{mm:02d}" for (yy, mm) in months], "min_years": MIN_REF_YEARS, "sample_days": SAMPLE_DAYS,
        "series": [{"key": "root", "label": "Root zone (0–100 cm)", "unit": "m³/m³"}, {"key": "surface", "label": "Surface (0–5 cm)", "unit": "m³/m³"}],
        "values": {"root": series(root), "surface": series(surf)},
    })
    print(f"Wrote data/soil_history.json: {len(months)} months")

    rows_m = []
    for t in range(len(months)):
        r = assess(months, root, t)
        if r is None:
            continue
        _, _, pc, pt, _ = r
        rows_m.append((f"{months[t][0]}-{months[t][1]:02d}", ym_text(f"{months[t][0]}-{months[t][1]:02d}"), list(pc),
                       [None if np.isnan(x) else wetness_category(x) for x in pt]))
    write_months("soil", list(gdf["id"]), rows_m, [c["key"] for c in cats], "not_rated", "against the same month in earlier years since 2015",
                 "{v}%", "of normal root-zone soil moisture, {label}", "{cat} · {v}% of normal", "Root-zone soil moisture as % of normal")
    write_layer("soil", {
        "label": "Soil moisture", "title": "Root-zone soil moisture compared with normal",
        "subtitle": f"{ym_text(label)}, against {MON[m - 1]} in {n} earlier years",
        "source": source, "demo": False, "build": BUILD, "categories": cats, "validation": "soil",
        "rank": {"high": "Wettest compared with normal", "low": "Driest compared with normal", "note": "Ranked by soil moisture as a percentage of normal."},
        "how": ("Each parish shows the average moisture in the top metre of soil for the month shown, compared with the "
                "same month in every other year since 2015. \"Very dry\" means that month ranks in the driest 10% of "
                "those years, \"dry\" in the driest 30%, and the same in reverse for \"wet\" and \"very wet\"."),
        "limits": [
            "The values come from NASA's SMAP Level-4 product, which blends satellite observations into a land model. It is an estimate, not a direct measurement at depth.",
            f"The SMAP record starts in 2015, so \"normal\" rests on only {n} earlier years. Rankings are coarser than for rainfall.",
            "The grid is about 9 km. It suits parish averages, not individual fields, and small parishes rest on one or two grid cells.",
            "Over forest, marsh and open water the satellite signal is weak, so values there lean more on the model. Parishes along the coast include a lot of water and wetland.",
            f"Each month is sampled on up to {len(SAMPLE_DAYS)} days at one time of day, not averaged over every hour.",
            "The 'Check against the stations' table under the map compares SMAP with the LaCADIAN soil sensors. The stations record only 6 to 21 months, so that check is limited.",
        ],
        "credits": [{"text": "Soil moisture: NASA SMAP L4 (SPL4SMGP), NSIDC DAAC", "url": "https://nsidc.org/data/spl4smgp"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 50, "unit": "% vs normal",
                  "x": [MON[months[t][1] - 1] for t in steps],
                  "caption": "Past 12 months, root zone", "top": "wetter than normal", "bottom": "drier"},
        "parishes": parishes,
    })


if __name__ == "__main__":
    main()
