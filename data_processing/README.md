# Mobility and heatmap datasets

This repo contains three related paths:

1. **Seattle grid heatmap**: grid cells, observed bike counts, GTFS supply, optional LEHD.
2. **Cross-city station vectors**: Delhi trip features with train/test splits, and Delhi/Seattle station-level vectors with comparable density/connectivity activity proxies.
3. **City-generic timelapse heatmap**: train a Delhi passenger-per-train model, score a 24x7 city grid from census/station vectors and GTFS supply, then run route/station/event scenarios.

Source code lives under `src/`:

- `src/common/`: shared I/O, station, and geospatial utilities.
- `src/pipelines/delhi/`: Delhi density, trip, and train/test feature builders.
- `src/pipelines/seattle/`: Seattle station-vector and heatmap feature builders.
- `src/models/`: model training entry points.

Run commands from the `data_processing/` directory with `python -m ...`. The modules read from `curr_data/raw` and write to `curr_data/processed` by default.

See `ARCHITECTURE.md` for the current pipeline architecture and the future Delhi-trained dispersion model plan.

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

---

## 0. Cache raw data

Keep public raw downloads in one place before running feature builders:

```bash
.venv/bin/python scripts/download_raw_data.py
```

By default this populates `curr_data/raw/`, downloads/extracts Puget Sound GTFS into `gtfs/`, and reuses any non-empty cached files. The Delhi trip CSV is downloaded from the Kaggle dataset `nikhilkumar766/delhi-metro-dataset`, extracted, renamed to `curr_data/raw/delhi_metro_updated.csv`, and validated for the columns required by `src.pipelines.delhi.transform_metro`.

If Kaggle requires authentication in the container, provide credentials through environment variables:

```bash
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
.venv/bin/python scripts/download_raw_data.py
```

Useful options:

```bash
.venv/bin/python scripts/download_raw_data.py --raw-dir curr_data/raw --gtfs-dir gtfs
.venv/bin/python scripts/download_raw_data.py --kaggle-delhi-dataset nikhilkumar766/delhi-metro-dataset
.venv/bin/python scripts/download_raw_data.py --delhi-trips-url https://example.com/delhi_metro_updated.csv
.venv/bin/python scripts/download_raw_data.py --delhi-gtfs-url https://example.com/delhi_gtfs.zip
.venv/bin/python scripts/download_raw_data.py --kaggle-delhi-gtfs-dataset owner/dataset-slug
.venv/bin/python scripts/download_raw_data.py --include-lehd
.venv/bin/python scripts/download_raw_data.py --skip-gtfs
```

Delhi GTFS is optional because there is no stable public DMRC GTFS URL baked into the repo. If you provide a GTFS zip, it is extracted to `gtfs_delhi/`; otherwise the Delhi frequency step emits zero-frequency fallback features and the model still trains on passenger-per-train labels.

`scripts/download_raw_data.sh` is a thin compatibility wrapper around the Python script.

---

## 1. Seattle grid heatmap dataset

### Outputs

- `curr_data/processed/seattle_heatmap_features.csv`: rows by grid cell, hour, and day of week.
- `curr_data/processed/seattle_heatmap_grid.geojson`: grid polygons with `congestion_score` for MapLibre or `react-map-gl`.
- `curr_data/processed/seattle_heatmap_model_metrics.json`: written by `src.models.train_heatmap_model`.
- `curr_data/processed/seattle_heatmap_predictions.csv`: optional model predictions.

### Build

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset \
  --gtfs-dir gtfs \
  --raw-dir curr_data/raw \
  --out-dir curr_data/processed \
  --fremont-limit 5000
```

Uses local GTFS in `gtfs/`, Seattle Open Data Fremont Bridge counts, and Seattle transit accessibility data. Optional LEHD (larger download):

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset \
  --gtfs-dir gtfs \
  --raw-dir curr_data/raw \
  --out-dir curr_data/processed \
  --include-lehd \
  --lehd-year 2022
```

### Train (separate step)

```bash
.venv/bin/python -m src.models.train_heatmap_model \
  --features-csv curr_data/processed/seattle_heatmap_features.csv
```

### Optional manual counts

CSV with `lat`, `lon`, `datetime`, `count`:

```bash
.venv/bin/python -m src.pipelines.seattle.build_heatmap_dataset \
  --gtfs-dir gtfs \
  --raw-dir curr_data/raw \
  --out-dir curr_data/processed \
  --optional-counts-csv path/to/counts.csv
```

---

## 2. City-generic heatmap timelapse

This path trains on Delhi Metro `Passengers` as **load per train/trip**, then scores any city that can provide comparable station vectors and GTFS supply. The prediction output is 24 hours x 7 days per grid cell.

### Commands

```bash
# Optional if gtfs_delhi/ exists; writes a zero-frequency fallback if it does not.
.venv/bin/python -m src.pipelines.delhi.build_gtfs_frequency \
  --gtfs-dir gtfs_delhi \
  --station-vectors curr_data/processed/delhi_station_vectors.csv \
  --out-dir curr_data/processed

# Build Delhi training rows from trip labels, station vectors, census density, and frequency.
.venv/bin/python -m src.pipelines.delhi.build_heatmap_training_dataset \
  --trip-features curr_data/processed/delhi_trip_features.csv \
  --station-vectors curr_data/processed/delhi_station_vectors.csv \
  --frequency-csv curr_data/processed/delhi_station_gtfs_frequency.csv \
  --out-dir curr_data/processed

# Build a Seattle 24x7 candidate grid using station proximity and GTFS frequency exposure.
.venv/bin/python -m src.pipelines.common.build_heatmap_candidates \
  --station-vectors curr_data/processed/seattle_station_vectors.csv \
  --gtfs-dir gtfs \
  --out-dir curr_data/processed

# Train on Delhi and score the candidate grid.
.venv/bin/python -m src.models.train_heatmap_timelapse_model \
  --training-features curr_data/processed/delhi_heatmap_training_features.csv \
  --candidate-features curr_data/processed/city_heatmap_candidate_features.csv \
  --out-dir curr_data/processed
```

### Scenario scoring

Route/station scenarios are handled by rebuilding candidate features with optional overlays:

```bash
.venv/bin/python -m src.pipelines.common.build_heatmap_candidates \
  --station-vectors curr_data/processed/seattle_station_vectors.csv \
  --gtfs-dir gtfs \
  --added-stations-csv path/to/added_stations.csv \
  --removed-stations-csv path/to/removed_stations.csv \
  --frequency-delta-csv path/to/frequency_delta.csv \
  --output-name city_heatmap_scenario_features.csv
```

Event surplus users are additive at scoring time. The included `examples/scenarios/seattle_event_scenario.csv` shows the expected fields:

```bash
.venv/bin/python -m src.models.train_heatmap_timelapse_model \
  --event-scenarios-csv examples/scenarios/seattle_event_scenario.csv
```

Outputs:

- `curr_data/processed/delhi_station_gtfs_frequency.csv`
- `curr_data/processed/delhi_heatmap_training_features.csv`
- `curr_data/processed/city_heatmap_candidate_features.csv`
- `curr_data/processed/heatmap_timelapse_predictions.csv`
- `curr_data/processed/heatmap_timelapse_scenario_predictions.csv`
- `curr_data/processed/heatmap_timelapse_model_metrics.json`
- `curr_data/processed/heatmap_timelapse_grid.geojson`

The model reports `predicted_load_per_train`, `scheduled_trains`, `predicted_hourly_flow`, and `demand_score`. Scenario outputs add `baseline_demand_score`, `scenario_demand_score`, `event_surplus_flow`, `demand_delta`, and `percent_change`.

Because the Delhi label is not hourly, the training builder expands each labeled trip into representative context hours from the trip remarks. GTFS hourly frequency is then used to convert predicted load into hourly flow. Treat this as a transfer/demo model until calibrated with local city ridership counts.

---

## 3. Cross-city density dataset (Delhi + Seattle)

Goal: comparable **station vectors** with `residential_density_ratio` (people per km² around a station buffer, divided by that city’s average population density) and `activity_score` derived from reproducible density/connectivity inputs instead of city-specific station IDs.

### Order of operations

Run in this order so trip features pick up density columns.

| Step | Module | Purpose |
|------|--------|---------|
| 0 | `scripts/download_raw_data.py` | Cache public raw inputs under `curr_data/raw/` and validate the Delhi trip file |
| 1 | `src.pipelines.delhi.build_population_vectors` | Delhi station coordinates + ward population + ward polygons → per-station density |
| 2 | `src.pipelines.delhi.transform_metro` | Trip CSV → `delhi_station_vectors.csv` + `delhi_trip_features.csv` (merges density from step 1 and keeps passengers as the target) |
| 3 | `src.pipelines.delhi.prepare_train_test` | Split `delhi_trip_features.csv` into train/test |
| 4 | `src.pipelines.seattle.build_station_vectors` | Seattle GTFS stops in bbox + ACS + TIGER tracts/place → `seattle_station_vectors.csv` |

### Commands

```bash
# Delhi: density only (uses the cached raw files)
.venv/bin/python -m src.pipelines.delhi.build_population_vectors \
  --raw-dir curr_data/raw \
  --out-dir curr_data/processed \
  --radius-m 1000

# Delhi: full trip features (expects curr_data/processed/delhi_station_density.csv from step 1)
.venv/bin/python -m src.pipelines.delhi.transform_metro \
  --input curr_data/raw/delhi_metro_updated.csv \
  --out-dir curr_data/processed \
  --density-vectors curr_data/processed/delhi_station_density.csv

# Delhi: train / test split
.venv/bin/python -m src.pipelines.delhi.prepare_train_test \
  --features-csv curr_data/processed/delhi_trip_features.csv \
  --out-dir curr_data/processed

# Seattle: station vectors with density
.venv/bin/python -m src.pipelines.seattle.build_station_vectors \
  --gtfs-dir gtfs \
  --raw-dir curr_data/raw \
  --out-dir curr_data/processed \
  --radius-m 1000
```

### Cross-city outputs

| File | Description |
|------|-------------|
| `curr_data/processed/delhi_station_density.csv` | All coordinate-matched Delhi stations with population/density fields |
| `curr_data/processed/delhi_station_vectors.csv` | Stations appearing in trip data: proxy activity + connectivity + density where matched |
| `curr_data/processed/delhi_trip_features.csv` | One row per trip with origin/destination vector columns and `target_passengers` |
| `curr_data/processed/delhi_train_features.csv` / `delhi_test_features.csv` | Stratified split (rows with non-null targets) |
| `curr_data/processed/seattle_station_vectors.csv` | Seattle-area GTFS stops in the Seattle bbox with density and proxy `activity_score` |

Summary JSON files: `delhi_population_vector_summary.json`, `seattle_station_vector_summary.json` (where generated).

### Data sources (cross-city)

- **Raw cache script**: `scripts/download_raw_data.py`
- **Delhi trips**: Kaggle dataset `nikhilkumar766/delhi-metro-dataset`, cached as `curr_data/raw/delhi_metro_updated.csv`
- **Delhi station lat/lon**: public coordinate CSV (default URL in `src.pipelines.delhi.build_population_vectors`)
- **Delhi population**: OpenCity ward population CSV; **geometry**: DataMeet `Delhi_Wards.geojson` (ward numbers joined to population rows)
- **Seattle**: local `gtfs/`; **ACS** `B01003_001E` (tract + Seattle place); **Census TIGER** cartographic boundary tract and place shapefiles (cached in `curr_data/raw/`)

`activity_score` is computed from the same proxy recipe in both station-vector builders: 70% `residential_density_ratio` plus 30% within-city connectivity percentile, then min-max normalized. Delhi connectivity currently comes from distinct origin/destination links in the trip file; Seattle connectivity comes from GTFS departures plus stop count. Delhi `Passengers` remains only as `target_passengers` in the trip feature table.

If a Delhi trip station name has no match in the coordinate file, `lat`/`lon` and density stay empty for that station.

---

## Data layout

- `curr_data/raw/`: cached downloads (GTFS zips, Census shapefiles, ward CSV, etc.)
- `curr_data/processed/`: generated CSV/GeoJSON/JSON artifacts for the current workspace
- `gtfs/`: extracted Puget Sound GTFS text files
- `gtfs_delhi/`: optional extracted Delhi GTFS text files
