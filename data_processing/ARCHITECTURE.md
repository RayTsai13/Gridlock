# Data Pipeline Architecture and Dispersion Model Plan

This document describes the current data-processing architecture and the planned path for training a dispersion model from Delhi Metro data, then applying that learned behavior to station vectors from other cities such as Seattle.

The current repository does not yet contain a script named for "dispersion". Today it provides the data foundation: Delhi trip labels, reusable station vectors, train/test splits, Seattle station vectors with matching fields, and a separate Seattle heatmap baseline.

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
    pipelines/
      delhi/
        build_population_vectors.py
        transform_metro.py
        prepare_train_test.py
      seattle/
        build_station_vectors.py
        build_heatmap_dataset.py
    models/
      train_heatmap_model.py
  curr_data/
    raw/
    processed/
```

Most module defaults point at `data/raw` and `data/processed`. The current checked-in/generated artifacts in this workspace are under `curr_data/raw` and `curr_data/processed`, so future runs should either pass `--raw-dir curr_data/raw --out-dir curr_data/processed` or normalize the folder naming.

## Current Architecture

There are two related but separate data paths.

### 1. Cross-City Station Vector Pipeline

This is the path that supports a future dispersion model.

```text
Delhi station coordinates
Delhi ward geometry + population
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

- 43 Seattle stations.
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
                    +--> model_metrics.json
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
- Delhi train/test files are prepared but no Delhi passenger or dispersion model script exists yet.
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
- Delhi `activity_score` and Seattle `activity_score` share the same density/connectivity proxy recipe, but Delhi connectivity is OD-link based until a Delhi GTFS/service feed is integrated.
- Seattle station vectors are GTFS stop based, not a direct equivalent of Delhi Metro station topology.
- The current heatmap model has only 168 observed target rows, so it should be treated as a demo proxy.
- Folder naming is inconsistent between script defaults (`data/processed`) and current artifacts (`curr_data/processed`).
- A transferred model should be reported as relative demand or dispersion unless calibrated against local labels.

## Recommended Next Implementation Steps

1. Normalize paths so scripts consistently use either `data/` or `curr_data/`.
2. Add a Delhi dispersion training script using `delhi_train_features.csv` and `delhi_test_features.csv`.
3. Add a reusable OD-pair feature builder for any city station-vector file.
4. Add a Seattle scoring script that creates Seattle OD pairs and applies the Delhi-trained model.
5. Add evaluation and visualization outputs: metrics JSON, prediction CSV, and map-ready flow files.
6. Decide how to calibrate Seattle predictions for the demo: relative score only, GTFS-scaled score, or local-observation-scaled score.

