#!/usr/bin/env python3
"""
LaCADIAN site - flood risk by parish (FEMA National Risk Index).

Source: FEMA's National Risk Index (NRI), county-level table. For every county or parish in the United States it rates the
risk from 18 natural hazards. A rating compares one county with all other counties: it combines how often a hazard
strikes, what is exposed to it (buildings, people, farm value) and how vulnerable those are, and gives a score from 0 to
100 for each hazard and a five-step rating from "Very Low" to "Very High". This layer shows:
  riverine flooding (IFLD), coastal flooding (CFLD) and, in the pop-up, hurricane risk (HRCN).
The parish is coloured by the higher of its riverine and coastal flooding ratings.

This measures risk compared with other US counties, not the share of land that floods and not a forecast. It is built once
and rebuilt only when asked (FLOOD=true) or when this script's BUILD number goes up.

If the download is blocked, put the county table (the CSV, or the zip FEMA publishes) in data/source/ as
NRI_Table_Counties.csv (or NRI_Table_Counties.zip).

Run:
  python scripts/flood.py
  python scripts/flood.py --self-test
"""
import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BOUNDARY_CREDIT, SOURCE, get_url, load_parishes, write_layer  # noqa: E402

BUILD = 1

# ---- settings you may want to change -------------------------------------
URLS = ["https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload//NRI_Table_Counties/NRI_Table_Counties.zip",
        "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRI_Table_Counties/NRI_Table_Counties.zip"]
# --------------------------------------------------------------------------

RATINGS = ["very low", "relatively low", "relatively moderate", "relatively high", "very high"]
COLORS = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"]
LABELS = ["Very low", "Relatively low", "Relatively moderate", "Relatively high", "Very high"]


def rating_index(text):
    """'Relatively High' -> 3; anything that is not one of the five ratings ('Not Applicable', 'Insufficient Data', '') -> None."""
    t = (text or "").strip().lower()
    return RATINGS.index(t) if t in RATINGS else None


def num(x):
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def read_table(blob, name=""):
    """Bytes of the NRI county table (a zip holding the CSV, or the CSV) -> {5-digit FIPS: row} for Louisiana."""
    if blob[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(blob))
        member = next(n for n in z.namelist() if n.lower().endswith(".csv") and "data dictionary" not in n.lower() and "dictionary" not in n.lower())
        text = z.read(member).decode("utf-8-sig", errors="replace")
    else:
        text = blob.decode("utf-8-sig", errors="replace")
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        fips = (r.get("STCOFIPS") or (str(r.get("STATEFIPS", "")).zfill(2) + str(r.get("COUNTYFIPS", "")).zfill(3))).strip().zfill(5)
        if fips.startswith("22"):
            out[fips] = r
    return out


def download():
    for f in ("NRI_Table_Counties.csv", "NRI_Table_Counties.zip"):
        p = SOURCE / f
        if p.exists():
            print(f"Using data/source/{f}")
            return p.read_bytes()
    errors = []
    for u in URLS:
        try:
            return get_url(u, tries=3, timeout=300).content
        except Exception as e:
            errors.append(f"{type(e).__name__} {str(e)[:100]}")
    sys.exit("The FEMA National Risk Index file could not be downloaded (" + " | ".join(errors) +
             "). Download the county table from hazards.fema.gov/nri/data-resources and put it in data/source/NRI_Table_Counties.zip.")


def money(v):
    if v is None:
        return "n/a"
    return f"${v / 1e6:,.1f} million" if v >= 1e6 else f"${v:,.0f}"


def build(gdf, table):
    cats = [{"key": f"r{k}", "label": LABELS[k], "note": "flood risk compared with other US counties", "color": COLORS[k]} for k in range(5)]
    cats.append({"key": "not_rated", "label": "Not rated", "note": "no rating in the table", "color": "#bdbdbd"})
    names = {c["key"]: c["label"] for c in cats}
    parishes = {}
    for _, row in gdf.iterrows():
        pid = row["id"]
        r = table.get(pid)
        if not r:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "Not rated", "rv": None, "rows": [], "big_note": "The National Risk Index has no row for this parish."}
            continue
        ri, ci, hi = rating_index(r.get("IFLD_RISKR")), rating_index(r.get("CFLD_RISKR")), rating_index(r.get("HRCN_RISKR"))
        top = max([x for x in (ri, ci) if x is not None], default=None)
        rs, cs, hs = num(r.get("IFLD_RISKS")), num(r.get("CFLD_RISKS")), num(r.get("HRCN_RISKS"))
        if top is None:
            parishes[pid] = {"name": row["name"], "cat": "not_rated", "big": "–", "tip": "Not rated", "rv": None, "rows": [], "big_note": "No flooding rating in the table."}
            continue
        eal = sum(v for v in (num(r.get("IFLD_EALT")), num(r.get("CFLD_EALT"))) if v is not None)
        label = lambda i: LABELS[i] if i is not None else "Not rated"
        rows = [["Riverine flooding", f"{label(ri)}" + (f" (score {rs:.0f} of 100)" if rs is not None else "")],
                ["Coastal flooding", f"{label(ci)}" + (f" (score {cs:.0f} of 100)" if cs is not None else "")],
                ["Hurricane", f"{label(hi)}" + (f" (score {hs:.0f} of 100)" if hs is not None else "")],
                ["Expected yearly flood loss (buildings, crops, people)", money(eal)]]
        agri = num(r.get("AGRIVALUE"))
        if agri:
            rows.append(["Value of crops and livestock in the parish", money(agri)])
        parishes[pid] = {"name": row["name"], "cat": f"r{top}", "big": label(top), "rv": (max(x for x in (rs, cs) if x is not None) if (rs is not None or cs is not None) else None),
                         "big_note": "flood risk (the higher of riverine and coastal flooding) compared with all other US counties, FEMA National Risk Index",
                         "tip": f"{names[f'r{top}']} flood risk", "rows": rows,
                         "v": [rs, cs, hs], "bc": ["#3182bd", "#08519c", "#b8c4bd"]}
    write_layer("flood", {
        "label": "Flood risk", "title": "Flood risk of each parish (FEMA National Risk Index)", "subtitle": "Higher of riverine and coastal flooding, compared with all US counties",
        "source": "FEMA National Risk Index, county table", "demo": False, "build": BUILD, "categories": cats,
        "rank": {"high": "Highest flood risk score", "low": "Lowest flood risk score", "note": "Ranked by the higher of the riverine and coastal flooding scores (0 to 100)."},
        "how": ("Each parish is coloured by its flood risk rating from FEMA's National Risk Index: the higher of its riverine flooding and its coastal flooding rating. "
                "The rating compares the parish with every county in the United States and combines how often flooding happens, what is exposed to it and how vulnerable that is. "
                "Click a parish for both ratings, hurricane risk and the expected yearly loss."),
        "limits": [
            "This is a risk rating relative to other US counties. It does not show how much of the parish floods and it is not a forecast.",
            "The rating mixes the chance of flooding with what is exposed (buildings, people, farm value). A thinly populated parish can have flood-prone land and a low rating.",
            "It is a county-level figure. Flood risk varies a lot inside a parish; FEMA flood maps and local drainage districts are the guide for a particular field or house.",
            "The Risk Index is updated every year or two, so it does not show last month's floods.",
        ],
        "credits": [{"text": "FEMA National Risk Index", "url": "https://hazards.fema.gov/nri/"}, BOUNDARY_CREDIT],
        "chart": {"kind": "bars", "unit": "score", "x": ["Riverine flood", "Coastal flood", "Hurricane"], "caption": "National Risk Index scores (0 to 100) for the parish", "top": "", "bottom": ""},
        "parishes": parishes,
    })


def self_test():
    import tempfile
    import geopandas as gpd
    from shapely.geometry import box
    assert rating_index("Relatively High") == 3 and rating_index("Very Low") == 0 and rating_index("Not Applicable") is None and rating_index("") is None and rating_index(None) is None
    assert num("1,234") == 1234.0 and num("") is None and num("$5") == 5.0 and money(2500000) == "$2.5 million" and money(None) == "n/a"
    csvtext = ("STCOFIPS,COUNTY,STATE,IFLD_RISKR,IFLD_RISKS,IFLD_EALT,CFLD_RISKR,CFLD_RISKS,CFLD_EALT,HRCN_RISKR,HRCN_RISKS,AGRIVALUE\n"
               "22001,Acadia,Louisiana,Relatively High,88.0,1000000,Not Applicable,,,Very High,99.5,500000000\n"
               "22003,Allen,Louisiana,Very Low,5,10,Relatively Low,20,5,Relatively Moderate,50,100\n"
               "22005,Ascension,Louisiana,Insufficient Data,,,No Rating,,,Very High,90,\n"
               "01001,Autauga,Alabama,Very High,99,1,Very High,99,1,Very High,99,1\n")
    t = read_table(csvtext.encode())
    assert sorted(t) == ["22001", "22003", "22005"]
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("NRI_DataDictionary.csv", "a,b\n1,2\n")
        f.writestr("NRI_Table_Counties.csv", csvtext)
    assert sorted(read_table(z.getvalue())) == ["22001", "22003", "22005"]
    g = gpd.GeoDataFrame({"id": ["22001", "22003", "22005", "22007"], "name": list("ABCD")}, geometry=[box(i, 0, i + 1, 1) for i in range(4)], crs=4326)
    old = common.DATA
    with tempfile.TemporaryDirectory() as tmp:
        common.DATA = Path(tmp)
        build(g, t)
        d = json.loads((Path(tmp) / "flood.json").read_text())["parishes"]
    common.DATA = old
    assert d["22001"]["cat"] == "r3" and d["22003"]["cat"] == "r1" and d["22005"]["cat"] == "not_rated" and d["22007"]["cat"] == "not_rated"
    assert d["22001"]["rv"] == 88.0 and d["22001"]["rows"][3][1] == "$1.0 million"
    print("self-test passed: 4 groups")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    table = read_table(download())
    print(f"{len(table)} Louisiana parishes in the table")
    if len(table) < 50:
        sys.exit("The table has fewer than 50 Louisiana parishes; it is probably not the county table.")
    build(load_parishes(), table)


if __name__ == "__main__":
    main()
