# LaCADIAN Environmental Intelligence (unofficial prototype, for review)

Maps of Louisiana by parish, plus the LaCADIAN field stations. Static pages (Leaflet), no build step.

| Page | What it does |
|---|---|
| Map (home) | statewide figures, layer sidebar in six groups, parish map, parish panel, ranking, time series, compare two parishes, related layers, data download |
| Stations | soil moisture by depth, rain and dry days, soil temperature, soil conductivity at the field stations |
| Parish reports | one-page report for any parish, printable, CSV |
| Data | every layer as CSV or JSON |
| Methods, About | sources, limits, status |

Layers built so far: rainfall, soil moisture (SMAP), dry spells, Drought Monitor, cropland, main crops, 9 single-crop maps, soil pH, organic matter, clay, sand, bulk density, drainage, vegetation, flood risk, surface water change.
Planned layers (air temperature, ET0, the pCC root-zone model, drought onset and gap, crop water stress, streamflow, recharge, land-cover change, coastal) show greyed out as "Planned" and hold no data.

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
