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
Rainfall, soil moisture and vegetation also keep a monthly record (`data/<layer>_months.json`), so any past month can be shown, downloaded (CSV, JSON) and saved as a PNG from the Map page.
Planned layers (the pCC root-zone model, crop water stress, streamflow, recharge, wetland and coastal vegetation change, coastal salinity) show greyed out as "Planned" and hold no data.

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

## Past periods
Rainfall, soil moisture and vegetation keep a month-by-month record (`data/<layer>_months.json`). Crops keep one saved version per year (`<layer>@2021.json` ...) and the Drought Monitor keeps one per month for the last five years (`usdm@2025-06.json` ...). Pick a year and month on the map page or in the download card. One run of Actions builds all of them.

## Added layers
Air temperature and Evaporative demand (gridMET, `scripts/gridmet_extra.py` then `scripts/climate.py`), Surface soil moisture, Soil-water deficit and Surface–root-zone gap (from the SMAP files already read, `scripts/soilextra.py`), Drought onset and recovery (from the weekly Drought Monitor maps, in `scripts/usdm.py`) and Land-cover change (from the Cropland Data Layer years, in `scripts/cdl.py`). A gridMET download that fails while an earlier record exists no longer fails the whole run.
