#!/usr/bin/env python3
"""
LaCADIAN site - surface water change by parish, 1984-2021.

Source: JRC Global Surface Water, "transitions" map (version 1.4, 2021). The European Commission's Joint Research Centre
classified every 30 m Landsat pixel in every month from 1984 to 2021 as water or not, and the transitions map compares
the first and last parts of that record. Each pixel is one of: permanent water, new permanent, lost permanent, seasonal,
new seasonal, lost seasonal, seasonal to permanent, permanent to seasonal, ephemeral (only briefly water), or no water.

For each parish the script adds up the area (km2) of each class and publishes:
  gained  = new permanent + new seasonal + seasonal to permanent
  lost    = lost permanent + lost seasonal + permanent to seasonal
  net     = gained - lost, as a percentage of the parish's area (this colours the map)

In coastal Louisiana, water gained is mostly marsh and land that has become open water. Inland, gains are new ponds, reservoirs
and flooding, and losses are drained or dried ponds. The map cannot tell these apart.

It reads only the part of the tiles that covers Louisiana, straight from the JRC's public storage. It is built once and
rebuilt only when this script's BUILD number goes up.

Run:
  python scripts/water.py
  python scripts/water.py --self-test
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BBOX, BOUNDARY_CREDIT, load_parishes, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
URL = "https://storage.googleapis.com/global-surface-water/downloads2021/transitions/transitions_{lon}_{lat}v1_4_2021.tif"
GAIN = (2, 5, 7)
LOSS = (3, 6, 8)
PERMANENT_NOW = (1, 2, 7)
SEASONAL_NOW = (4, 5, 8)
NODATA = 255
CUTS = [-1.0, -0.2, 0.2, 1.0]          # net change as % of the parish area
# --------------------------------------------------------------------------

R = 6371007.181
CATS = [
    ("w0", "Much less water", "net loss of 1% of the parish area or more", "#a63603"),
    ("w1", "Less water", "net loss of 0.2 to 1%", "#fdae61"),
    ("w2", "Little change", "within 0.2% of the parish area", "#f1ede0"),
    ("w3", "More water", "net gain of 0.2 to 1%", "#6baed6"),
    ("w4", "Much more water", "net gain of 1% or more", "#08519c"),
]


def tile_url(lon_w, lat_n):
    ew = "W" if lon_w < 0 else "E"
    ns = "N" if lat_n >= 0 else "S"
    return URL.format(lon=f"{abs(lon_w)}{ew}", lat=f"{abs(lat_n)}{ns}")


def tiles_for(bbox=BBOX):
    """10-degree tiles, named by their top-left corner, that cover a lon/lat box -> [(lon_w, lat_n)]."""
    west, south, east, north = bbox
    out = []
    lon = math.floor(west / 10) * 10
    while lon < east:
        lat = math.ceil(south / 10) * 10
        while lat - 10 < north:
            out.append((lon, lat))
            lat += 10
        lon += 10
    return out


def row_areas(transform, nrows):
    """Area in km2 of one pixel in each row of a window (pixels shrink east-west away from the equator)."""
    dx, dy = abs(transform.a), abs(transform.e)
    lat = transform.f + (np.arange(nrows) + 0.5) * transform.e
    return (R * math.radians(dy)) * (R * math.radians(dx) * np.cos(np.radians(lat))) / 1e6


def class_areas(arr, transform):
    """arr: 2-D array of class codes -> {class: km2} (no-data pixels are not counted)."""
    a = row_areas(transform, arr.shape[0])
    out = {}
    for c in range(0, 11):
        out[c] = float(((arr == c).sum(axis=1) * a).sum())
    out["nodata"] = float(((arr == NODATA).sum(axis=1) * a).sum())
    return out


def parish_areas(sources, geom):
    """Class areas for one parish, adding up every tile it touches. sources: open rasterio datasets."""
    from rasterio.mask import mask
    from shapely.geometry import box
    total = {}
    for src in sources:
        b = src.bounds
        if not box(*b).intersects(geom):
            continue
        try:
            arr, tf = mask(src, [geom.intersection(box(*b))], crop=True, filled=True, nodata=NODATA)
        except ValueError:                           # the parish does not overlap this tile's pixels
            continue
        a = class_areas(arr[0], tf)
        for k, v in a.items():
            total[k] = total.get(k, 0.0) + v
    return total


def summarise(a):
    gain = sum(a.get(c, 0.0) for c in GAIN)
    loss = sum(a.get(c, 0.0) for c in LOSS)
    return {"gain": gain, "loss": loss, "net": gain - loss,
            "perm": sum(a.get(c, 0.0) for c in PERMANENT_NOW), "seas": sum(a.get(c, 0.0) for c in SEASONAL_NOW),
            "nodata": a.get("nodata", 0.0)}


def category(net_pct):
    return f"w{int(np.searchsorted(CUTS, net_pct, side='right'))}"


def build(gdf, results):
    """results: {parish id: summarise(...)} -> writes the layer."""
    area_km2 = dict(zip(gdf["id"], gdf.to_crs(5070).geometry.area / 1e6))
    cats = [{"key": k, "label": lab, "note": note, "color": col} for k, lab, note, col in CATS] + [{"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"}]
    names = {c["key"]: c["label"] for c in cats}
    parishes = {}
    for _, row in gdf.iterrows():
        pid = row["id"]
        r = results.get(pid)
        if not r or area_km2[pid] <= 0:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": "No surface-water data for this parish."}
            continue
        pct = r["net"] / area_km2[pid] * 100
        cat = category(pct)
        rows = [["Water gained, 1984 to 2021", f"{r['gain']:,.1f} km²"], ["Water lost", f"{r['loss']:,.1f} km²"],
                ["Net change", f"{r['net']:+,.1f} km² ({pct:+.2f}% of the parish)"],
                ["Permanent water, 2021", f"{r['perm']:,.1f} km²"], ["Seasonal water, 2021", f"{r['seas']:,.1f} km²"]]
        parishes[pid] = {"name": row["name"], "cat": cat, "rv": round(float(pct), 3), "big": f"{pct:+.1f}%",
                         "big_note": "net change in surface water as a share of the parish area, 1984 to 2021",
                         "tip": f"{names[cat]} · net {r['net']:+,.1f} km²", "rows": rows,
                         "v": [round(r["gain"], 1), round(r["loss"], 1), round(r["perm"], 1), round(r["seas"], 1)],
                         "bc": ["#08519c", "#a63603", "#6baed6", "#b8c4bd"]}
    write_layer("water", {
        "label": "Surface water change", "title": "Surface water change, 1984 to 2021", "subtitle": "Net change in open water, as a share of each parish's area (JRC Global Surface Water)",
        "source": "JRC Global Surface Water, transitions map v1.4 (2021)", "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Most net water gained", "low": "Most net water lost", "note": "Ranked by net change as a percentage of the parish area."},
        "how": ("Each parish is coloured by how much its surface water changed between the early and late years of a 1984 to 2021 satellite record, as a share of the parish's area. "
                "Blue means more water now, brown means less. In coastal parishes, more water is mostly marsh and land lost to open water. Click a parish for the areas."),
        "limits": [
            "The map compares the early and late years of the record. It shows a long-term change, not a particular flood or this year's water level.",
            "Seasonal water depends on the weather of the years compared. A wet late period can show as a gain and a dry one as a loss.",
            "More water can mean new ponds and reservoirs, flooded fields, or land lost to the sea. Less water can mean drained or dried ponds. The map cannot tell them apart.",
            "Clouds and shadows can hide water on Landsat images; the source corrects for this but small ponds and narrow bayous are not always seen.",
            "The record ends in 2021, so recent changes are not shown.",
        ],
        "credits": [{"text": "Pekel, J.-F., Cottam, A., Gorelick, N., Belward, A.S. (2016) High-resolution mapping of global surface water and its long-term changes. Nature 540, 418-422. Data: European Commission Joint Research Centre", "url": "https://global-surface-water.appspot.com/"}, BOUNDARY_CREDIT],
        "chart": {"kind": "bars", "unit": "km²", "x": ["Gained", "Lost", "Permanent now", "Seasonal now"], "caption": "Water area in the parish (km²)", "top": "", "bottom": ""},
        "parishes": parishes,
    })


def self_test():
    import tempfile
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import box
    assert tile_url(-100, 40).endswith("transitions_100W_40Nv1_4_2021.tif")
    assert sorted(tiles_for()) == [(-100, 30), (-100, 40), (-90, 30), (-90, 40)], tiles_for()
    assert category(-2) == "w0" and category(-1.0) == "w1" and category(0) == "w2" and category(0.2) == "w3" and category(5) == "w4"
    # a small raster: 100 x 100 pixels of 0.001 degrees at 31 N
    arr = np.zeros((100, 100), "uint8")
    arr[:10, :] = 1          # permanent water: 10 rows
    arr[10:20, :50] = 2      # new permanent: 10 rows x 50
    arr[20:30, :20] = 3      # lost permanent
    arr[30:40, :10] = NODATA
    tf = from_origin(-92.0, 31.0, 0.001, 0.001)
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "t.tif")
        with rasterio.open(path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8", crs="EPSG:4326", transform=tf, nodata=NODATA) as dst:
            dst.write(arr, 1)
        with rasterio.open(path) as src:
            a = parish_areas([src], box(-92.0, 30.9, -91.9, 31.0))
            b = parish_areas([src], box(-80, 10, -79, 11))                 # elsewhere: nothing
    px = (R * math.radians(0.001)) ** 2 * math.cos(math.radians(30.95)) / 1e6        # about 0.0000107 km2
    assert abs(a[1] - 1000 * px) / (1000 * px) < 0.02, (a[1], 1000 * px)
    assert abs(a[2] - 500 * px) / (500 * px) < 0.02 and abs(a[3] - 200 * px) / (200 * px) < 0.02 and abs(a["nodata"] - 100 * px) / (100 * px) < 0.02
    assert b == {}
    s = summarise({1: 5.0, 2: 3.0, 3: 1.0, 5: 1.0, 6: 0.5, 7: 0.25, 8: 0.25, 4: 2.0})
    assert s["gain"] == 4.25 and s["loss"] == 1.75 and s["net"] == 2.5 and s["perm"] == 8.25 and s["seas"] == 3.25
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005"], "name": list("ABC")}, geometry=[box(-92 + i, 30, -91 + i, 31) for i in range(3)], crs=4326)
    area = float(g.to_crs(5070).geometry.area.iloc[0] / 1e6)
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        build(g, {"22001": {"gain": area * 0.03, "loss": 0.0, "net": area * 0.03, "perm": 5, "seas": 1, "nodata": 0},
                  "22003": {"gain": 1.0, "loss": 1.0, "net": 0.0, "perm": 5, "seas": 1, "nodata": 0}})
        d = json.loads((Path(tmp) / "water.json").read_text())["parishes"]
    common.DATA = old
    assert d["22001"]["cat"] == "w4" and d["22003"]["cat"] == "w2" and d["22005"]["cat"] == "not_rated"
    print("self-test passed: 6 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    import rasterio
    gdf = load_parishes()
    results, sources = {}, []
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_MAX_RETRY="6", GDAL_HTTP_RETRY_DELAY="4", VSI_CACHE="TRUE")
    with rasterio.Env(**env):
        for lon, lat in tiles_for():
            u = tile_url(lon, lat)
            try:
                sources.append(rasterio.open("/vsicurl/" + u))
                print("opened", u.rsplit("/", 1)[1], flush=True)
            except Exception as e:
                sys.exit(f"Could not open {u}: {type(e).__name__} {str(e)[:150]}. The existing layer is kept. Check URL in scripts/water.py.")
        for i, row in gdf.iterrows():
            try:
                a = parish_areas(sources, row.geometry)
            except Exception as e:
                print(f"  {row['name']}: {type(e).__name__} {str(e)[:100]}", flush=True)
                continue
            if a:
                results[row["id"]] = summarise(a)
            if (i + 1) % 10 == 0:
                print(f"  {i + 1} of {len(gdf)} parishes", flush=True)
    if len(results) < 0.8 * len(gdf):
        sys.exit(f"Only {len(results)} of {len(gdf)} parishes could be read; the existing layer is kept.")
    build(gdf, results)


if __name__ == "__main__":
    main()
