# LaCADIAN site (unofficial prototype, for review)

Maps of Louisiana by parish, plus the LaCADIAN field stations. Static pages (Leaflet), no build step.

| Page | Layers |
|---|---|
| Stations | soil moisture by depth, rain and dry days, soil temperature, soil conductivity |
| Drought | rainfall against normal, soil moisture (SMAP), dry spells, US Drought Monitor |
| Agriculture | cropland, main crops, 9 single-crop maps, soil pH, organic matter, clay, sand, bulk density, drainage |
| Land and flood | vegetation, flood risk, surface water change |

Layers that have not been built show as dashed tabs. The repository ships no example data.

## How the data get here
`scripts/update.py` runs every layer that is due (see its header). The GitHub workflow runs it daily and commits `data/`.
Each script has a self-test: `python scripts/rain.py --self-test` (same for the others).

Secrets (Settings > Secrets and variables > Actions): `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` (free NASA Earthdata account;
needed for soil moisture and vegetation). Without them those two layers are skipped.

First run: Actions > Update data > Run workflow, tick all four boxes.

If a download is blocked, put the file in `data/source/` (see the header of `cdl.py`, `flood.py`).

## Local preview
Double-click `index.html`, or `python -m http.server 8000` and open http://localhost:8000.

## Status
Prototype. Ownership, name and licence are to be settled with the LaCADIAN network team. Not for farm decisions.
