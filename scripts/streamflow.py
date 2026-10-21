#!/usr/bin/env python3
"""
LaCADIAN site - river flow compared with normal, by parish.

Source: USGS stream gauges, daily mean discharge (parameter 00060, cubic feet per second), through the USGS Water Data
OGC API (api.waterdata.usgs.gov). The old waterservices.usgs.gov service is being retired, so it is not used.

Method:
  1. Find the Louisiana gauges that measure discharge, and download each gauge's daily record (from 1991).
  2. For each gauge, take the mean flow of the last 7 days and compare it with the mean flow of the same 7 calendar days in each year of
     1991-2020. The gauge's colour is where this year ranks among those years (a gauge needs at least 15 of them).
  3. A parish gets the median rank of the gauges inside it. A parish with no usable gauge is left grey: nothing is guessed for it.

A free USGS API key (https://api.waterdata.usgs.gov/signup) raises the request limit. If you have one, add it as the repository secret
USGS_API_KEY; the script uses it when present and works without it.

Run:
  python scripts/streamflow.py
  python scripts/streamflow.py --self-test
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOUNDARY_CREDIT, CACHE, MON, WETNESS, load_parishes, pct_rank, wetness_category, write_layer  # noqa: E402

BUILD = 1
API = "https://api.waterdata.usgs.gov/ogcapi/v0"
FIRST_YEAR = 1991
REF_FIRST, REF_LAST = 1991, 2020
WINDOW_DAYS = 7
MIN_WINDOW_DAYS = 5              # days of the 7 that must have a value
MIN_REF = 15                     # reference years a gauge needs
STALE_DAYS = 10                  # a gauge whose newest value is older than this is left out
MIN_LAST_YEARS = 15              # a gauge needs at least this many years of record in the reference period
STATE_NAMES = ("Louisiana",)
MAX_MINUTES = 40                 # stop downloading after this long; what is saved is used now and the rest continues next run
PAUSE = 0.7                      # seconds between requests, to stay under the rate limit
ACTIVE_DAYS = 45                 # a gauge must have reported within this many days
MIN_BEGIN_YEAR = 2006            # and have started before this year, so it can have 15 years of record
CACHE_FILE = CACHE / "usgs_flow.npz"
META_FILE = CACHE / "usgs_flow_sites.json"
EPOCH = dt.date(1970, 1, 1)

CATS = [dict(c, label=l, note=n) for c, l, n in zip(WETNESS,
        ["Much below normal", "Below normal", "Near normal", "Above normal", "Much above normal"],
        ["lowest 10% of years", "lowest 10 to 30% of years", "middle 40% of years", "highest 10 to 30% of years", "highest 10% of years"])] + \
       [{"key": "not_rated", "label": "No usable gauge", "note": "no gauge in the parish with enough record", "color": "#bdbdbd"}]


# ============================================================ talking to the API
class RateLimited(RuntimeError):
    pass


def _get(url, params=None, tries=5):
    import requests
    headers = {"Accept": "application/json"}
    if os.environ.get("USGS_API_KEY"):
        headers["X-Api-Key"] = os.environ["USGS_API_KEY"]
    last = None
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=120)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = r.headers.get("Retry-After", "")
                time.sleep(min(180, int(wait) if wait.isdigit() else 30 * attempt))
                last = RateLimited("HTTP 429, too many requests (a free USGS_API_KEY secret raises the limit)")
                continue
            if r.status_code in (400, 404):
                raise ValueError(f"HTTP {r.status_code}: {r.text[:150]}")
            last = RuntimeError(f"HTTP {r.status_code}")
        except ValueError:
            raise
        except Exception as e:
            last = e
        time.sleep(6 * attempt)
    raise last


def _pages(url, params, cap=60):
    """Every feature of a collection query, following the 'next' links."""
    out, n = [], 0
    data = _get(url, params)
    while True:
        out += data.get("features", [])
        n += 1
        nxt = next((l.get("href") for l in data.get("links", []) if l.get("rel") == "next"), None)
        if not nxt or n >= cap:
            return out
        data = _get(nxt)


def is_louisiana(props):
    return str(props.get("state_name", "")) in STATE_NAMES or str(props.get("state_code", "")) in ("22", "US:22", "LA")


def _day(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def list_gauges(today=None):
    """-> {monitoring_location_id: {"name", "lon", "lat"}} for Louisiana sites with a discharge series that is still reporting
    and started early enough to have a long record. Tidal sites are left out."""
    today = today or dt.date.today()
    base = f"{API}/collections/combined-metadata/items"
    tries = [{"state_name": "Louisiana"}, {"state_code": "22"}, {"state_code": "US:22"}]
    last = None
    for extra in tries:
        try:
            feats = _pages(base, {"f": "json", "limit": 1000, "parameter_code": "00060", **extra})
        except Exception as e:
            last = e
            continue
        sites = {}
        for f in feats:
            p, g = f.get("properties", {}), f.get("geometry") or {}
            if not is_louisiana(p) or str(p.get("parameter_code", "00060")) != "00060":
                continue
            sid = p.get("monitoring_location_id") or p.get("id")
            if not sid or g.get("type") != "Point":
                continue
            if str(p.get("site_type_code") or "") == "ST-TS":
                continue                                                  # tidal stream
            end, begin = _day(p.get("end") or p.get("end_utc")), _day(p.get("begin") or p.get("begin_utc"))
            if end is not None and (today - end).days > ACTIVE_DAYS:
                continue
            if begin is not None and begin.year > MIN_BEGIN_YEAR:
                continue
            sites[sid] = {"name": p.get("monitoring_location_name") or sid, "lon": g["coordinates"][0], "lat": g["coordinates"][1],
                          "type": p.get("site_type_code") or ""}
        if sites:
            return sites
    raise RuntimeError(f"No Louisiana discharge gauges could be listed from the USGS API. {last or ''}")


def fetch_daily(site_id, start, end):
    """-> [(date, value)] of daily mean discharge for one gauge."""
    feats = _pages(f"{API}/collections/daily/items",
                   {"f": "json", "limit": 10000, "monitoring_location_id": site_id, "parameter_code": "00060",
                    "statistic_id": "00003", "time": f"{start}/{end}"})
    out = []
    for f in feats:
        p = f.get("properties", {})
        try:
            out.append((str(p["time"])[:10], float(p["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ============================================================ the cache
def load_cache():
    if not (CACHE_FILE.exists() and META_FILE.exists()):
        return {}
    meta = json.loads(META_FILE.read_text())
    z = np.load(CACHE_FILE, allow_pickle=False)
    out = {}
    for sid, m in meta.items():
        if f"{sid}_d" in z.files:
            out[sid] = dict(m, days=z[f"{sid}_d"], vals=z[f"{sid}_v"])
    return out


def save_cache(series):
    CACHE.mkdir(exist_ok=True)
    META_FILE.write_text(json.dumps({s: {k: v for k, v in d.items() if k not in ("days", "vals")} for s, d in series.items()}))
    arrs = {}
    for s, d in series.items():
        arrs[f"{s}_d"], arrs[f"{s}_v"] = d["days"], d["vals"]
    np.savez_compressed(CACHE_FILE, **arrs)


def to_arrays(rows):
    rows = sorted(set(rows))
    return (np.array([(dt.date.fromisoformat(d) - EPOCH).days for d, _ in rows], "int32"), np.array([v for _, v in rows], "float32"))


def merge(old, rows):
    d2, v2 = to_arrays(rows)
    if old is None:
        return d2, v2
    d = dict(zip(old["days"].tolist(), old["vals"].tolist()))
    d.update(zip(d2.tolist(), v2.tolist()))
    ks = sorted(d)
    return np.array(ks, "int32"), np.array([d[k] for k in ks], "float32")


def download(today):
    sites = list_gauges(today)
    print(f"{len(sites)} Louisiana gauges that are still reporting and have a long record")
    series = load_cache()
    failed, in_a_row, t0 = 0, 0, time.time()
    # gauges we have never downloaded first, then the ones that only need an update
    order = sorted(sites, key=lambda k: (k in series, k))
    for i, sid in enumerate(order):
        m = sites[sid]
        if time.time() - t0 > MAX_MINUTES * 60:
            left = len(order) - i
            print(f"Time limit reached after {MAX_MINUTES} minutes: {left} gauges are left for the next run.")
            break
        time.sleep(PAUSE)
        old = series.get(sid)
        start = dt.date(FIRST_YEAR, 1, 1) if old is None else EPOCH + dt.timedelta(days=int(old["days"][-1]) - 45)
        try:
            rows = fetch_daily(sid, start.isoformat(), today.isoformat())
        except Exception as e:
            failed += 1
            in_a_row += 1
            print(f"  {sid}: {str(e)[:100]}", flush=True)
            if in_a_row >= 12:
                print("Twelve requests in a row failed (rate limit or outage). Stopping for this run; the rest continues next run.")
                break
            if failed >= 8 and not series:
                raise RuntimeError("Too many gauges failed; the USGS service may be down.")
            continue
        in_a_row = 0
        if not rows and old is None:
            continue
        d, v = merge(old, rows)
        series[sid] = dict(m, days=d, vals=v)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1} of {len(order)} gauges", flush=True)
            save_cache(series)
    save_cache(series)
    return series


# ============================================================ the numbers
def window_mean(day_map, end_ord):
    vals = [day_map[o] for o in range(end_ord - WINDOW_DAYS + 1, end_ord + 1) if o in day_map]
    return float(np.mean(vals)) if len(vals) >= MIN_WINDOW_DAYS else None


def gauge_rank(days, vals, today):
    """-> dict(date, flow, pctile, n) for the last 7 days of one gauge, or None when it is stale or has too little record."""
    dm = dict(zip(days.tolist(), vals.tolist()))
    dm = {k: v for k, v in dm.items() if v == v}
    if not dm:
        return None
    last = max(dm)
    if (today - EPOCH).days - last > STALE_DAYS:
        return None
    end = EPOCH + dt.timedelta(days=last)
    cur = window_mean(dm, last)
    if cur is None:
        return None
    refs = []
    for y in range(REF_FIRST, REF_LAST + 1):
        try:
            e = dt.date(y, end.month, end.day)
        except ValueError:
            e = dt.date(y, end.month, 28)
        w = window_mean(dm, (e - EPOCH).days)
        if w is not None:
            refs.append(w)
    if len(refs) < MIN_REF:
        return None
    return {"date": end.isoformat(), "flow": cur, "pctile": pct_rank(cur, refs), "n": len(refs), "median": float(np.median(refs))}


def monthly_ranks(days, vals, months):
    """For each (year, month) in `months`: percentile of the month's mean flow among the same month in 1991-2020, or None."""
    d = (EPOCH + dt.timedelta(days=1))
    dates = [EPOCH + dt.timedelta(days=int(x)) for x in days]
    by = {}
    for dd, v in zip(dates, vals.tolist()):
        if v == v:
            by.setdefault((dd.year, dd.month), []).append(v)
    mean = {k: float(np.mean(x)) for k, x in by.items() if len(x) >= 0.8 * (28 if k[1] == 2 else 30)}
    out = []
    for (y, m) in months:
        if (y, m) not in mean:
            out.append(None)
            continue
        refs = [mean[(ry, m)] for ry in range(REF_FIRST, REF_LAST + 1) if (ry, m) in mean]
        out.append(pct_rank(mean[(y, m)], refs) if len(refs) >= MIN_REF else None)
    return out


def usable(days, vals):
    """A gauge counts when it has enough years in the reference period and is not tidal (tidal flow goes negative)."""
    v = vals[vals == vals]
    if len(v) == 0 or (v < 0).mean() > 0.01:
        return False
    years = {(EPOCH + dt.timedelta(days=int(x))).year for x in days}
    return sum(1 for y in years if REF_FIRST <= y <= REF_LAST) >= MIN_LAST_YEARS


def build(gdf, series, today):
    import geopandas as gpd
    good = {s: d for s, d in series.items() if usable(d["days"], d["vals"])}
    ranks = {s: gauge_rank(d["days"], d["vals"], today) for s, d in good.items()}
    ranks = {s: r for s, r in ranks.items() if r is not None}
    if not ranks:
        sys.exit("No gauge has a recent value and enough record; the streamflow layer is not built.")
    pts = gpd.GeoDataFrame({"sid": list(ranks)}, geometry=gpd.points_from_xy([good[s]["lon"] for s in ranks], [good[s]["lat"] for s in ranks]), crs=gdf.crs)
    hit = gpd.sjoin(pts, gdf[["id", "geometry"]], predicate="within")
    where = dict(zip(hit["sid"], hit["id"]))
    inside = {s: r for s, r in ranks.items() if s in where}
    latest = max(r["date"] for r in inside.values())
    print(f"{len(good)} usable gauges, {len(ranks)} with a recent value, {len(inside)} inside a parish; newest value {latest}")
    # the 12 months before the latest value, for the pop-up chart
    ey, em = int(latest[:4]), int(latest[5:7])
    months = []
    y, m = ey, em
    for _ in range(12):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        months.append((y, m))
    months.reverse()
    mranks = {s: monthly_ranks(good[s]["days"], good[s]["vals"], months) for s in inside}
    names = {c["key"]: c["label"] for c in CATS}
    parishes = {}
    for _, row in gdf.iterrows():
        pid = row["id"]
        gs = sorted((s for s in inside if where[s] == pid), key=lambda s: good[s]["name"])
        if not gs:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "No usable gauge", "rv": None, "rows": [],
                             "big_note": "No USGS gauge inside this parish has a recent value and enough record."}
            continue
        med = float(np.median([inside[s]["pctile"] for s in gs]))
        cat = wetness_category(med)
        rows = [[f"{good[s]['name'].title()[:48]}", f"{inside[s]['flow']:,.0f} cfs, {inside[s]['pctile']:.0f}th percentile"] for s in gs[:6]]
        if len(gs) > 6:
            rows.append(["More gauges", f"{len(gs) - 6} not listed"])
        v, c = [], []
        for k in range(12):
            vals = [mranks[s][k] for s in gs if mranks[s][k] is not None]
            if vals:
                mm = float(np.median(vals))
                v.append(round(mm - 50, 1))
                c.append(wetness_category(mm))
            else:
                v.append(None)
                c.append("not_rated")
        parishes[pid] = {
            "name": row["name"], "cat": cat, "rv": round(med, 1), "big": f"{med:.0f}th",
            "big_note": f"percentile of river flow, last 7 days to {dt.date.fromisoformat(latest):%d %b %Y} ({len(gs)} gauge{'s' if len(gs) != 1 else ''})",
            "tip": f"{names[cat]}, {med:.0f}th percentile, {len(gs)} gauge{'s' if len(gs) != 1 else ''}",
            "rows": rows, "v": v, "c": c}
    ld = dt.date.fromisoformat(latest)
    write_layer("streamflow", {
        "label": "River and streamflow", "title": "River flow compared with normal",
        "subtitle": f"Mean flow of the last 7 days to {ld.day} {ld:%b %Y}, against the same days in 1991–2020",
        "source": "USGS stream gauges, daily mean discharge", "demo": False, "build": BUILD, "categories": CATS,
        "rank": {"high": "Highest flow compared with normal", "low": "Lowest flow compared with normal", "note": "Ranked by the median percentile of the gauges in the parish."},
        "how": ("Each USGS stream gauge's flow over the last 7 days is compared with the flow over the same 7 days in each year from 1991 to 2020. A parish shows the middle rank of the gauges inside it. \"Much below normal\" means the lowest 10% of years, and \"much above normal\" the highest 10%. Parishes with no gauge, or with only gauges that have too little record, are grey."),
        "limits": [
            "Only parishes with a USGS discharge gauge get a colour. A river can be high in a neighbouring parish and this map will not show it.",
            "A gauge measures the river it sits on. The Mississippi and the Atchafalaya reflect rain far upstream and not rain in the parish.",
            "Flow on the lower Mississippi and Atchafalaya is partly controlled by dams, locks and diversions, so a high or low rank is not always weather.",
            "Recent values are provisional and USGS may revise them. Gauges near the coast move with the tide and are left out.",
            f"A gauge needs at least {MIN_REF} of the 30 reference years and a newest value no more than {STALE_DAYS} days old.",
        ],
        "credits": [{"text": "River flow: US Geological Survey, National Water Information System", "url": "https://waterdata.usgs.gov/"}, BOUNDARY_CREDIT],
        "chart": {"kind": "diverging", "cap": 50, "unit": "percentile points", "x": [MON[mm - 1] for _, mm in months],
                  "caption": "Monthly flow rank, past 12 months (middle gauge)", "top": "higher than normal", "bottom": "lower"},
        "parishes": parishes})


# ============================================================ test
def self_test():
    import tempfile
    import geopandas as gpd
    from shapely.geometry import box
    import common
    today = dt.date(2026, 10, 20)
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005"], "name": list("ABC")}, geometry=[box(i, 0, i + 1, 1) for i in range(3)], crs=4326)
    d0 = (dt.date(1991, 1, 1) - EPOCH).days
    n = (today - dt.date(1991, 1, 1)).days + 1
    days = np.arange(d0, d0 + n, dtype="int32")
    rng = np.random.default_rng(4)
    base = 1000 + 200 * rng.standard_normal(n)
    hi = base.copy(); hi[-30:] *= 3                               # gauge in parish A: far above normal lately
    lo = base.copy(); lo[-30:] *= 0.2                             # gauge in parish B: far below
    tidal = base.copy(); tidal[::50] = -50                        # gauge in parish C: tidal, left out
    short = base[-3 * 365:].copy()                                # a gauge with only 3 years: left out
    series = {"USGS-1": {"name": "RIVER A", "lon": 0.5, "lat": 0.5, "days": days, "vals": hi.astype("float32")},
              "USGS-2": {"name": "RIVER B", "lon": 1.5, "lat": 0.5, "days": days, "vals": lo.astype("float32")},
              "USGS-3": {"name": "BAYOU C", "lon": 2.5, "lat": 0.5, "days": days, "vals": tidal.astype("float32")},
              "USGS-4": {"name": "SHORT", "lon": 0.6, "lat": 0.6, "days": days[-3 * 365:], "vals": short.astype("float32")}}
    assert usable(days, hi.astype("float32")) and not usable(days, tidal.astype("float32")) and not usable(days[-3 * 365:], short.astype("float32"))
    r = gauge_rank(days, hi.astype("float32"), today)
    assert r["pctile"] == 100 and r["n"] == 30 and r["date"] == "2026-10-20", r
    assert gauge_rank(days[:-20], hi[:-20].astype("float32"), today) is None            # stale
    # cache round trip and merge
    old = common.CACHE
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        globals()["CACHE"] = Path(tmp) / "c"; globals()["CACHE_FILE"] = globals()["CACHE"] / "a.npz"; globals()["META_FILE"] = globals()["CACHE"] / "m.json"
        save_cache(series)
        back = load_cache()
        assert set(back) == set(series) and back["USGS-1"]["days"].shape == days.shape and back["USGS-1"]["name"] == "RIVER A"
        d, v = merge(back["USGS-1"], [("2026-10-20", 5.0), ("2026-10-21", 6.0)])
        assert d[-1] - d[-2] == 1 and v[-1] == 6.0 and v[-2] == 5.0 and len(d) == len(days) + 1
        build(g, series, today)
        out = json.loads((Path(tmp) / "streamflow.json").read_text())
        p = out["parishes"]
        assert p["22001"]["cat"] == "very_wet" and p["22002" if False else "22003"]["cat"] == "very_dry" and p["22005"]["cat"] == "not_rated", {k: v["cat"] for k, v in p.items()}
        assert len(p["22001"]["v"]) == 12 and p["22001"]["rows"][0][0] == "River A" and out["counts"]["not_rated"] == 1
    common.DATA = common.DATA
    # only active gauges with a long record, no tidal ones
    def feat(sid, begin, end, typ="ST"):
        return {"properties": {"monitoring_location_id": sid, "state_name": "Louisiana", "parameter_code": "00060", "begin": begin, "end": end,
                               "site_type_code": typ, "monitoring_location_name": sid}, "geometry": {"type": "Point", "coordinates": [-91.0, 30.0]}}
    fake = [feat("USGS-A", "1980-01-01", "2026-10-19"), feat("USGS-B", "2015-01-01", "2026-10-19"), feat("USGS-C", "1980-01-01", "2019-01-01"),
            feat("USGS-D", "1980-01-01", "2026-10-19", "ST-TS")]
    global _pages
    keep = _pages
    _pages = lambda *a, **k: fake
    try:
        assert list(list_gauges(today)) == ["USGS-A"], list(list_gauges(today))
    finally:
        _pages = keep
    assert is_louisiana({"state_name": "Louisiana"}) and is_louisiana({"state_code": "22"}) and not is_louisiana({"state_name": "Texas"})
    print("self-test passed: 6 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    today = dt.date.today()
    series = download(today)
    if not series:
        sys.exit("The USGS API returned no daily records.")
    build(load_parishes(), series, today)


if __name__ == "__main__":
    main()
