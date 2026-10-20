#!/usr/bin/env python3
"""
LaCADIAN site - vegetation greenness by parish.

Source: NASA VIIRS monthly vegetation index (VNP13A3, 1 km NDVI), from 2012. NDVI runs from about 0 (bare ground) to
about 0.9 (dense green vegetation).

Indicator: average NDVI of each parish for the latest month, compared with the same calendar month in every earlier year.

Only good-quality pixels are used. A parish is not rated when too few of its pixels are usable (clouds, and open water
along the coast, are left out).

Needs the same NASA Earthdata login as the soil moisture layer:
  EARTHDATA_USERNAME and EARTHDATA_PASSWORD   (or EARTHDATA_TOKEN)

Run:
  python scripts/vegetation.py
  python scripts/vegetation.py --self-test
"""
import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BBOX, BOUNDARY_CREDIT, CACHE, MON, WETNESS, load_parishes, wetness_category, write_json, write_layer, ym_text  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
SHORT_NAME = "VNP13A3"
VERSION = "002"                          # change here if NASA releases a new version
FIRST_MONTH = (2012, 2)                  # first full month of VIIRS
MAX_RELIABILITY = 4                      # pixel reliability rank kept (0 best ... 4 pass; 5+ poor or cloudy)
MIN_USABLE = 0.20                        # share of a parish's pixels that must be usable (coastal parishes include open water)
MIN_REF_YEARS = 5                        # earlier years needed before a month is rated
HISTORY_MONTHS = 12
SAVE_EVERY = 20
RETRIES = 3
# --------------------------------------------------------------------------
CACHE_FILE = CACHE / "vegetation.npz"

# the standard NASA sinusoidal grid used by MODIS and VIIRS land products
R = 6371007.181
TILE_M = 1111950.5197
X_MIN, Y_MAX = -20015109.354, 10007554.677
NPIX = 1200
SINU = f"+proj=sinu +R={R} +lon_0=0 +units=m +no_defs"


def tile_transform(tile):
    h, v = int(tile[1:3]), int(tile[4:6])
    pix = TILE_M / NPIX
    return Affine(pix, 0, X_MIN + h * TILE_M, 0, -pix, Y_MAX - v * TILE_M)


def tiles_for(bbox=BBOX):
    """The tiles ('h10v05') of the sinusoidal grid that cover a lon/lat box."""
    west, south, east, north = bbox
    tiles = set()
    for lat in np.linspace(south, north, 25):
        for lon in np.linspace(west, east, 25):
            x = R * np.radians(lon) * np.cos(np.radians(lat))
            y = R * np.radians(lat)
            h = int((x - X_MIN) // TILE_M)
            v = int((Y_MAX - y) // TILE_M)
            tiles.add(f"h{h:02d}v{v:02d}")
    return sorted(tiles)


def parish_index(gdf_sinu, tile):
    """Raster of parish numbers (1..n, 0 = outside Louisiana) on one tile's grid."""
    return rasterize(((g, i + 1) for i, g in enumerate(gdf_sinu.geometry)),
                     out_shape=(NPIX, NPIX), transform=tile_transform(tile), fill=0, dtype="int32")


def read_ndvi(fobj):
    """Return NDVI (float, NaN where missing) and the pixel reliability rank from one file."""
    import h5py
    found = {}

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            low = name.lower()
            if low.endswith("ndvi"):
                found["ndvi"] = obj
            elif "pixel reliability" in low:
                found["rel"] = obj

    with h5py.File(fobj, "r") as f:
        f.visititems(visit)
        if "ndvi" not in found or "rel" not in found:
            raise KeyError("NDVI or pixel reliability dataset not found in file")
        d = found["ndvi"]
        raw = d[...].astype("float32")
        sf = float(np.ravel(d.attrs.get("scale_factor", 10000.0))[0])
        rel = found["rel"][...].astype("int16")
    ndvi = raw / sf if sf > 1 else raw * sf        # stored as whole numbers, e.g. 6500 = 0.65
    ndvi[(ndvi < -0.2) | (ndvi > 1.0)] = np.nan
    return ndvi, rel


def read_with_retry(earthaccess, granule, key):
    for attempt in range(1, RETRIES + 1):
        try:
            fobj = earthaccess.open([granule])[0]
            try:
                return read_ndvi(fobj)
            finally:
                try:
                    fobj.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"  {key}: attempt {attempt} failed ({type(e).__name__}: {str(e)[:120]})", flush=True)
            if attempt < RETRIES:
                time.sleep(20 * attempt)
                try:
                    earthaccess.login(strategy="environment")
                except Exception:
                    pass
    return None


def tally(ndvi, rel, idx, nd):
    """Per parish: sum of NDVI over usable pixels, and how many pixels were usable."""
    ok = (idx > 0) & ~np.isnan(ndvi) & (rel >= 0) & (rel <= MAX_RELIABILITY)
    s = np.bincount(idx[ok], weights=ndvi[ok], minlength=nd + 1)[1:]
    n = np.bincount(idx[ok], minlength=nd + 1)[1:]
    return s.astype("float32"), n.astype("int32")


def load_cache():
    if not CACHE_FILE.exists():
        return {}
    z = np.load(CACHE_FILE, allow_pickle=False)
    return {k: (z["s"][i], z["n"][i]) for i, k in enumerate(z["keys"].tolist())}


def save_cache(have):
    CACHE.mkdir(exist_ok=True)
    keys = sorted(have)
    np.savez_compressed(CACHE_FILE, keys=np.array(keys),
                        s=np.stack([have[k][0] for k in keys]), n=np.stack([have[k][1] for k in keys]))


def load_real(gdf, tiles, today):
    import earthaccess
    from common import cmr_search, earthdata_login
    earthdata_login()                                  # tries several times; exits with a plain message if NASA is unreachable
    have = load_cache()
    found = cmr_search(short_name=SHORT_NAME, version=VERSION, count=-1, bounding_box=BBOX,
                                    temporal=(f"{FIRST_MONTH[0]}-{FIRST_MONTH[1]:02d}-01", today.isoformat()))
    todo = {}
    for g in found:
        name = g.data_links()[0].rsplit("/", 1)[1]
        m = re.search(r"\.A(\d{4})(\d{3})\.(h\d{2}v\d{2})\.", name)
        if not m or m.group(3) not in tiles:
            continue
        day = dt.date(int(m.group(1)), 1, 1) + dt.timedelta(days=int(m.group(2)) - 1)
        key = f"{day.year}-{day.month:02d}|{m.group(3)}"
        if key not in have:
            todo[key] = g
    print(f"{len(found)} files listed, {len(todo)} to read, {len(have)} cached")
    if not found and not have:
        sys.exit(f"No {SHORT_NAME} v{VERSION} files were found. Check VERSION in scripts/vegetation.py.")

    gs = gdf.to_crs(SINU)
    index = {t: parish_index(gs, t) for t in tiles}
    done, skipped = 0, []
    for key in sorted(todo):
        got = read_with_retry(earthaccess, todo[key], key)
        if got is None:
            skipped.append(key)
            continue
        have[key] = tally(got[0], got[1], index[key.split("|")[1]], len(gdf))
        done += 1
        if done % SAVE_EVERY == 0:
            save_cache(have)
            print(f"  {done} files read (up to {key})", flush=True)
    if skipped:
        print(f"Could not read {len(skipped)} file(s), they will be tried again next run: {', '.join(skipped)}")
    save_cache(have)
    total = sum(np.bincount(index[t].ravel(), minlength=len(gdf) + 1)[1:] for t in tiles)   # pixels per parish
    return have, total, f"NASA VIIRS {SHORT_NAME} v{VERSION}"


def monthly(have, total, tiles):
    """Months with every tile -> (months, ndvi[time, parish], usable share[time, parish])."""
    months, mean, share = [], [], []
    for ym in sorted({k.split("|")[0] for k in have}):
        keys = [f"{ym}|{t}" for t in tiles]
        if not all(k in have for k in keys):
            continue
        s = sum(have[k][0].astype("float64") for k in keys)
        n = sum(have[k][1].astype("float64") for k in keys)
        frac = n / np.maximum(total, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.where((n > 0) & (frac >= MIN_USABLE), s / n, np.nan)
        months.append((int(ym[:4]), int(ym[5:7])))
        mean.append(v)
        share.append(frac)
    return months, np.array(mean), np.array(share)


def assess(months, x, t):
    """Compare month t with the same calendar month in all earlier years, parish by parish."""
    y, m = months[t]
    ref_i = [i for i, (yy, mm) in enumerate(months) if mm == m and yy < y]
    cur = x[t]
    nd = x.shape[1]
    normal, pct, pctile, nref = (np.full(nd, np.nan) for _ in range(4))
    if not ref_i:
        return cur, normal, pct, pctile, nref
    ref = x[ref_i]
    valid = ~np.isnan(ref)
    cnt = valid.sum(axis=0)
    ok = (cnt >= MIN_REF_YEARS) & ~np.isnan(cur)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nansum(ref, axis=0) / np.maximum(cnt, 1)
        less = (np.where(valid, ref, np.inf) < cur).sum(axis=0) + 0.5 * (np.where(valid, ref, np.inf) == cur).sum(axis=0)
        normal[ok] = mean[ok]
        pct[ok] = cur[ok] / mean[ok] * 100
        pctile[ok] = less[ok] / cnt[ok] * 100
    nref[ok] = cnt[ok]
    return cur, normal, pct, pctile, nref


def self_test():
    tiles = tiles_for()
    assert tiles == ["h09v05", "h09v06", "h10v05", "h10v06"] or set(tiles) <= {"h09v05", "h09v06", "h10v05", "h10v06", "h08v05", "h08v06"}, tiles
    assert {"h10v05", "h10v06"} <= set(tiles)
    # tally: usable pixels only
    idx = np.array([[1, 1, 2], [2, 0, 0]], "int32")
    ndvi = np.array([[0.5, np.nan, 0.7], [0.9, 0.4, 0.4]], "float32")
    rel = np.array([[0, 0, 4], [5, 0, 0]], "int16")
    s, n = tally(ndvi, rel, idx, 2)
    assert list(n) == [1, 1] and abs(s[0] - 0.5) < 1e-6 and abs(s[1] - 0.7) < 1e-6      # NaN, poor quality and outside pixels are left out
    # monthly needs every tile; low usable share gives NaN
    have, total = {}, np.array([100, 100])
    for ym in ("2020-07", "2021-07", "2022-07", "2023-07", "2024-07", "2025-07", "2026-07"):
        for ti, t in enumerate(("h10v05", "h10v06")):
            have[f"{ym}|{t}"] = (np.array([30.0, 3.0], "float32"), np.array([50, 5], "int32"))
    have["2026-08|h10v05"] = (np.array([30.0, 3.0], "float32"), np.array([50, 5], "int32"))      # second tile missing: month not used
    months, v, share = monthly(have, total, ["h10v05", "h10v06"])
    assert len(months) == 7 and months[-1] == (2026, 7)
    assert abs(v[0, 0] - 0.6) < 1e-9 and np.isnan(v[0, 1]) and share[0, 0] == 1.0 and abs(share[0, 1] - 0.10) < 1e-9     # 10% usable: too few
    # assessing: the last year greener than all earlier ones
    x = np.array([[0.5 + 0.01 * i, 0.4] for i in range(7)])
    cur, normal, pct, pctile, nref = assess([(2020 + i, 7) for i in range(7)], x, 6)
    assert nref[0] == 6 and pctile[0] == 100 and pctile[1] == 50 and wetness_category(pctile[0]) == "very_wet"
    print("self-test passed: 4 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    today = dt.date.today()
    gdf = load_parishes()
    tiles = tiles_for()
    have, total, source = load_real(gdf, tiles, today)
    build(gdf, have, total, tiles, source)


def build(gdf, have, total, tiles, source):
    months, ndvi, share = monthly(have, total, tiles)
    ndvi = np.round(ndvi, 4)      # rate the same numbers the history file holds, so text and map agree on ties
    if not months:
        sys.exit("No complete month of vegetation data yet.")
    T = len(months) - 1
    cur, normal, pct, pctile, nref = assess(months, ndvi, T)
    steps = list(range(max(0, T - HISTORY_MONTHS + 1), T + 1))
    hist = [assess(months, ndvi, t) for t in steps]
    y, m = months[T]
    label = f"{y}-{m:02d}"
    print(f"{len(months)} complete months, latest = {label}, rated parishes = {int((~np.isnan(pctile)).sum())} of {len(gdf)}")

    labels = ["Much less green", "Less green", "Near normal", "Greener", "Much greener"]
    notes = ["lowest 10% of years", "lowest 10 to 30% of years", "middle 40% of years", "highest 10 to 30% of years", "highest 10% of years"]
    cats = [dict(c, label=lab, note=t) for c, lab, t in zip(WETNESS, labels, notes)]
    cats.append({"key": "cloud", "label": "Too cloudy or too much water", "note": "not rated", "color": "#bdbdbd"})
    cats.append({"key": "few", "label": "Not enough years", "note": f"under {MIN_REF_YEARS} other years", "color": "#dcd6c8"})
    names = {c["key"]: c["label"] for c in cats}

    parishes = {}
    for i, row in gdf.iterrows():
        rated = not np.isnan(pctile[i])
        has_value = not np.isnan(cur[i])
        cat = wetness_category(pctile[i]) if rated else ("few" if has_value else "cloud")
        rows = [["Usable pixels this month", f"{share[T][i] * 100:.0f}%"]]
        if rated:
            rows = [["Greenness (NDVI)", f"{cur[i]:.2f}"], [f"Normal for {MON[m - 1]}", f"{normal[i]:.2f}"],
                    ["Earlier years that were less green", f"{round(pctile[i] / 100 * nref[i])} of {int(nref[i])}"],
                    ["Earlier years in the comparison", f"{int(nref[i])}"]] + rows
        parishes[row["id"]] = {
            "name": row["name"], "cat": cat, "rv": round(float(pct[i]), 1) if rated else None,
            "big": f"{pct[i]:.0f}%" if rated else "–",
            "big_note": (f"of normal greenness, {ym_text(label)}" if rated
                         else f"Fewer than {MIN_REF_YEARS} other years with a value for this month, so it is not rated." if has_value
                         else "Too few cloud-free land pixels this month to rate this parish."),
            "tip": f"{names[cat]} · {pct[i]:.0f}% of normal" if rated else ("Not enough years to rate" if has_value else "Too cloudy to rate"),
            "rows": rows,
            "v": [None if np.isnan(h[2][i]) else round(float(h[2][i] - 100), 1) for h in hist],
            "c": ["cloud" if np.isnan(h[3][i]) else wetness_category(h[3][i]) for h in hist],
        }

    write_json("vegetation_history.json", {
        "months": [f"{yy}-{mm:02d}" for (yy, mm) in months], "min_years": MIN_REF_YEARS,
        "series": [{"key": "ndvi", "label": "Greenness (NDVI)", "unit": ""}],
        "values": {"ndvi": {row["id"]: [None if np.isnan(v) else round(float(v), 4) for v in ndvi[:, i]] for i, row in gdf.iterrows()}},
    })

    write_layer("vegetation", {
        "label": "Vegetation", "title": "Vegetation greenness compared with normal",
        "subtitle": f"{ym_text(label)}, against {MON[m - 1]} in earlier years since 2012",
        "source": source, "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Greenest compared with normal", "low": "Least green compared with normal", "note": "Ranked by NDVI as a percentage of normal."},
        "how": (f"Each parish shows how green its vegetation was in {ym_text(label)}, compared with {MON[m - 1]} in each "
                "earlier year since 2012. Greenness is measured by NDVI, a satellite index that rises with the amount of "
                "healthy green leaves. \"Much less green\" means this year ranks in the lowest 10% of those years."),
        "limits": [
            "Greenness covers all vegetation: crops, grass, forest and marsh. A low value can come from dry weather, late planting, flooding, harvest, clearing or a freeze.",
            f"Clouds hide the ground, and coastal parishes include open water. A parish is not rated when under {MIN_USABLE * 100:.0f}% of its pixels were usable that month.",
            "The grid is about 1 km, so it suits parish averages, not individual fields.",
            "The record starts in 2012, so \"normal\" rests on about a dozen years.",
            "The monthly file is published about six weeks after the month ends.",
        ],
        "credits": [{"text": "Vegetation: NASA VIIRS VNP13A3, LP DAAC", "url": "https://lpdaac.usgs.gov/products/vnp13a3v002/"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 30, "unit": "% vs normal", "x": [MON[months[t][1] - 1] for t in steps],
                  "caption": "Past 12 months", "top": "greener than normal", "bottom": "less green"},
        "parishes": parishes,
    })


if __name__ == "__main__":
    main()
