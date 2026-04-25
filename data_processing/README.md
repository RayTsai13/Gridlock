# Mobility and heatmap datasets

This repo contains two related paths:

1. **Seattle grid heatmap**: grid cells, observed bike counts, GTFS supply, optional LEHD.
2. **Cross-city station vectors**: Delhi trip features with train/test splits, and Seattle station-level vectors with Census-based residential density.

Shared code lives under `src/` (`io_utils`, `station_utils`, `geo_utils`). Scripts are small CLIs that read from `data/raw` or `data/processed` and write explicit CSV artifacts.

Seattle-specific scripts and generated Seattle artifacts now live under [`seattle/`](../seattle/README.md). The current frontend Seattle map architecture is documented in [`docs/seattle-map-architecture.md`](../docs/seattle-map-architecture.md).

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

---

## 1. Seattle grid heatmap dataset

### Outputs

- `seattle/data/processed/seattle_heatmap_features.csv`: rows by grid cell, hour, and day of week.
- `seattle/data/processed/seattle_heatmap_grid.geojson`: grid polygons with `congestion_score` for MapLibre or `react-map-gl`.
- `seattle/data/processed/model_metrics.json`: written by `train_heatmap_model.py`.
- `seattle/data/processed/seattle_heatmap_predictions.csv`: optional model predictions.

### Build

```bash
.venv/bin/python seattle/scripts/build_heatmap_dataset.py --gtfs-dir gtfs --fremont-limit 5000
```

Uses local GTFS in `gtfs/`, Seattle Open Data Fremont Bridge counts, and Seattle transit accessibility data. Optional LEHD (larger download):

```bash
.venv/bin/python seattle/scripts/build_heatmap_dataset.py --gtfs-dir gtfs --include-lehd --lehd-year 2022
```

### Train (separate step)

```bash
.venv/bin/python seattle/scripts/train_heatmap_model.py
```

### Optional manual counts

CSV with `lat`, `lon`, `datetime`, `count`:

```bash
.venv/bin/python seattle/scripts/build_heatmap_dataset.py --optional-counts-csv path/to/counts.csv
```

---

## 2. Cross-city density dataset (Delhi + Seattle)

Goal: comparable **station vectors** with `residential_density_ratio` (people per km² around a station buffer, divided by that city’s average population density).

### Order of operations

Run in this order so trip features pick up density columns.

| Step | Script | Purpose |
|------|--------|---------|
| 1 | `build_delhi_population_vectors.py` | Delhi station coordinates + ward population + ward polygons → per-station density |
| 2 | `transform_delhi_metro.py` | Trip CSV → `delhi_station_vectors.csv` + `delhi_trip_features.csv` (merges density from step 1) |
| 3 | `prepare_delhi_train_test.py` | Split `delhi_trip_features.csv` into train/test |
| 4 | `seattle/scripts/build_seattle_station_vectors.py` | Seattle GTFS stops in bbox + ACS + TIGER tracts/place → `seattle_station_vectors.csv` |

### Commands

```bash
# Delhi: density only (caches downloads under data/raw/)
.venv/bin/python build_delhi_population_vectors.py --radius-m 1000

# Delhi: full trip features (expects data/processed/delhi_station_density.csv from step 1)
.venv/bin/python transform_delhi_metro.py \
  --input data/raw/delhi_metro_updated.csv \
  --out-dir data/processed \
  --density-vectors data/processed/delhi_station_density.csv

# Delhi: train / test split
.venv/bin/python prepare_delhi_train_test.py \
  --features-csv data/processed/delhi_trip_features.csv \
  --out-dir data/processed

# Seattle: station vectors with density
.venv/bin/python seattle/scripts/build_seattle_station_vectors.py --gtfs-dir gtfs --radius-m 1000
```

### Cross-city outputs

| File | Description |
|------|-------------|
| `data/processed/delhi_station_density.csv` | All coordinate-matched Delhi stations with population/density fields |
| `data/processed/delhi_station_vectors.csv` | Stations appearing in trip data: activity + connectivity + density where matched |
| `data/processed/delhi_trip_features.csv` | One row per trip with origin/destination vector columns and `target_passengers` |
| `data/processed/delhi_train_features.csv` / `delhi_test_features.csv` | Stratified split (rows with non-null targets) |
| `seattle/data/processed/seattle_station_vectors.csv` | Seattle-area GTFS stops in the Seattle bbox with density and combined `activity_score` |

Summary JSON files: `delhi_population_vector_summary.json`, `seattle_station_vector_summary.json` (where generated).

### Data sources (cross-city)

- **Delhi trips** (place in `data/raw/`): `data/raw/delhi_metro_updated.csv`
- **Delhi station lat/lon**: public coordinate CSV (default URL in `build_delhi_population_vectors.py`)
- **Delhi population**: OpenCity ward population CSV; **geometry**: DataMeet `Delhi_Wards.geojson` (ward numbers joined to population rows)
- **Seattle**: local `gtfs/`; **ACS** `B01003_001E` (tract + Seattle place); **Census TIGER** cartographic boundary tract and place shapefiles (cached in `data/raw/`)

If a Delhi trip station name has no match in the coordinate file, `lat`/`lon` and density stay empty for that station.

---

## Data layout

- `data/raw/`: cached downloads (GTFS zips, Census shapefiles, ward CSV, etc.)
- `data/processed/`: all generated CSV/GeoJSON/JSON for modeling and maps
