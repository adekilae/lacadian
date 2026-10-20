"""
LaCADIAN site - shared helpers.

Every parish layer script ends by calling write_layer(key, payload). The website draws whatever the payload
describes, so a new layer needs a new script but no change to the website.

Payload fields the website reads:
  label, title, subtitle, updated, source, demo
  categories : [{key, label, note, color}]       legend, in order
  counts     : {category key: number of parishes}
  how        : one paragraph, "how to read this map"
  limits     : [sentences]
  credits    : [{text, url}]
  legend_notes : [sentences shown under the legend]
  rank       : {high: text, low: text, note: text}   optional; each parish then needs "rv" (a number or null)
  chart      : {caption, top, bottom, unit, kind: "diverging"|"bars", x: [labels], cap}
  validation : "rain" | "soil"                      optional; shows that block of data/validation.json under the map
  parishes   : {parish id: {name, cat, big, big_note, tip, rows: [[label, value]], rv,
                            v: [numbers or null], c: [category keys] (diverging), bc: [colours] (bars),
                            table: {caption, head, rows, note}}}

Parish ids are the five-digit FIPS codes (22001 ... 22127), as in data/parishes.geojson.
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
SOURCE = DATA / "source"                 # small files you may put here by hand if a download is blocked
PARISHES = DATA / "parishes.geojson"
BBOX = (-94.15, 28.75, -88.7, 33.1)       # west, south, east, north (Louisiana with a small margin)
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# every layer of the site: key, tab label, page it belongs to, and (for tabs that hold several layers) the group
# group = (group key, text on the tab, label of the list under it, text in the list)
LAYERS = [
    ("rain", "Rainfall", "drought", None),
    ("soil", "Soil moisture", "drought", None),
    ("dryspell", "Dry spells", "drought", None),
    ("usdm", "Drought Monitor", "drought", None),
    ("cropland", "Cropland", "agriculture", None),
    ("crops", "Main crops", "agriculture", None),
    ("crop_rice", "Rice", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_cane", "Sugarcane", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_soy", "Soybeans", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_corn", "Corn", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_cotton", "Cotton", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_sweetpotato", "Sweet potatoes", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_wheat", "Wheat", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_pasture", "Grass, pasture and hay", "agriculture", ("crop", "Crops", "Crop")),
    ("crop_aqua", "Aquaculture", "agriculture", ("crop", "Crops", "Crop")),
    ("soilph", "Soil pH", "agriculture", ("soil", "Soil", "Soil property")),
    ("soilom", "Organic matter", "agriculture", ("soil", "Soil", "Soil property")),
    ("soilclay", "Clay", "agriculture", ("soil", "Soil", "Soil property")),
    ("soilsand", "Sand", "agriculture", ("soil", "Soil", "Soil property")),
    ("soilbd", "Bulk density", "agriculture", ("soil", "Soil", "Soil property")),
    ("soildrain", "Drainage class", "agriculture", ("soil", "Soil", "Soil property")),
    ("vegetation", "Vegetation", "land", None),
    ("flood", "Flood risk", "land", None),
    ("water", "Surface water change", "land", None),
]

BOUNDARY_CREDIT = {"text": "Parish boundaries: US Census Bureau cartographic boundary files (public domain)",
                   "url": "https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html"}

# dry-to-wet colours shared by the rainfall and soil moisture layers (colour-blind safe)
WETNESS = [
    {"key": "very_dry", "label": "Very dry", "color": "#8c510a"},
    {"key": "dry", "label": "Dry", "color": "#d8b365"},
    {"key": "normal", "label": "Near normal", "color": "#f3efe4"},
    {"key": "wet", "label": "Wet", "color": "#5ab4ac"},
    {"key": "very_wet", "label": "Very wet", "color": "#01665e"},
]


def load_parishes():
    import geopandas as gpd
    g = gpd.read_file(PARISHES)
    g["id"] = g["id"].astype(str)
    return g.reset_index(drop=True)


def ym_text(label):
    """'2026-08' -> 'Aug 2026'"""
    y, m = label.split("-")
    return f"{MON[int(m) - 1]} {y}"


def wetness_category(pctile):
    """Rank among reference years (0 = driest) -> category key."""
    if pctile <= 10:
        return "very_dry"
    if pctile <= 30:
        return "dry"
    if pctile < 70:
        return "normal"
    if pctile < 90:
        return "wet"
    return "very_wet"


def pct_rank(v, base):
    """Share (0-100) of the baseline values below v, ties counted half."""
    import numpy as np
    b = np.asarray([x for x in base if x is not None and x == x], "float64")
    if len(b) == 0:
        return None
    return float(((b < v).sum() + 0.5 * (b == v).sum()) / len(b) * 100)


def dry_runs(x, dry=1.0):
    """[(start index, length), ...] for every run of days under `dry` mm. A day with no data (NaN) ends a run."""
    runs, start = [], None
    for i, v in enumerate(x):
        if v == v and v < dry:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(x) - start))
    return runs


def get_url(url, tries=4, timeout=120, **kw):
    """requests.get with a few tries; raises the last error."""
    import time
    import requests
    last = None
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} from {url[:100]}")
        except Exception as e:                      # network hiccup
            last = e
        if attempt < tries:
            time.sleep(8 * attempt)
    raise last


def earthdata_login(tries=4):
    """Log in to NASA Earthdata from EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or EARTHDATA_TOKEN). Exits with a plain message."""
    import os
    import sys
    import time
    import earthaccess
    if not (os.environ.get("EARTHDATA_TOKEN") or (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))):
        sys.exit("No NASA Earthdata login: set the repository secrets EARTHDATA_USERNAME and EARTHDATA_PASSWORD.")
    last = None
    for attempt in range(1, tries + 1):
        try:
            auth = earthaccess.login(strategy="environment")
            if auth is not None and getattr(auth, "authenticated", True):
                return auth
            last = RuntimeError("login was refused (check the username and password)")
        except Exception as e:
            last = e
        if attempt < tries:
            time.sleep(10 * attempt)
    sys.exit(f"Could not log in to NASA Earthdata: {type(last).__name__} {str(last)[:200]}")


# ---------------------------------------------------------------------------- writing layers
def _write_pair(path_json, obj, compact=True):
    """Write data/x.json and data/x.js. The .js copy lets the pages work when index.html is opened straight from disk."""
    text = json.dumps(obj, separators=(",", ":") if compact else None, ensure_ascii=False, indent=None if compact else 1)
    path_json.write_text(text)
    rel = "data/" + path_json.name
    path_json.with_suffix(".js").write_text(f'window.__LC=window.__LC||{{}};window.__LC["{rel}"]={text};')


def write_layer(key, payload):
    """Save data/<key>.json (+ .js) and refresh data/layers.json (the list of tabs)."""
    payload = {"key": key, "updated": dt.date.today().isoformat(), **payload}
    counts = {}
    for d in payload["parishes"].values():
        counts[d["cat"]] = counts.get(d["cat"], 0) + 1
    payload["counts"] = counts
    DATA.mkdir(exist_ok=True)
    _write_pair(DATA / f"{key}.json", payload)
    write_manifest()
    print(f"Wrote data/{key}.json: {len(payload['parishes'])} parishes, {counts}")


def write_json(name, obj):
    """Save any other data file (validation, history) as .json and .js."""
    DATA.mkdir(exist_ok=True)
    _write_pair(DATA / name, obj)


def write_manifest():
    out = []
    for key, label, page, grp in LAYERS:
        f = DATA / f"{key}.json"
        item = {"key": key, "label": label, "page": page, "file": f"data/{key}.json", "built": f.exists()}
        if grp:
            item.update({"group": grp[0], "group_tab": grp[1], "group_label": grp[2]})
        if f.exists():
            try:
                item["updated"] = json.loads(f.read_text()).get("updated")
            except Exception:
                item["built"] = False
        out.append(item)
    _write_pair(DATA / "layers.json", {"layers": out}, compact=False)
