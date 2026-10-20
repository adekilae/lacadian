#!/usr/bin/env python3
"""
LaCADIAN site - run every layer that is due.

  stations     every run, from a checkout of the LaCADIAN data repository (LACADIAN_SRC, default "_source")
  rainfall     every run: gridMET daily rain by parish (gridmet.py), then the rainfall layer and the dry-spell layer
  soil moisture, vegetation   every run, if a NASA Earthdata login is available
  check        after those: compares gridMET and SMAP with the stations (validate.py)
  Drought Monitor   every run
  crops        when never built, or CDL=true, or when a new CDL year may be out (February onwards, once a year)
  soil survey, flood risk, surface water   only when never built, when the script's BUILD number is higher, or when asked
               (SOILS=true, FLOOD=true, WATER=true)

One layer failing does not stop the others; the run is marked failed at the end.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
sys.path.insert(0, str(HERE))

src = os.environ.get("LACADIAN_SRC", "_source")
earthdata = bool(os.environ.get("EARTHDATA_USERNAME") or os.environ.get("EARTHDATA_TOKEN"))
today = dt.date.today()


def flag(name):
    return os.environ.get(name, "").lower() in ("true", "full", "1", "yes")


def is_old(key, script):
    """True when the published layer is missing or was built by an older version of its script."""
    f = DATA / f"{key}.json"
    if not f.exists():
        return True
    want = int(re.search(r"^BUILD = (\d+)", (HERE / script).read_text(), re.M).group(1))
    return json.loads(f.read_text()).get("build", 1) < want


def built_before_this_year(key):
    f = DATA / f"{key}.json"
    return f.exists() and json.loads(f.read_text()).get("updated", "")[:4] < str(today.year)


jobs = []
if Path(src).exists():
    jobs.append(("stations", ["stations.py", "--repo", src]))
else:
    print(f"Skipping stations: no checkout of the LaCADIAN data repository at '{src}'.")
jobs.append(("rainfall data (gridMET)", ["gridmet.py"]))
jobs.append(("rainfall layer", ["rain.py"]))
jobs.append(("dry spells", ["dryspell.py"]))
if earthdata:
    jobs += [("soil moisture (SMAP)", ["smap.py"]), ("vegetation", ["vegetation.py"])]
else:
    print("Skipping soil moisture and vegetation: no EARTHDATA_USERNAME / EARTHDATA_PASSWORD set.")
if Path(src).exists():
    jobs.append(("check against the stations", ["validate.py", "--repo", src]))
jobs.append(("US Drought Monitor", ["usdm.py"]))

if flag("CDL") or is_old("crops", "cdl.py") or is_old("cropland", "cdl.py") or (today.month >= 2 and built_before_this_year("crops")):
    jobs.append(("cropland and crops (USDA CDL)", ["cdl.py"]))
else:
    print("Skipping crops: already built this year.")
if flag("SOILS") or is_old("soilph", "soils.py") or is_old("soildrain", "soils.py"):
    jobs.append(("soil survey", ["soils.py"]))
else:
    print("Skipping soil survey: already built.")
if flag("FLOOD") or is_old("flood", "flood.py"):
    jobs.append(("flood risk", ["flood.py"]))
else:
    print("Skipping flood risk: already built.")
if flag("WATER") or is_old("water", "water.py"):
    jobs.append(("surface water change", ["water.py"]))
else:
    print("Skipping surface water change: already built.")

failed = []
for name, cmd in jobs:
    print(f"\n===== {name} =====", flush=True)
    if subprocess.run([sys.executable, str(HERE / cmd[0])] + cmd[1:]).returncode != 0:
        failed.append(name)

from common import write_manifest  # noqa: E402
write_manifest()                                   # refresh the list of tabs even if a layer failed

if failed:
    sys.exit(f"\nThese layers failed: {', '.join(failed)}. The others were updated.")
print("\nAll layers updated.")
