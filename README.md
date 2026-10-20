# LaCADIAN prototype (for review)

A static web page (Leaflet map, station table, per-station charts) built from the public
LaCADIAN station data (https://github.com/soil-hydrology/LaCADIAN).

- `scripts/stations.py` reads the daily station files and writes `data/stations.json`.
- `index.html`, `css/`, `js/` draw it. No build step. Leaflet is in `vendor/`.
- `.github/workflows/update.yml` refreshes the data daily.

Status: prototype. Keep this repository private. Ownership, licence and the name
are to be settled with the LaCADIAN network team before anything is published.
Not for farm decisions.

Local preview: `python3 -m http.server` then open http://localhost:8000
