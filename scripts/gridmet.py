#!/usr/bin/env python3
"""
LaCADIAN site - daily rainfall for every parish, from gridMET.

gridMET (Abatzoglou 2013, University of California Merced and the University of Idaho) is a daily, 4 km
precipitation grid for the contiguous United States from 1979 to about two days ago. It blends PRISM, which is
built from rain gauges, with a land-model reanalysis. This script downloads only the Louisiana window, one year
at a time, through the NetCDF Subset Service of the gridMET THREDDS server, and averages it by parish.

It saves cache/gridmet_rain.npz, which the rainfall, dry-spell and validation scripts read:
    dates         YYYY-MM-DD
    parish_ids    five-digit FIPS codes
    rain          mm per day, [days, parishes]  (mean of the grid cells whose centre is inside the parish)
    station_ids   LaCADIAN stations (from data/stations.json, if present)
    station_rain  mm per day at the grid cell nearest each station, [days, stations]

Years before the current one are downloaded once. The current year is downloaded again every run, because the
newest days are revised.

Run:
  python scripts/gridmet.py
  python scripts/gridmet.py --self-test
"""
import argparse
import datetime as dt
import json
import re
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BBOX, CACHE, DATA, get_url, load_parishes  # noqa: E402

# ---- settings you may want to change -------------------------------------
FIRST_YEAR = 1991                     # the 1991-2020 normal needs these years
BASES = ["https://www.reacchpna.org/thredds/ncss/MET/pr",
         "http://thredds.northwestknowledge.net:8080/thredds/ncss/MET/pr"]    # tried in this order
VAR_NAMES = ["precipitation_amount", "pr"]
CACHE_FILE = CACHE / "gridmet_rain.npz"
MAX_MM = 500.0                        # a daily value above this cannot be right and is treated as missing
# --------------------------------------------------------------------------


# ============================================================ reading one yearly NetCDF file
def read_nc(path, parish_geoms, points):
    """-> (dates, parish[time, n], point[time, m]) from one subset file.

    parish_geoms: GeoDataFrame of parishes. points: [(lat, lon)] of the stations.
    Each parish is the mean of the grid cells whose centre is inside it (or the nearest cell, for a parish smaller than a cell).
    """
    import geopandas as gpd
    import netCDF4
    ds = netCDF4.Dataset(path)
    try:
        var = next((v for v in ds.variables.values() if v.ndim == 3), None)
        if var is None:
            raise KeyError("no three-dimensional variable in the file")
        tname, yname, xname = var.dimensions
        t, lat, lon = ds.variables[tname], ds.variables[yname][:], ds.variables[xname][:]
        units = getattr(t, "units", "days since 1900-01-01")
        m = re.match(r"days since (\d{4})-(\d\d)-(\d\d)", units)
        if not m:
            raise ValueError(f"unexpected time units: {units}")
        base = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        dates = [(base + dt.timedelta(days=int(d))).isoformat() for d in np.asarray(t[:]).astype(float)]
        a = np.ma.filled(var[:].astype("float32"), np.nan)
    finally:
        ds.close()
    a[(a < 0) | (a > MAX_MM)] = np.nan
    la, lo = np.meshgrid(np.asarray(lat, float), np.asarray(lon, float), indexing="ij")
    pts = gpd.GeoDataFrame({"cell": np.arange(la.size)}, geometry=gpd.points_from_xy(lo.ravel(), la.ravel()), crs=parish_geoms.crs)
    hit = gpd.sjoin(pts, parish_geoms[["geometry"]], predicate="within")
    groups = hit.groupby("index_right")["cell"].apply(np.array).to_dict()
    flat = a.reshape(a.shape[0], -1)
    cols = []
    for i, geom in enumerate(parish_geoms.geometry):
        if i in groups:
            c = groups[i]
        else:
            p = geom.representative_point()
            c = np.array([np.argmin((la.ravel() - p.y) ** 2 + (lo.ravel() - p.x) ** 2)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)          # a parish with no data on a day gives NaN, not a warning
            cols.append(np.nanmean(flat[:, c], axis=1))
    parish = np.stack(cols, axis=1).astype("float32")
    pcols = []
    for (y, x) in points:
        k = int(np.argmin((la.ravel() - y) ** 2 + (lo.ravel() - x) ** 2))
        pcols.append(flat[:, k])
    point = np.stack(pcols, axis=1).astype("float32") if pcols else np.zeros((len(dates), 0), "float32")
    return dates, parish, point


# ============================================================ downloading
def subset_url(base, year, var, time_end):
    n, w, e, s = BBOX[3], BBOX[0], BBOX[2], BBOX[1]
    return (f"{base}/pr_{year}.nc?var={var}&north={n}&west={w}&east={e}&south={s}&horizStride=1"
            f"&time_start={year}-01-01T00:00:00Z&time_end={time_end}&timeStride=1&accept=netcdf")


def time_span_end(base, year):
    """The last day of the yearly file, read from its NCSS description; None if it cannot be read."""
    try:
        r = get_url(f"{base}/pr_{year}.nc/dataset.xml", tries=2, timeout=60)
        m = re.search(r"<TimeSpan>.*?<end>([^<]+)</end>", r.text, re.S)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def download_year(year, today):
    """Download one subset file into a temporary path and return it, or raise if every server fails."""
    errors = []
    for base in BASES:
        end = time_span_end(base, year) or (f"{year}-12-31T00:00:00Z" if year < today.year else f"{today.isoformat()}T00:00:00Z")
        for var in VAR_NAMES:
            try:
                r = get_url(subset_url(base, year, var, end), tries=3, timeout=300)
                if len(r.content) < 2000 or r.content[:3] not in (b"CDF", b"\x89HD"):
                    raise RuntimeError("the reply is not a NetCDF file: " + r.text[:120].replace("\n", " "))
                f = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
                f.write(r.content)
                f.close()
                return f.name
            except Exception as e:
                errors.append(f"{base.split('/')[2]} {var}: {type(e).__name__} {str(e)[:100]}")
    raise RuntimeError(f"gridMET {year} could not be downloaded. " + " | ".join(errors))


# ============================================================ the cache
def load_cache():
    if not CACHE_FILE.exists():
        return None
    z = np.load(CACHE_FILE, allow_pickle=False)
    return {k: z[k] for k in z.files}


def save_cache(dates, parish_ids, rain, station_ids, station_rain):
    CACHE.mkdir(exist_ok=True)
    np.savez_compressed(CACHE_FILE, dates=np.array(dates), parish_ids=np.array(parish_ids), rain=rain,
                        station_ids=np.array(station_ids), station_rain=station_rain)


def stations_list():
    f = DATA / "stations.json"
    if not f.exists():
        return [], []
    s = json.loads(f.read_text())["stations"]
    return [x["id"] for x in s], [(x["lat"], x["lon"]) for x in s]


def merge(old, dates, parish, point):
    """Add (or replace) days in the cache arrays. old: dict from load_cache or None. Returns sorted arrays."""
    rows = {}
    if old is not None:
        for i, d in enumerate(old["dates"].tolist()):
            rows[d] = (old["rain"][i], old["station_rain"][i])
    for i, d in enumerate(dates):
        rows[d] = (parish[i], point[i])
    ds = sorted(rows)
    return ds, np.stack([rows[d][0] for d in ds]), np.stack([rows[d][1] for d in ds])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    today = dt.date.today()
    gdf = load_parishes()
    sids, pts = stations_list()
    old = load_cache()
    have = {}
    if old is not None:
        for d in old["dates"].tolist():
            have[d[:4]] = have.get(d[:4], 0) + 1
        if list(old["parish_ids"]) != list(gdf["id"]) or list(old["station_ids"]) != sids:
            print("The parish or station list changed: starting the rainfall record again.")
            old, have = None, {}
    dates = parish = point = None
    failed = []
    for year in range(FIRST_YEAR, today.year + 1):
        expected = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
        if year < today.year and have.get(str(year), 0) >= expected:
            continue
        try:
            path = download_year(year, today)
        except Exception as e:
            print(f"  {year}: {e}", flush=True)
            failed.append(year)
            continue
        try:
            d, p, q = read_nc(path, gdf, pts)
        finally:
            Path(path).unlink(missing_ok=True)
        ds, rain, srain = merge(old, d, p, q)
        old = {"dates": np.array(ds), "parish_ids": np.array(gdf["id"]), "rain": rain, "station_ids": np.array(sids), "station_rain": srain}
        save_cache(ds, list(gdf["id"]), rain, sids, srain)
        print(f"  {year}: {len(d)} days read, record now {ds[0]} to {ds[-1]}", flush=True)
    if old is None:
        sys.exit("No gridMET rainfall could be downloaded. See the messages above.")
    if failed:
        print(f"These years could not be downloaded and will be tried again next run: {failed}")
    n = len(old["dates"])
    print(f"Rainfall record: {n} days, {old['dates'][0]} to {old['dates'][-1]}, {len(gdf)} parishes, {len(sids)} station cells")
    if failed and failed[-1] == today.year:
        sys.exit("The current year could not be downloaded; the earlier record is kept.")


# ============================================================ test
def self_test():
    """Write a small NetCDF like the server's reply and check the parish and station averages."""
    import geopandas as gpd
    import netCDF4
    from shapely.geometry import box
    lat = np.array([32.0, 31.0, 30.0])                    # gridMET runs north to south
    lon = np.array([-92.0, -91.0, -90.0])
    data = np.arange(2 * 3 * 3, dtype="float32").reshape(2, 3, 3)
    data[0, 0, 0] = -32767                                 # fill value: missing
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.nc")
        ds = netCDF4.Dataset(path, "w")
        ds.createDimension("day", 2); ds.createDimension("lat", 3); ds.createDimension("lon", 3)
        d = ds.createVariable("day", "f8", ("day",)); d.units = "days since 1900-01-01 00:00:00"; d[:] = [46021, 46022]   # 2026-01-01 is day 46021
        ds.createVariable("lat", "f4", ("lat",))[:] = lat
        ds.createVariable("lon", "f4", ("lon",))[:] = lon
        v = ds.createVariable("precipitation_amount", "f4", ("day", "lat", "lon"), fill_value=-32767.0)
        v[:] = np.ma.masked_equal(data, -32767)
        ds.close()
        gdf = gpd.GeoDataFrame({"id": ["22001", "22003", "22005"]},
                               geometry=[box(-92.5, 31.5, -91.5, 32.5),      # contains the cell at (32, -92) only
                                         box(-91.5, 29.5, -89.5, 31.5),      # contains cells (31,-91), (30,-91), (31,-90), (30,-90)
                                         box(-95, 25, -94.9, 25.1)],         # far away: nearest cell is used
                               crs=4326)
        dates, parish, point = read_nc(path, gdf, [(30.1, -90.1)])
    assert dates == ["2026-01-01", "2026-01-02"], dates
    assert np.isnan(parish[0, 0]) and parish[1, 0] == 9.0, parish         # the missing cell makes the first parish empty on day 0 only
    assert parish[0, 1] == np.mean([4, 5, 7, 8]) and parish[1, 1] == np.mean([13, 14, 16, 17]), parish
    assert parish[0, 2] == data[0, 2, 0] and point[0, 0] == data[0, 2, 2] and point[1, 0] == data[1, 2, 2]
    # merging replaces a day and keeps the others in order
    ds1, r1, s1 = merge(None, ["2026-01-02", "2026-01-01"], np.array([[1, 2, 3], [4, 5, 6]], "float32"), np.array([[7], [8]], "float32"))
    assert ds1 == ["2026-01-01", "2026-01-02"] and r1[0, 0] == 4
    old = {"dates": np.array(ds1), "rain": r1, "station_rain": s1}
    ds2, r2, _ = merge(old, ["2026-01-02", "2026-01-03"], np.array([[9, 9, 9], [1, 1, 1]], "float32"), np.array([[0], [0]], "float32"))
    assert ds2 == ["2026-01-01", "2026-01-02", "2026-01-03"] and r2[1, 0] == 9 and r2[0, 0] == 4
    # the URL names the Louisiana window
    u = subset_url(BASES[0], 2026, "precipitation_amount", "2026-10-17T00:00:00Z")
    assert "pr_2026.nc" in u and "north=33.1" in u and "accept=netcdf" in u
    print("self-test passed: 5 groups")


if __name__ == "__main__":
    main()
