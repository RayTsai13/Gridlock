# Mobility and heatmap datasets

This repo contains two related paths:

1. **Seattle grid heatmap**: grid cells, observed bike counts, GTFS supply, optional LEHD.
2. **Cross-city station vectors**: Delhi trip features with train/test splits, and Delhi/Seattle station-level vectors with comparable density/connectivity activity proxies.

Source code lives under `src/`:

- `src/common/`: shared I/O, station, and geospatial utilities.
- `src/pipelines/delhi/`: Delhi density, trip, and train/test feature builders.
- `src/pipelines/seattle/`: Seattle station-vector and heatmap feature builders.
- `src/models/`: model training entry points.

Run commands from the `data_processing/` directory with `python -m ...`. The modules read from `data/raw` or `data/processed` by default and write explicit CSV/GeoJSON/JSON artifacts.

See `ARCHITECTURE.md` for the current pipeline architecture and the future Delhi-trained dispersion model plan.

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

---

## 1. Seattle grid heatmap dataset

### Outputs

- `data/processed/seattle_heatmap_features.csv`: rows by grid cell, hour, and day of week.
- `data/processed/seattle_heatmap_grid.geojson`: grid polygons with `congestion_score` for MapLibre or `react-map-gl`.
- `data/processed/model_metrics.json`: written by `src.models.train_heatmap_model`.
- `data/processed/seattle_heatmap_predictions.csv`: optional model predictions.

### Build

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset --gtfs-dir gtfs --fremont-limit 5000
```

Uses local GTFS in `gtfs/`, Seattle Open Data Fremont Bridge counts, and Seattle transit accessibility data. Optional LEHD (larger download):

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset --gtfs-dir gtfs --include-lehd --lehd-year 2022
```

### Train (separate step)

```bash
.venv/bin/python -m src.models.train_heatmap_model --features-csv data/processed/seattle_heatmap_features.csv
```

### Optional manual counts

CSV with `lat`, `lon`, `datetime`, `count`:

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset --optional-counts-csv path/to/counts.csv
```

---

## 2. Cross-city density dataset (Delhi + Seattle)

Goal: comparable **station vectors** with `residential_density_ratio` (people per km² around a station buffer, divided by that city’s average population density) and `activity_score` derived from reproducible density/connectivity inputs instead of city-specific station IDs.

### Order of operations

Run in this order so trip features pick up density columns.

| Step | Module | Purpose |
|------|--------|---------|
| 1 | `src.pipelines.delhi.build_population_vectors` | Delhi station coordinates + ward population + ward polygons → per-station density |
| 2 | `src.pipelines.delhi.transform_metro` | Trip CSV → `delhi_station_vectors.csv` + `delhi_trip_features.csv` (merges density from step 1 and keeps passengers as the target) |
| 3 | `src.pipelines.delhi.prepare_train_test` | Split `delhi_trip_features.csv` into train/test |
| 4 | `src.pipelines.seattle.build_station_vectors` | Seattle GTFS stops in bbox + ACS + TIGER tracts/place → `seattle_station_vectors.csv` |

### Commands

```bash
# Delhi: density only (caches downloads under data/raw/)
.venv/bin/python -m src.pipelines.delhi.build_population_vectors --radius-m 1000

# Delhi: full trip features (expects data/processed/delhi_station_density.csv from step 1)
.venv/bin/python -m src.pipelines.delhi.transform_metro \
  --input data/raw/delhi_metro_updated.csv \
  --out-dir data/processed \
  --density-vectors data/processed/delhi_station_density.csv

# Delhi: train / test split
.venv/bin/python -m src.pipelines.delhi.prepare_train_test \
  --features-csv data/processed/delhi_trip_features.csv \
  --out-dir data/processed

# Seattle: station vectors with density
.venv/bin/python -m src.pipelines.seattle.build_station_vectors --gtfs-dir gtfs --radius-m 1000
```

### Cross-city outputs

| File | Description |
|------|-------------|
| `data/processed/delhi_station_density.csv` | All coordinate-matched Delhi stations with population/density fields |
| `data/processed/delhi_station_vectors.csv` | Stations appearing in trip data: proxy activity + connectivity + density where matched |
| `data/processed/delhi_trip_features.csv` | One row per trip with origin/destination vector columns and `target_passengers` |
| `data/processed/delhi_train_features.csv` / `delhi_test_features.csv` | Stratified split (rows with non-null targets) |
| `data/processed/seattle_station_vectors.csv` | Seattle-area GTFS stops in the Seattle bbox with density and proxy `activity_score` |

Summary JSON files: `delhi_population_vector_summary.json`, `seattle_station_vector_summary.json` (where generated).

### Data sources (cross-city)

- **Delhi trips** (place in `data/raw/`): `data/raw/delhi_metro_updated.csv`
- **Delhi station lat/lon**: public coordinate CSV (default URL in `src.pipelines.delhi.build_population_vectors`)
- **Delhi population**: OpenCity ward population CSV; **geometry**: DataMeet `Delhi_Wards.geojson` (ward numbers joined to population rows)
- **Seattle**: local `gtfs/`; **ACS** `B01003_001E` (tract + Seattle place); **Census TIGER** cartographic boundary tract and place shapefiles (cached in `data/raw/`)

`activity_score` is computed from the same proxy recipe in both station-vector builders: 70% `residential_density_ratio` plus 30% within-city connectivity percentile, then min-max normalized. Delhi connectivity currently comes from distinct origin/destination links in the trip file; Seattle connectivity comes from GTFS departures plus stop count. Delhi `Passengers` remains only as `target_passengers` in the trip feature table.

If a Delhi trip station name has no match in the coordinate file, `lat`/`lon` and density stay empty for that station.

---

## Data layout

- `data/raw/`: cached downloads (GTFS zips, Census shapefiles, ward CSV, etc.)
- `data/processed/`: all generated CSV/GeoJSON/JSON for modeling and maps
