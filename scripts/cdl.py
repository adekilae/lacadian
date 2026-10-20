#!/usr/bin/env python3
"""
LaCADIAN site - cropland, main crops and one layer for each main crop, by parish.

Source: USDA National Agricultural Statistics Service (NASS) Cropland Data Layer (CDL). Every year NASS maps the crop
growing on each 30 m pixel of the contiguous United States from satellite images and farm-reporting data. The CropScape
web service of George Mason University adds the pixels up by county (parish) for any year.

This script asks CropScape for the acres of every CDL class in each parish for the latest year and the four years
before it, then publishes:
  * "cropland"     share of each parish's mapped area that is in crops
  * "crops"        the crop with the largest area in each parish
  * "crop_*"       one layer for each of nine main crops: share of the parish, with the 5-year change in the pop-up
It also writes data/crops-by-parish.csv (acres of every crop group in every parish, latest year).

Each year is downloaded once (cache/cdl_YEAR.json); a new CDL year is picked up on its own (NASS publishes the
previous year in January). If CropScape cannot be reached you can put the counts in data/source/cdl_YEAR.csv
(columns: fips,code,acres) and the script will use that file instead.

Run:
  python scripts/cdl.py
  python scripts/cdl.py --self-test
"""
import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BOUNDARY_CREDIT, CACHE, DATA, SOURCE, get_url, load_parishes, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
ENDPOINT = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLStat"
N_YEARS = 5                         # latest year and the four before it
MIN_CROP_ACRES = 100                # a parish with fewer acres of crops than this has no main crop
PAUSE = 0.5                         # seconds between requests
# --------------------------------------------------------------------------

# CDL classes that are crops: 1-61 (field crops, hay, fallow), 66-77 (orchards and tree crops), 204-254 (specialty and double crops).
# Grassland/pasture (176), forest, wetland, water, developed and barren are not crops. 92 (aquaculture) is mapped but is not a crop.
CROP = set(range(1, 62)) | set(range(66, 78)) | set(range(204, 255))
# the nine main crops: key -> (name, CDL classes). Double crops (for example 26 = winter wheat then soybeans) count for both crops.
GROUPS = {
    "rice": ("Rice", [3]),
    "cane": ("Sugarcane", [45]),
    "soy": ("Soybeans", [5, 26, 239, 240, 241, 254]),
    "corn": ("Corn", [1, 12, 13, 225, 226, 228, 237, 241]),
    "cotton": ("Cotton", [2, 232, 238, 239]),
    "sweetpotato": ("Sweet potatoes", [46]),
    "wheat": ("Wheat", [22, 23, 24, 26, 225, 236, 238]),
    "pasture": ("Grass, pasture and hay", [176, 36, 37]),
    "aqua": ("Aquaculture", [92]),
}
# the crops that can be the "main crop" of a parish (grass and pasture are not crops; they are left out)
LEAD = {"rice": ("Rice", [3]), "cane": ("Sugarcane", [45]), "soy": ("Soybeans", [5, 26, 239, 240, 241, 254]),
        "corn": ("Corn", [1, 12, 13, 225, 226, 228, 237, 241]), "cotton": ("Cotton", [2, 232, 238, 239]),
        "sweetpotato": ("Sweet potatoes", [46]), "wheat": ("Wheat", [22, 23, 24, 26, 225, 236, 238]),
        "hay": ("Hay", [36, 37]), "pecan": ("Pecans", [74])}
FALLOW = 61
PALETTE = {"rice": "#e6ab02", "cane": "#7570b3", "soy": "#1b9e77", "corn": "#d95f02", "cotton": "#a6a6a6", "sweetpotato": "#e7298a",
           "wheat": "#a6761d", "hay": "#66a61e", "pecan": "#1f78b4", "other": "#666666"}
GREENS = ["#eef4e6", "#cfe3bd", "#9ccb88", "#56a05f", "#1f6b43"]
CROP_BINS = [2, 10, 25, 50]          # cropland share cut points, %
NAMES = {"rice": "Rice", "cane": "Sugarcane", "soy": "Soybeans", "corn": "Corn", "cotton": "Cotton", "sweetpotato": "Sweet potatoes",
         "wheat": "Wheat", "hay": "Hay", "pecan": "Pecans", "other": "Other crops"}


# ============================================================ reading CropScape replies
def parse_stat(text):
    """Reply of GetCDLStat -> {class code: acres}. Accepts the CSV/text table, or an XML reply that points to one (returned as the string 'URL:...')."""
    m = re.search(r"<returnURL>\s*(.*?)\s*</returnURL>", text, re.S)
    if m:
        return "URL:" + m.group(1)
    rows = [r for r in csv.reader(io.StringIO(text.strip())) if r]
    if not rows:
        return {}
    head = [c.strip().lower() for c in rows[0]]
    has_head = not head[0].replace('"', "").isdigit()
    code_i, acre_i = 0, None
    if has_head:
        for i, c in enumerate(head):
            if c in ("value", "code", "class", "class_code"):
                code_i = i
            if "acre" in c:
                acre_i = i
        rows = rows[1:]
    if acre_i is None:
        acre_i = len(rows[0]) - 1 if rows else 2
    out = {}
    for r in rows:
        try:
            out[int(float(r[code_i]))] = out.get(int(float(r[code_i])), 0.0) + float(r[acre_i])
        except (ValueError, IndexError):
            continue
    return out


def fetch_parish(fips, year):
    r = get_url(f"{ENDPOINT}?year={year}&fips={fips}&format=csv", tries=3, timeout=180)
    got = parse_stat(r.text)
    if isinstance(got, str):                                  # the service answered with the address of the table
        got = parse_stat(get_url(got[4:], tries=3, timeout=180).text)
        if isinstance(got, str):
            raise RuntimeError("CropScape answered with another address, not a table")
    return got


def load_manual(year):
    f = SOURCE / f"cdl_{year}.csv"
    if not f.exists():
        return None
    out = {}
    for r in csv.DictReader(open(f, encoding="utf-8")):
        out.setdefault(str(r["fips"]).zfill(5), {})[int(float(r["code"]))] = float(r["acres"])
    return out


def get_year(gdf, year):
    """{fips: {code: acres}} for one year, from the cache, a hand-made file, or CropScape (only the parishes still missing)."""
    CACHE.mkdir(exist_ok=True)
    cf = CACHE / f"cdl_{year}.json"
    have = {k: {int(c): a for c, a in v.items()} for k, v in json.loads(cf.read_text()).items()} if cf.exists() else {}
    manual = load_manual(year)
    if manual:
        have.update(manual)
    missing = [p for p in gdf["id"] if p not in have]
    errors = 0
    for n, fips in enumerate(missing):
        try:
            have[fips] = fetch_parish(fips, year)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  {year} {fips}: {type(e).__name__} {str(e)[:100]}", flush=True)
            if errors >= 6 and not any(p in have for p in gdf["id"]):
                break                                          # the service is not answering at all
        time.sleep(PAUSE)
        if (n + 1) % 16 == 0:
            cf.write_text(json.dumps(have))
    cf.write_text(json.dumps(have))
    return {p: have[p] for p in gdf["id"] if p in have and have[p]}


# ============================================================ the numbers
def acres(stat, classes):
    return float(sum(stat.get(c, 0.0) for c in classes))


def totals(stat):
    """(mapped acres, crop acres, fallow acres, {lead crop: acres}, other crop acres) for one parish and year."""
    mapped = float(sum(stat.values()))
    crop = float(sum(a for c, a in stat.items() if c in CROP))
    lead = {k: acres(stat, cl) for k, (_, cl) in LEAD.items()}
    counted = set(c for _, cl in LEAD.values() for c in cl) | {FALLOW}
    other = float(sum(a for c, a in stat.items() if c in CROP and c not in counted))
    return mapped, crop, acres(stat, [FALLOW]), lead, other


def cuts_for(values):
    pos = np.array([v for v in values if v > 0], float)
    return list(np.percentile(pos, [20, 40, 60, 80])) if len(pos) >= 5 else []


def fmt_pct(x):
    return f"{x:.0f}%" if x >= 10 else (f"{x:.1f}%" if x >= 1 else f"{x:.2f}%")


def build(gdf, stats):
    """stats: {year: {fips: {code: acres}}}. Writes the 11 + layers."""
    years = sorted(stats)
    latest = years[-1]
    first = years[0]
    ids = list(gdf["id"])
    names = dict(zip(ids, gdf["name"]))
    cur = stats[latest]
    done = [p for p in ids if p in cur]
    print(f"CDL {latest}: {len(done)} of {len(ids)} parishes, earlier years {years[:-1]}")
    credits = [{"text": f"Crop maps: USDA National Agricultural Statistics Service, Cropland Data Layer {latest}, summarised by parish with the CropScape service (George Mason University)",
                "url": "https://nassgeodata.gmu.edu/CropScape/"}, BOUNDARY_CREDIT]
    common_limits = [
        "The Cropland Data Layer is a satellite map made once a year by USDA. Its accuracy is highest for the large crops (rice, soybeans, corn, cotton, sugarcane) and lower for small ones. NASS publishes accuracy tables for each year.",
        f"Each parish is the total of 30 m pixels inside it for {latest}. A pixel can be wrongly labelled, and double crops (for example wheat then soybeans) count for both crops.",
        "These are the crops mapped in one year. They are not a list of what a given farm grows and do not show rotations.",
        "The most recent year is the last one NASS has published, so it is usually the previous growing season.",
    ]
    # ---- per-parish totals for each year
    T = {y: {p: totals(stats[y][p]) for p in ids if p in stats[y]} for y in years}

    # ---- cropland
    share = {y: {p: (v[1] / v[0] * 100 if v[0] > 0 else None) for p, v in T[y].items()} for y in years}
    cats = []
    labels = [f"Under {CROP_BINS[0]}%"] + [f"{CROP_BINS[i]}–{CROP_BINS[i + 1]}%" for i in range(len(CROP_BINS) - 1)] + [f"{CROP_BINS[-1]}% or more"]
    for k in range(5):
        cats.append({"key": f"c{k}", "label": labels[k], "note": "of the parish in crops", "color": GREENS[k]})
    cats.append({"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"})
    parishes = {}
    for p in ids:
        if p not in T[latest]:
            parishes[p] = {"name": names[p], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": "CropScape returned nothing for this parish."}
            continue
        mapped, crop, fallow, lead, other = T[latest][p]
        s = share[latest][p]
        k = int(np.searchsorted(CROP_BINS, s, side="right"))
        top = sorted(((acres(stats[latest][p], cl), LEAD[key][0]) for key, (_, cl) in LEAD.items() for cl in [LEAD[key][1]]), reverse=True)
        top = [t for t in top if t[0] >= 1][:3]
        rows = [["Cropland", f"{crop:,.0f} acres ({fmt_pct(s)} of the parish)"], ["Mapped area of the parish", f"{mapped:,.0f} acres"],
                ["Fallow or idle cropland", f"{fallow:,.0f} acres"], ["Largest crops", ", ".join(f"{n} ({a:,.0f} ac)" for a, n in top) or "None above 1 acre"]]
        s0 = share[first].get(p)
        if first != latest and s0 is not None:
            rows.append([f"Change since {first}", f"{s - s0:+.1f} percentage points"])
        parishes[p] = {"name": names[p], "cat": f"c{k}", "rv": round(s, 2), "big": fmt_pct(s), "big_note": f"of the parish's mapped area was in crops in {latest}",
                       "tip": f"{fmt_pct(s)} cropland ({crop:,.0f} acres)", "rows": rows,
                       "v": [None if share[y].get(p) is None else round(share[y][p], 2) for y in years],
                       "bc": ["#2D6A4F" if y == latest else "#b8c4bd" for y in years]}
    write_layer("cropland", {
        "label": "Cropland", "title": "Cropland: share of each parish in crops", "subtitle": f"USDA Cropland Data Layer {latest}",
        "source": f"USDA NASS Cropland Data Layer {latest}", "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Most cropland", "low": "Least cropland", "note": "Ranked by the share of the parish in crops."},
        "how": (f"Each parish is coloured by the share of its mapped area that was in crops in {latest}, from the USDA Cropland Data Layer. Crops include field crops, "
                "hay, orchards, vegetables and fallow or idle cropland. Grassland and pasture, forest, wetland, water and built-up land are not counted as crops."),
        "limits": common_limits + ["Hay counts as a crop here; grassland and pasture do not. The map cannot always tell grazed pasture from other grass."],
        "credits": credits,
        "chart": {"kind": "bars", "unit": "%", "x": [str(y) for y in years], "caption": "Share of the parish in crops, by year (dark bar: latest)", "top": "", "bottom": ""},
        "parishes": parishes,
    })

    # ---- main crop
    ranked = {p: sorted(((T[latest][p][3][k] if k != "other" else T[latest][p][4], k) for k in list(LEAD) + ["other"]), reverse=True) for p in done}
    lead_of = {p: (ranked[p][0][1] if T[latest][p][1] >= MIN_CROP_ACRES and ranked[p][0][0] >= 1 else None) for p in done}
    counts = {}
    for v in lead_of.values():
        if v:
            counts[v] = counts.get(v, 0) + 1
    order = sorted(counts, key=lambda k: -counts[k])
    cats2 = [{"key": f"k_{k}", "label": NAMES[k], "note": f"leads in {counts[k]} parishes", "color": PALETTE[k]} for k in order]
    cats2.append({"key": "none", "label": "Little or no cropland", "note": f"under {MIN_CROP_ACRES} acres of crops", "color": "#e5e0d3"})
    cats2.append({"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"})
    chart_keys = ["soy", "rice", "cane", "corn", "cotton", "wheat", "sweetpotato"]
    ptab = {}
    for p in ids:
        if p not in T[latest]:
            ptab[p] = {"name": names[p], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": "CropScape returned nothing for this parish."}
            continue
        mapped, crop, fallow, lead, other = T[latest][p]
        if not lead_of.get(p):
            ptab[p] = {"name": names[p], "cat": "none", "big": "–", "tip": "Little or no cropland", "rv": None,
                       "big_note": f"Under {MIN_CROP_ACRES} acres of crops mapped in {latest}.", "rows": [["Cropland", f"{crop:,.0f} acres"]]}
            continue
        k = lead_of[p]
        tot_named = sum(a for a, _ in ranked[p])
        rows = [["Main crop", NAMES[k]], ["Its area", f"{ranked[p][0][0]:,.0f} acres"],
                ["Other large crops", ", ".join(f"{NAMES[kk]} ({a:,.0f} ac)" for a, kk in ranked[p][1:4] if a >= 1) or "None above 1 acre"],
                ["Cropland", f"{crop:,.0f} acres"]]
        table = {"caption": f"Crops mapped in {names[p]}, {latest}", "head": ["Crop", "Acres", "Share of crop total"],
                 "rows": [[NAMES[kk], f"{a:,.0f}", f"{a / tot_named * 100:.0f}%"] for a, kk in ranked[p] if a >= 1][:6],
                 "note": f"Source: USDA CDL {latest}. Double crops count for both crops, so the shares can add to more than 100%."}
        ptab[p] = {"name": names[p], "cat": f"k_{k}", "rv": round(ranked[p][0][0], 0), "big": NAMES[k],
                   "big_note": f"is the crop with the largest area in the parish in {latest}",
                   "tip": f"{NAMES[k]}, {ranked[p][0][0]:,.0f} acres", "rows": rows, "table": table,
                   "v": [round(T[latest][p][3].get(kk, 0.0), 0) for kk in chart_keys], "bc": [PALETTE[kk] if kk == k else "#b8c4bd" for kk in chart_keys]}
    write_layer("crops", {
        "label": "Main crops", "title": "Main crop in each parish", "subtitle": f"The crop with the largest area, USDA Cropland Data Layer {latest}",
        "source": f"USDA NASS Cropland Data Layer {latest}", "demo": False, "build": BUILD, "categories": cats2,
        "rank": {"high": "Largest main-crop area", "low": "Smallest main-crop area", "note": "Ranked by the area of each parish's main crop, in acres."},
        "how": (f"Each parish is coloured by the crop with the largest mapped area in {latest}. Click a parish for its other main crops. Grass and pasture are left out, "
                "because they are not crops. A parish with under 100 acres of crops has no main crop."),
        "limits": common_limits + ["The main crop is the one with the most acres, even if it leads by a small margin. Check the table in the pop-up."],
        "credits": credits,
        "chart": {"kind": "bars", "unit": "acres", "x": [NAMES[k] for k in chart_keys], "caption": "Acres of the main crops in the parish", "top": "", "bottom": ""},
        "parishes": ptab,
    })

    # ---- one layer per main crop
    for key, (name, classes) in GROUPS.items():
        a = {p: acres(stats[latest][p], classes) for p in done}
        sh = {p: (a[p] / T[latest][p][0] * 100 if T[latest][p][0] > 0 else 0.0) for p in done}
        cut = cuts_for(list(sh.values()))
        total_la = sum(a.values())
        rank = {p: r + 1 for r, p in enumerate(sorted(done, key=lambda p: -a[p]))}
        n_pos = sum(1 for p in done if a[p] >= 1)
        if cut:
            labs = [f"Under {fmt_pct(cut[0])}"] + [f"{fmt_pct(cut[i])}–{fmt_pct(cut[i + 1])}" for i in range(3)] + [f"{fmt_pct(cut[3])} or more"]
        else:
            labs = ["Lowest fifth", "Lower fifth", "Middle fifth", "Higher fifth", "Highest fifth"]
        cc = [{"key": f"n{k}", "label": labs[k], "note": "of the parish", "color": GREENS[k]} for k in range(5)]
        cc.append({"key": "none", "label": "None mapped", "note": "under 1 acre", "color": "#e5e0d3"})
        cc.append({"key": "not_rated", "label": "No data", "note": "", "color": "#bdbdbd"})
        pk = {}
        for p in ids:
            if p not in T[latest]:
                pk[p] = {"name": names[p], "cat": "not_rated", "big": "–", "tip": "No data", "rv": None, "rows": [], "big_note": "CropScape returned nothing for this parish."}
                continue
            if a[p] < 1:
                pk[p] = {"name": names[p], "cat": "none", "big": "None", "tip": f"No {name.lower()} mapped", "rv": 0, "rows": [],
                         "big_note": f"No {name.lower()} mapped in {latest}.",
                         "v": [round(acres(stats[y][p], classes), 0) if p in stats[y] else None for y in years], "bc": ["#2D6A4F" if y == latest else "#b8c4bd" for y in years]}
                continue
            k = int(np.searchsorted(cut, sh[p], side="right")) if cut else 4 - int((rank[p] - 1) / max(n_pos, 1) * 5)    # few parishes: fifths by rank
            past = {y: acres(stats[y][p], classes) for y in years if p in stats[y]}
            rows = [["Area mapped", f"{a[p]:,.0f} acres"], ["Share of the parish", fmt_pct(sh[p])],
                    ["Share of Louisiana's total", f"{a[p] / total_la * 100:.1f}%" if total_la else "–"], ["Rank by area", f"{rank[p]} of {n_pos} parishes with any"]]
            if first in past and past[first] >= 1:
                rows.append([f"Change since {first}", f"{(a[p] - past[first]) / past[first] * 100:+.0f}% ({a[p] - past[first]:+,.0f} acres)"])
            pk[p] = {"name": names[p], "cat": f"n{k}", "rv": round(a[p], 0), "big": f"{a[p]:,.0f} acres",
                     "big_note": f"of {name.lower()} mapped in {latest} ({fmt_pct(sh[p])} of the parish)",
                     "tip": f"{a[p]:,.0f} acres, {fmt_pct(sh[p])} of the parish", "rows": rows,
                     "v": [round(past[y], 0) if y in past else None for y in years], "bc": ["#2D6A4F" if y == latest else "#b8c4bd" for y in years]}
        lim = list(common_limits)
        if key == "pasture":
            lim.append("The map cannot tell grazed pasture from other grass, so this includes lawns, roadsides, levees and idle land. Hay is mapped separately in the CDL but is added here.")
        if key == "aqua":
            lim.append("CDL class 92 maps aquaculture ponds, but crawfish are often grown in flooded rice fields and in ponds the map labels as rice or water, so crawfish area is not captured well.")
        if key in ("wheat", "soy", "corn", "cotton"):
            lim.append("This crop includes double-crop classes, such as winter wheat followed by soybeans, so an acre can appear on two crop layers.")
        write_layer(f"crop_{key}", {
            "label": name, "title": f"{name}: area by parish", "subtitle": f"Share of each parish, USDA Cropland Data Layer {latest}",
            "source": f"USDA NASS Cropland Data Layer {latest}", "demo": False, "build": BUILD, "categories": cc,
            "rank": {"high": "Most area", "low": "Least area", "note": "Ranked by acres."},
            "how": (f"Each parish is coloured by the share of its mapped area that is {name.lower()} in {latest}. Colours rank the parishes in fifths (the cut points are in the legend). "
                    "Click a parish for the area in acres, its rank, and how the area changed over the last five years."),
            "limits": lim, "credits": credits,
            "chart": {"kind": "bars", "unit": "acres", "x": [str(y) for y in years], "caption": f"Acres of {name.lower()} by year (dark bar: latest)", "top": "", "bottom": ""},
            "parishes": pk,
        })
        print(f"  {name}: {n_pos} parishes, {total_la:,.0f} acres in Louisiana")

    import csv as _csv
    with open(DATA / "crops-by-parish.csv", "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["Parish FIPS", "Parish", "Year", "Mapped acres", "Crop acres", "Fallow acres"] + [GROUPS[k][0] + " acres" for k in GROUPS])
        for p in done:
            mapped, crop, fallow, _, _ = T[latest][p]
            w.writerow([p, names[p], latest, round(mapped), round(crop), round(fallow)] + [round(acres(stats[latest][p], GROUPS[k][1])) for k in GROUPS])
    print("Wrote data/crops-by-parish.csv")


def pick_years(gdf, today):
    """Find the latest CDL year that CropScape can give, then take it and the four years before it."""
    probe = list(gdf["id"])[0]
    latest = None
    for y in (today.year, today.year - 1, today.year - 2):
        if (SOURCE / f"cdl_{y}.csv").exists() or (CACHE / f"cdl_{y}.json").exists():
            latest = y
            break
        try:
            if fetch_parish(probe, y):
                latest = y
                break
        except Exception as e:
            print(f"  CDL {y}: {type(e).__name__} {str(e)[:90]}", flush=True)
    return latest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    gdf = load_parishes()
    today = dt.date.today()
    latest = pick_years(gdf, today)
    if latest is None:
        sys.exit("CropScape did not answer for any recent year. Try again later, or put the counts in data/source/cdl_YEAR.csv (columns: fips,code,acres).")
    stats = {}
    for y in range(latest - N_YEARS + 1, latest + 1):
        got = get_year(gdf, y)
        if len(got) >= 0.9 * len(gdf):
            stats[y] = got
        else:
            print(f"CDL {y}: only {len(got)} of {len(gdf)} parishes, year left out")
    if latest not in stats:
        sys.exit(f"CDL {latest} is incomplete; the existing crop layers are kept.")
    build(gdf, stats)


# ============================================================ test
def self_test():
    import tempfile
    # 1. a CSV table, with and without a header, and the XML that points to a table
    t = parse_stat("Value,Category,Acreage\n1,Corn,100.5\n5,Soybeans,2000\n176,Grassland/Pasture,300\n")
    assert t == {1: 100.5, 5: 2000.0, 176: 300.0}, t
    assert parse_stat('"1","Corn","10"\n"3","Rice","5"') == {1: 10.0, 3: 5.0}
    assert parse_stat("<x><returnURL>https://example.org/a.csv</returnURL></x>") == "URL:https://example.org/a.csv"
    assert parse_stat("") == {}
    # 2. crop classes
    assert 3 in CROP and 45 in CROP and 74 in CROP and 61 in CROP and 241 in CROP and 176 not in CROP and 92 not in CROP and 190 not in CROP and 63 not in CROP
    # 3. totals: pecans lead, a double crop counts for both, fallow is a crop but not a lead crop
    m, c, f, lead, other = totals({3: 100, 5: 200, 26: 50, 24: 10, 61: 40, 176: 500, 63: 1000, 74: 5, 207: 7})
    assert m == 1912 and c == 412 and f == 40 and lead["soy"] == 250 and lead["wheat"] == 60 and lead["pecan"] == 5 and other == 7, (m, c, f, lead, other)
    # 4. a full build on made-up parishes
    import geopandas as gpd
    from shapely.geometry import box
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005", "22007", "22009", "22011", "22013"], "name": list("ABCDEFG")},
                         geometry=[box(i, 0, i + 1, 1) for i in range(7)], crs=4326)
    rng = np.random.default_rng(1)
    stats = {}
    for yi, y in enumerate((2023, 2024, 2025)):
        stats[y] = {}
        for i, p in enumerate(g["id"]):
            st = {176: 1000.0, 63: 2000.0}
            if i == 0:
                st.update({3: 4000.0 + 100 * yi, 5: 1000.0})
            elif i == 1:
                st.update({5: 3000.0, 1: 500.0, 26: 100.0})
            elif i == 2:
                st.update({45: 2500.0})
            elif i == 3:
                st.update({2: 800.0, 5: 700.0})
            elif i == 4:
                st.update({61: 50.0})                    # only fallow: no main crop
            elif i == 5:
                st.update({3: 1500.0, 92: 300.0})
            if i != 6 or y == 2025:
                stats[y][p] = st
    stats[2025].pop("22013")                              # parish G has no data in the latest year
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        globals()["DATA"] = Path(tmp)
        build(g, stats)
        crops = json.loads((Path(tmp) / "crops.json").read_text())
        assert crops["parishes"]["22001"]["cat"] == "k_rice" and crops["parishes"]["22003"]["cat"] == "k_soy" and crops["parishes"]["22005"]["cat"] == "k_cane"
        assert crops["parishes"]["22007"]["cat"] == "k_cotton" and crops["parishes"]["22009"]["cat"] == "none" and crops["parishes"]["22013"]["cat"] == "not_rated"
        crop = json.loads((Path(tmp) / "cropland.json").read_text())
        assert crop["parishes"]["22001"]["cat"] == "c4" and crop["parishes"]["22009"]["cat"] == "c0" and len(crop["parishes"]["22001"]["v"]) == 3
        rice = json.loads((Path(tmp) / "crop_rice.json").read_text())
        assert rice["parishes"]["22001"]["cat"] == "n4" and rice["parishes"]["22003"]["cat"] == "none" and rice["parishes"]["22001"]["rv"] == 4200.0
        assert any("Change since 2023" == r[0] for r in rice["parishes"]["22001"]["rows"])
        for k in GROUPS:
            assert (Path(tmp) / f"crop_{k}.json").exists()
        assert (Path(tmp) / "crops-by-parish.csv").exists()
    common.DATA = old
    globals()["DATA"] = old
    print("self-test passed: 4 groups")


if __name__ == "__main__":
    main()
