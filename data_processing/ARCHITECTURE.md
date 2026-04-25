# Data Pipeline Architecture and Dispersion Model Plan

This document describes the current data-processing architecture for training a city-generic heatmap timelapse model from Delhi Metro passenger-per-train data, then applying that learned behavior to station vectors and GTFS supply from other cities such as Seattle.

The repository now contains both the reusable station-vector foundation and a Delhi-trained grid timelapse path. The older Seattle-only heatmap baseline remains available as a local proxy model.

## Goals

- Build station-level vectors that describe transit stations without using city-specific identifiers as model features.
- Train on Delhi Metro trips, where passenger targets are available.
- Reuse the learned relationship between station context and passenger movement in another city.
- Use Seattle vectors and heatmap outputs for a demo of cross-city transfer.

## Repository Layout

The data-processing package is organized as importable modules under `src/`, with shared utilities separated from city-specific pipelines and model training entry points:

```text
data_processing/
  src/
    common/
      io_utils.py          # cached downloads, directory creation, CSV writes
      station_utils.py     # station cleaning, station ids, GTFS stop aggregation, scores
      geo_utils.py         # station buffers and population-density vectors
      gtfs_utils.py        # GTFS extraction and station-hour frequency helpers
      heatmap_utils.py     # grid, distance exposure, and scenario helpers
    pipelines/
      common/
        build_heatmap_candidates.py
      delhi/
        build_population_vectors.py
        build_gtfs_frequency.py
        build_heatmap_training_dataset.py
        transform_metro.py
        prepare_train_test.py
      seattle/
        build_station_vectors.py
        build_heatmap_dataset.py
    models/
      train_heatmap_model.py
      train_heatmap_timelapse_model.py
  scripts/
    download_raw_data.py
    download_raw_data.sh
  curr_data/
    raw/
    processed/
```

Pipeline defaults point at `curr_data/raw` and `curr_data/processed`. Use `scripts/download_raw_data.py` to populate the raw cache before running pipeline modules. `scripts/download_raw_data.sh` is only a thin compatibility wrapper. Delhi GTFS is optional and can be supplied via `--delhi-gtfs-url` or `--kaggle-delhi-gtfs-dataset`; if omitted, the Delhi frequency builder emits zero-frequency fallback rows.

## Current Architecture

There are two related but separate data paths.

### 1. Cross-City Station Vector Pipeline

This is the path that supports a future dispersion model.

```text
Delhi station coordinates
Delhi ward geometry + population
scripts/download_raw_data.py
        |
        v
src.pipelines.delhi.build_population_vectors
        |
        v
delhi_station_density.csv
        |
        v
Delhi Metro trips -> src.pipelines.delhi.transform_metro
        |
        +--> delhi_station_vectors.csv
        +--> delhi_trip_features.csv
                    |
                    v
            src.pipelines.delhi.prepare_train_test
                    |
                    +--> delhi_train_features.csv
                    +--> delhi_test_features.csv

Seattle GTFS + ACS/TIGER population data
scripts/download_raw_data.py
        |
        v
src.pipelines.seattle.build_station_vectors
        |
        v
seattle_station_vectors.csv
```

#### Delhi Population Vectors

`src.pipelines.delhi.build_population_vectors` builds residential-density features for Delhi stations.

Inputs:

- Delhi Metro station coordinate CSV.
- Delhi ward GeoJSON.
- Delhi ward population CSV.

These public files are cached by `scripts/download_raw_data.py`.

Process:

- Clean station names and create stable `station_id` slugs.
- Attach population to ward polygons.
- Build a circular buffer around each station, currently 1000 meters by default.
- Area-weight ward population into each station buffer.
- Normalize each station's local population density against the city-wide average.

Output:

- `curr_data/processed/delhi_station_density.csv`
- `curr_data/processed/delhi_population_vector_summary.json`

Current summary:

- 221 Delhi stations.
- 290 ward geometries.
- 1000 meter station radius.

#### Delhi Trip and Station Vectors

`src.pipelines.delhi.transform_metro` converts raw Delhi Metro trips into model-ready features.

Inputs:

- `curr_data/raw/delhi_metro_updated.csv`
- `curr_data/processed/delhi_station_density.csv`

The raw trip CSV is downloaded by `scripts/download_raw_data.py` from the Kaggle dataset `nikhilkumar766/delhi-metro-dataset`, extracted from the archive, cached as `curr_data/raw/delhi_metro_updated.csv`, and validated for the required trip columns. If Kaggle requires authentication in a container, set `KAGGLE_USERNAME` and `KAGGLE_KEY`, or pass `--delhi-trips-url` with a direct CSV URL.

Required raw trip fields:

- `TripID`
- `Date`
- `From_Station`
- `To_Station`
- `Distance_km`
- `Fare`
- `Cost_per_passenger`
- `Passengers`
- `Ticket_Type`
- `Remarks`

Process:

- Clean station names and derive origin/destination `station_id` values.
- Extract calendar features: day of week, month, year, and weekend flag.
- Encode operating-context flags from remarks: peak, off-peak, festival, and maintenance.
- Merge residential-density fields from the Delhi population-vector output.
- Build station-level connectivity from distinct inbound and outbound station links.
- Estimate station-level `activity_raw` as a proxy blend:
  - 70 percent residential density ratio.
  - 30 percent station connectivity rank.
- Convert raw activity/connectivity to normalized scores and rank percentiles.
- Join station vectors back onto each trip as origin and destination features.
- One-hot encode ticket type and remark categories.

Outputs:

- `curr_data/processed/delhi_station_vectors.csv`
- `curr_data/processed/delhi_trip_features.csv`

The trip feature file is the main supervised-learning input. Its label is `target_passengers`.

#### Delhi Train/Test Split

`src.pipelines.delhi.prepare_train_test` splits rows with a non-null passenger target.

Process:

- Read `delhi_trip_features.csv`.
- Keep rows where `target_passengers` exists.
- Split train/test with a deterministic random seed.
- Stratify by `is_weekend` when available.

Outputs:

- `curr_data/processed/delhi_train_features.csv`
- `curr_data/processed/delhi_test_features.csv`
- `curr_data/processed/delhi_train_test_summary.json`

Current summary:

- 150,000 input trip rows.
- 148,500 usable rows with targets.
- 118,800 train rows.
- 29,700 test rows.

#### Seattle Station Vectors

`src.pipelines.seattle.build_station_vectors` builds a Seattle station table using the same output schema as Delhi station vectors.

Inputs:

- Local GTFS files.
- King County ACS tract population.
- Seattle ACS place population.
- Census TIGER tract and place boundaries.

`scripts/download_raw_data.py` caches the public Seattle files and extracts GTFS into the configured GTFS directory.

Process:

- Aggregate duplicate GTFS stops into station-level records.
- Keep stations inside the Seattle bounding box.
- Estimate station connectivity from GTFS departures and stop counts.
- Compute residential-density fields around each station using the same buffer method.
- Estimate Seattle `activity_raw` as a proxy blend:
  - 70 percent residential density ratio.
  - 30 percent GTFS connectivity rank.
- Convert raw activity/connectivity to normalized scores and rank percentiles.

Output:

- `curr_data/processed/seattle_station_vectors.csv`
- `curr_data/processed/seattle_station_vector_summary.json`

Current summary:

- 2,088 Seattle stations/stops.
- 1000 meter station radius.
- Seattle ACS population baseline: 734,603.

### 2. Seattle Heatmap Pipeline

The heatmap path is useful for a Seattle demo, but it is separate from the Delhi OD/trip modeling path.

```text
Seattle bbox + grid
GTFS supply
Fremont Bridge counts
Transit accessibility
Optional manual counts
Optional LEHD jobs
        |
        v
src.pipelines.seattle.build_heatmap_dataset
        |
        +--> seattle_heatmap_features.csv
        +--> seattle_heatmap_grid.geojson
                    |
                    v
            src.models.train_heatmap_model
                    |
                    +--> seattle_heatmap_model_metrics.json
                    +--> seattle_heatmap_predictions.csv
```

`src.pipelines.seattle.build_heatmap_dataset` creates a grid over Seattle, then expands each cell across hour and day-of-week combinations. It adds GTFS transit frequency, Fremont Bridge observed counts, optional local counts, accessibility score, and optional LEHD jobs.

The output includes:

- `curr_data/processed/seattle_heatmap_features.csv`
- `curr_data/processed/seattle_heatmap_grid.geojson`

`src.models.train_heatmap_model` trains a baseline `HistGradientBoostingRegressor` on rows where `target_count > 0`. This is a proxy congestion model, not the future Delhi-trained station dispersion model.

Current baseline metrics:

- 168 observed target rows.
- MAE: 24.92.
- RMSE: 35.56.

### 3. City-Generic Heatmap Timelapse Pipeline

This is the current Delhi-trained transfer path for a 24x7 heatmap.

```text
Delhi trip features
Delhi station vectors
Optional Delhi GTFS
        |
        v
src.pipelines.delhi.build_gtfs_frequency
src.pipelines.delhi.build_heatmap_training_dataset
        |
        +--> delhi_station_gtfs_frequency.csv
        +--> delhi_heatmap_training_features.csv
                    |
                    v
            src.models.train_heatmap_timelapse_model
                    ^
                    |
City station vectors + GTFS
        |
        v
src.pipelines.common.build_heatmap_candidates
        |
        +--> city_heatmap_candidate_features.csv
```

The Delhi label is interpreted as `load_per_train`, not station activity. Training rows are station/cell examples with:

- Calendar and context flags.
- Census-derived residential-density proxy fields from station vectors.
- Transit proximity exposure and station connectivity exposure.
- Station-hour scheduled train frequency when Delhi GTFS is available.

Because the Delhi trip data is not hourly, the training builder maps trip context into representative hours: peak trips are expanded to peak hours, off-peak trips to off-peak hours, weekend trips to weekend activity hours, and normal trips to morning/midday/evening anchors. At scoring time, GTFS scheduled frequency converts `predicted_load_per_train` into `predicted_hourly_flow`.

Scenario behavior is split into two stages:

- Route/station/frequency changes rebuild `city_heatmap_candidate_features.csv` with `--added-stations-csv`, `--removed-stations-csv`, or `--frequency-delta-csv`.
- Event surplus users are added during model scoring from a CSV with event location, day, hour window, surplus users, radius, and decay.

Primary outputs:

- `curr_data/processed/delhi_station_gtfs_frequency.csv`
- `curr_data/processed/delhi_heatmap_training_features.csv`
- `curr_data/processed/city_heatmap_candidate_features.csv`
- `curr_data/processed/heatmap_timelapse_predictions.csv`
- `curr_data/processed/heatmap_timelapse_scenario_predictions.csv`
- `curr_data/processed/heatmap_timelapse_model_metrics.json`
- `curr_data/processed/heatmap_timelapse_grid.geojson`

## Shared Station Vector Schema

Delhi and Seattle station-vector CSVs intentionally share these columns:

```text
station_id
station_name
lat
lon
activity_score
connectivity_score
activity_rank_pct
is_transfer_proxy
connectivity
population_within_radius
population_density_within_radius
city_average_population_density
residential_density_ratio
```

These fields are the bridge between cities.

- `activity_score` is a normalized station activity measure.
- `connectivity_score` is a normalized connectivity measure.
- `activity_rank_pct` is the station's activity percentile within its city.
- `is_transfer_proxy` flags stations in the upper connectivity range.
- `connectivity` keeps the underlying raw connectivity value.
- `residential_density_ratio` compares station-buffer density against the city average.

Important modeling caveat: Delhi and Seattle activity now use the same density/connectivity proxy recipe, but their connectivity sources still differ. Delhi connectivity currently comes from distinct trip-file OD links, while Seattle connectivity comes from GTFS departures plus stop count. Delhi passenger counts remain the supervised target, not a station-vector input.

## Delhi Trip Feature Schema

`delhi_trip_features.csv` is the current supervised-learning table.

Feature groups:

- Identifiers: `TripID`, `from_station_id`, `to_station_id`.
- Calendar context: `day_of_week`, `month`, `year`, `is_weekend`.
- Operating context: `is_peak`, `is_off_peak`, `is_festival`, `is_maintenance`.
- Trip attributes: `Distance_km`, `Fare`, `Cost_per_passenger`.
- Origin vector fields: `origin_activity_score`, `origin_connectivity_score`, `origin_activity_rank_pct`, `origin_is_transfer_proxy`, `origin_connectivity`, `origin_residential_density_ratio`.
- Destination vector fields: same fields with the `destination_` prefix.
- Encoded categories: ticket type and remark one-hot columns.
- Target: `target_passengers`.

The future dispersion model should start from this table because it already expresses each trip as a relationship between an origin vector, a destination vector, and contextual features.

## How the Data Is Currently Used

Current usage is feature generation and baseline modeling:

- Delhi raw trips become trip-level supervised examples and station connectivity inputs; passenger counts remain labels.
- Delhi trip labels train the city-generic timelapse model as passenger load per train.
- Seattle station vectors are built in the same schema as Delhi vectors for transfer, comparison, or demo scoring.
- Seattle heatmap features are used by a baseline model that predicts `target_count` for grid cells with sparse observations.
- The GeoJSON heatmap grid is intended for map visualization.

## Future Dispersion Model Plan

For this project, define dispersion as the expected spread of passenger demand from an origin station to possible destination stations under a given time and operating context.

The Delhi data supports this because each row has:

- An origin station vector.
- A destination station vector.
- Trip context.
- A passenger target.

The Seattle data supports transfer because each Seattle station can be represented with the same station-vector fields.

### Phase 1: Establish a Delhi Baseline

Create a new training script, for example `train_dispersion_model.py`, that reads:

- `curr_data/processed/delhi_train_features.csv`
- `curr_data/processed/delhi_test_features.csv`

Initial target:

- `target_passengers`

Initial feature set:

- Origin and destination station-vector fields.
- Calendar and operating-context fields.
- Distance, fare, and cost fields when available.
- Ticket and remark one-hot columns.

Recommended first model:

- `HistGradientBoostingRegressor`, `RandomForestRegressor`, or XGBoost/LightGBM if extra dependencies are acceptable.

Evaluation:

- MAE and RMSE for passenger count.
- R2 or explained variance for general fit.
- Error by weekend/weekday and peak/off-peak.
- Error by activity-rank buckets to verify high-demand station behavior.

Expected outputs:

- `dispersion_model_metrics.json`
- `delhi_dispersion_predictions.csv`
- Serialized model artifact, such as `models/dispersion_model.joblib`.

### Phase 2: Model OD Dispersion Explicitly

The baseline predicts passengers for known OD rows. A dispersion model for another city should score many possible OD pairs.

Add a feature builder that expands station vectors into candidate OD pairs:

```text
station_vectors
        |
        v
candidate origin/destination pairs
        |
        v
OD pair features
        |
        v
trained model scores
        |
        v
predicted passenger dispersion matrix
```

Additional pair-level features to add:

- Great-circle distance between origin and destination.
- Difference and product terms between origin and destination scores.
- Origin activity multiplied by destination activity.
- Origin residential density ratio multiplied by destination activity.
- Connectivity balance between origin and destination.
- Same-station or very-short-distance filter.

Outputs:

- `city_od_candidate_features.csv`
- `city_dispersion_predictions.csv`
- A station-by-station dispersion matrix for visualization.

### Phase 3: Transfer to Seattle

Use `seattle_station_vectors.csv` as the station universe.

Process:

1. Generate all plausible Seattle origin/destination station pairs.
2. Add the same OD pair features used for Delhi.
3. Fill or omit Delhi-only fields that are not reproducible in Seattle.
4. Apply the trained Delhi model.
5. Normalize predictions for demo use, because Seattle predictions will be relative unless calibrated with local ridership.

Recommended output fields:

```text
origin_station_id
destination_station_id
origin_lat
origin_lon
destination_lat
destination_lon
predicted_passengers
predicted_share
dispersion_score
```

For the demo, `predicted_share` or `dispersion_score` may be more useful than raw passenger counts because Seattle lacks matching observed metro passenger labels.

### Phase 4: Calibrate With Local City Data

Direct transfer from Delhi to Seattle has distribution shift. Calibration should be added as soon as local labels or constraints are available.

Useful calibration sources:

- GTFS departures as supply constraints.
- Station boardings if available from a transit agency.
- Pedestrian or bike counters near stations.
- Event, employment, or land-use data.
- Known route topology or transfer stations.

Calibration options:

- Scale predicted OD totals to match known station-level boardings.
- Constrain total demand by hour or day.
- Fine-tune on any city-specific labeled data.
- Train a domain-adaptation layer that maps Seattle proxy activity to Delhi-like activity.

### Phase 5: Integrate With the Seattle Demo

The Seattle demo can use two complementary outputs:

- Station-level dispersion predictions from the Delhi-trained model.
- Grid-level intensity from the existing Seattle heatmap pipeline.

Possible integration:

1. Use the dispersion model to predict station-to-station demand.
2. Render predicted flows as arcs or weighted links between stations.
3. Use station scores to seed local heat around stations.
4. Blend with `seattle_heatmap_predictions.csv` to show both station demand and neighborhood congestion.

## Data Quality and Modeling Risks

- Some Delhi trip station names may not match the coordinate/density source, leaving missing `lat`, `lon`, or density fields.
- Delhi `activity_score` and Seattle `activity_score` share the same density/connectivity proxy recipe, but Delhi connectivity is OD-link based unless a reliable Delhi Metro GTFS/service feed is supplied.
- Delhi GTFS frequency is optional because a stable public DMRC GTFS URL is not bundled. Without it, training still predicts load per train, but Delhi scheduled-train features are zero and hourly flow depends on the scored city's GTFS.
- Seattle station vectors are GTFS stop based, not a direct equivalent of Delhi Metro station topology.
- The current heatmap model has only 168 observed target rows, so it should be treated as a demo proxy.
- A transferred model should be reported as relative demand or dispersion unless calibrated against local labels.

## Recommended Next Implementation Steps

1. Find or curate a trustworthy Delhi Metro GTFS/service-frequency source and run `src.pipelines.delhi.build_gtfs_frequency` with it.
2. Calibrate transferred hourly flow against any local ridership, boardings, counters, or event attendance data available for the target city.
3. Add route-shape exposure, not only station/frequency exposure, so new routes can affect cells between stops more directly.
4. Add a map-facing export that tiles or compresses the 24x7 prediction CSV for fast frontend playback.
5. Keep the older OD-dispersion idea as a separate layer if the UI needs station-to-station arcs in addition to grid heat.

