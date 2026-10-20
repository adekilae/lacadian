#!/usr/bin/env python3
"""
LaCADIAN site - daily air temperature and evaporative demand for every parish, from gridMET.

Same source and method as gridmet.py (rain). Three more daily variables are downloaded, one year at a time, for the Louisiana window and averaged by parish:
  tmmx  daily maximum air temperature (kelvin)
  tmmn  daily minimum air temperature (kelvin)
  pet   reference evapotranspiration, grass (mm per day, ASCE Penman-Monteith)

Each is kept in cache/gridmet_<name>.npz (dates, parish_ids, values). Years before the current one are downloaded once.
The current year is downloaded again each run. If a year cannot be downloaded the earlier record is kept and the run does NOT fail:
climate.py uses whatever record there is.

Run:
  python scripts/gridmet_extra.py
  python scripts/gridmet_extra.py --self-test
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridmet  # noqa: E402
from common import BBOX, CACHE, get_url, load_parishes  # noqa: E402

FIRST_YEAR = 1991
HOSTS = ["https://www.reacchpna.org/thredds/ncss/MET", "http://thredds.northwestknowledge.net:8080/thredds/ncss/MET"]
VARS = {"tmmx": ["air_temperature", "daily_maximum_temperature", "tmmx"],
        "tmmn": ["air_temperature", "daily_minimum_temperature", "tmmn"],
        "pet": ["potential_evapotranspiration", "pet"]}


def cache_file(name):
    return CACHE / f"gridmet_{name}.npz"


def load(name):
    f = cache_file(name)
    if not f.exists():
        return None
    z = np.load(f, allow_pickle=False)
    return {k: z[k] for k in z.files}


def url_for(host, name, year, var, end):
    n, w, e, s = BBOX[3], BBOX[0], BBOX[2], BBOX[1]
    return (f"{host}/{name}/{name}_{year}.nc?var={var}&north={n}&west={w}&east={e}&south={s}&horizStride=1"
            f"&time_start={year}-01-01T00:00:00Z&time_end={end}&timeStride=1&accept=netcdf")


def download_year(name, year, today):
    import tempfile
    errors = []
    for host in HOSTS:
        try:
            r = get_url(f"{host}/{name}/{name}_{year}.nc/dataset.xml", tries=2, timeout=60)
            import re
            m = re.search(r"<TimeSpan>.*?<end>([^<]+)</end>", r.text, re.S)
            end = m.group(1).strip() if m else None
        except Exception:
            end = None
        end = end or (f"{year}-12-31T00:00:00Z" if year < today.year else f"{today.isoformat()}T00:00:00Z")
        for var in VARS[name]:
            try:
                r = get_url(url_for(host, name, year, var, end), tries=3, timeout=300)
                if len(r.content) < 2000 or r.content[:3] not in (b"CDF", b"\x89HD"):
                    raise RuntimeError("the reply is not a NetCDF file: " + r.text[:100].replace("\n", " "))
                f = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
                f.write(r.content)
                f.close()
                return f.name
            except Exception as e:
                errors.append(f"{host.split('/')[2]} {var}: {type(e).__name__} {str(e)[:80]}")
    raise RuntimeError(f"{name} {year} could not be downloaded. " + " | ".join(errors))


def merge(old, dates, values):
    rows = {}
    if old is not None:
        for i, d in enumerate(old["dates"].tolist()):
            rows[d] = old["values"][i]
    for i, d in enumerate(dates):
        rows[d] = values[i]
    ds = sorted(rows)
    return ds, np.stack([rows[d] for d in ds]).astype("float32")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    today = dt.date.today()
    gdf = load_parishes()
    CACHE.mkdir(exist_ok=True)
    missing = []
    for name in VARS:
        old = load(name)
        if old is not None and list(old["parish_ids"]) != list(gdf["id"]):
            print(f"{name}: the parish list changed, starting again.")
            old = None
        have = {}
        if old is not None:
            for d in old["dates"].tolist():
                have[d[:4]] = have.get(d[:4], 0) + 1
        failed = []
        for year in range(FIRST_YEAR, today.year + 1):
            expected = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
            if year < today.year and have.get(str(year), 0) >= expected:
                continue
            try:
                path = download_year(name, year, today)
            except Exception as e:
                print(f"  {name} {year}: {e}", flush=True)
                failed.append(year)
                continue
            try:
                d, p, _ = gridmet.read_nc(path, gdf, [])
            finally:
                Path(path).unlink(missing_ok=True)
            ds, vals = merge(old, d, p)
            old = {"dates": np.array(ds), "parish_ids": np.array(gdf["id"]), "values": vals}
            np.savez_compressed(cache_file(name), dates=old["dates"], parish_ids=old["parish_ids"], values=vals)
            print(f"  {name} {year}: {len(d)} days read, record now {ds[0]} to {ds[-1]}", flush=True)
        if old is None:
            missing.append(name)
        elif failed:
            print(f"{name}: these years could not be downloaded and will be tried again next run: {failed}")
    if missing:
        print(f"No record at all for: {', '.join(missing)}. The temperature and evaporative-demand layers cannot be built yet.")
    else:
        print("Air temperature and evaporative demand records are ready.")


def self_test():
    ds, v = merge(None, ["2026-01-02", "2026-01-01"], np.array([[2, 2], [1, 1]], "float32"))
    assert ds == ["2026-01-01", "2026-01-02"] and v[0, 0] == 1
    ds2, v2 = merge({"dates": np.array(ds), "values": v}, ["2026-01-02", "2026-01-03"], np.array([[9, 9], [3, 3]], "float32"))
    assert ds2 == ["2026-01-01", "2026-01-02", "2026-01-03"] and v2[1, 0] == 9 and v2[0, 0] == 1
    u = url_for(HOSTS[0], "tmmx", 2026, "air_temperature", "2026-10-17T00:00:00Z")
    assert "/tmmx/tmmx_2026.nc?var=air_temperature" in u and "north=33.1" in u
    print("self-test passed: 3 groups")


if __name__ == "__main__":
    main()
