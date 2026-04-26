#!/usr/bin/env python3
"""Build Delhi cell-level heatmap training features from passenger-per-train labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.common.artifacts import (
    DEFAULT_PROCESSED_DIR,
    DELHI_HEATMAP_TRAINING_FEATURES_CSV,
    DELHI_STATION_GTFS_FREQUENCY_CSV,
    DELHI_STATION_VECTORS_CSV,
    DELHI_TRIP_FEATURES_CSV,
)
from src.common.heatmap_utils import (
    add_hour_context,
    bbox_from_points,
    build_grid,
    cell_id_for,
    context_hours,
)
from src.common.io_utils import ensure_dir, write_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Delhi heatmap training features.")
    parser.add_argument(
        "--trip-features",
        default=str(DEFAULT_PROCESSED_DIR / DELHI_TRIP_FEATURES_CSV),
        help="Delhi trip features with passenger-per-train labels.",
    )
    parser.add_argument(
        "--station-vectors",
        default=str(DEFAULT_PROCESSED_DIR / DELHI_STATION_VECTORS_CSV),
        help="Delhi station vectors with density and station context.",
    )
    parser.add_argument(
        "--frequency-csv",
        default=str(DEFAULT_PROCESSED_DIR / DELHI_STATION_GTFS_FREQUENCY_CSV),
        help="Delhi station-hour GTFS frequency features.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_PROCESSED_DIR), help="Output directory.")
    parser.add_argument("--cell-size-m", type=int, default=1000, help="Training grid cell size.")
    parser.add_argument("--time-bin-minutes", type=int, default=30, help="Training interval size.")
    return parser.parse_args()


def load_frequency(path: Path, station_ids: list[str], bin_minutes: int) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        frequency = pd.read_csv(path)
        if "time_bin" not in frequency:
            frequency["time_bin"] = pd.to_numeric(frequency["hour"], errors="coerce").fillna(0).astype(int) * 60
        if "hour" not in frequency:
            frequency["hour"] = (frequency["time_bin"] // 60).astype(int)
        if "minute" not in frequency:
            frequency["minute"] = (frequency["time_bin"] % 60).astype(int)
    else:
        bins = list(range(0, 1440, bin_minutes))
        full_index = pd.MultiIndex.from_product([station_ids, bins], names=["station_id", "time_bin"])
        frequency = full_index.to_frame(index=False)
        frequency["hour"] = (frequency["time_bin"] // 60).astype(int)
        frequency["minute"] = (frequency["time_bin"] % 60).astype(int)
        frequency["scheduled_trains"] = 0
        frequency["daily_scheduled_trains"] = 0
        frequency["has_gtfs_frequency"] = 0
    for column in ["scheduled_trains", "daily_scheduled_trains", "has_gtfs_frequency"]:
        if column not in frequency:
            frequency[column] = 0
    return frequency


def station_cell_features(stations: pd.DataFrame, cell_size_m: int) -> pd.DataFrame:
    valid = stations.dropna(subset=["lat", "lon"]).copy()
    bbox = bbox_from_points(valid["lat"], valid["lon"], padding_degrees=0.02)
    _, spec = build_grid(bbox, cell_size_m)
    valid["cell_id"] = [cell_id_for(lat, lon, spec) for lat, lon in zip(valid["lat"], valid["lon"])]
    valid["center_lat"] = valid["lat"]
    valid["center_lon"] = valid["lon"]
    return valid


def explode_context_bins(records: pd.DataFrame, bin_minutes: int) -> pd.DataFrame:
    rows = []
    for record in records.itertuples(index=False):
        values = record._asdict()
        for hour in context_hours(pd.Series(values)):
            for minute in [0, 30] if bin_minutes == 30 else [0]:
                time_bin = hour * 60 + minute
                if time_bin % bin_minutes != 0:
                    continue
                row = dict(values)
                row["time_bin"] = time_bin
                row["hour"] = hour
                row["minute"] = minute
                rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    out_dir = ensure_dir(Path(args.out_dir))
    trips = pd.read_csv(args.trip_features)
    stations = pd.read_csv(args.station_vectors)
    stations = station_cell_features(stations, args.cell_size_m)
    station_ids = sorted(stations["station_id"].dropna().astype(str).unique())
    frequency = load_frequency(Path(args.frequency_csv), station_ids, args.time_bin_minutes)

    base_columns = [
        "station_id",
        "cell_id",
        "center_lat",
        "center_lon",
        "activity_score",
        "connectivity_score",
        "activity_rank_pct",
        "is_transfer_proxy",
        "connectivity",
        "residential_density_ratio",
    ]
    station_lookup = stations[base_columns].copy()

    origin = trips.rename(columns={"from_station_id": "station_id"})[
        [
            "station_id",
            "day_of_week",
            "is_weekend",
            "is_peak",
            "is_off_peak",
            "is_festival",
            "is_maintenance",
            "target_passengers",
        ]
    ]
    origin["flow_role"] = "origin"
    destination = trips.rename(columns={"to_station_id": "station_id"})[
        [
            "station_id",
            "day_of_week",
            "is_weekend",
            "is_peak",
            "is_off_peak",
            "is_festival",
            "is_maintenance",
            "target_passengers",
        ]
    ]
    destination["flow_role"] = "destination"
    records = pd.concat([origin, destination], ignore_index=True).dropna(subset=["target_passengers"])
    records = records.merge(station_lookup, on="station_id", how="inner")
    records = explode_context_bins(records, args.time_bin_minutes)
    records = records.merge(frequency, on=["station_id", "time_bin"], how="left", suffixes=("", "_freq"))
    records["hour"] = records["hour"].fillna(records.get("hour_freq")).astype(int)
    records["minute"] = records["minute"].fillna(records.get("minute_freq")).astype(int)
    records = add_hour_context(records)
    for column in ["scheduled_trains", "daily_scheduled_trains", "has_gtfs_frequency"]:
        records[column] = pd.to_numeric(records[column], errors="coerce").fillna(0)

    group_columns = [
        "cell_id",
        "center_lat",
        "center_lon",
        "station_id",
        "flow_role",
        "time_bin",
        "hour",
        "minute",
        "day_of_week",
        "is_weekend",
        "is_peak",
        "is_off_peak",
        "is_morning_commute",
        "is_evening_commute",
        "is_workday_midday",
        "is_festival",
        "is_maintenance",
        "activity_score",
        "connectivity_score",
        "activity_rank_pct",
        "is_transfer_proxy",
        "connectivity",
        "residential_density_ratio",
        "scheduled_trains",
        "daily_scheduled_trains",
        "has_gtfs_frequency",
    ]
    training = (
        records.groupby(group_columns, as_index=False)
        .agg(load_per_train=("target_passengers", "mean"), sample_count=("target_passengers", "count"))
    )
    training["nearest_station_distance_m"] = 0.0
    training["stations_within_500m"] = 1
    training["stations_within_1000m"] = 1
    training["distance_weighted_station_activity"] = training["activity_score"]
    training["distance_weighted_connectivity"] = training["connectivity"]
    training["distance_weighted_residential_density"] = training["residential_density_ratio"]
    training["distance_weighted_transfer_score"] = training["is_transfer_proxy"]
    training["distance_weighted_office_jobs"] = 0.0
    training["office_jobs_nearby"] = 0.0
    residential_factor = training.apply(
        lambda row: 1.10
        if row["is_weekend"]
        else 1.15
        if row["is_morning_commute"]
        else 1.20
        if row["is_evening_commute"]
        else 0.75
        if row["is_workday_midday"]
        else 0.50
        if row["is_off_peak"]
        else 0.90,
        axis=1,
    )
    training["residential_temporal_demand"] = (
        training["distance_weighted_residential_density"] * residential_factor
    )
    training["office_temporal_demand"] = 0.0
    training["commute_demand_score"] = training["residential_temporal_demand"]
    training["target_time_bin_flow"] = training["load_per_train"] * training["scheduled_trains"]
    training["target_hourly_flow"] = training["target_time_bin_flow"]
    output_path = write_csv(training, out_dir / DELHI_HEATMAP_TRAINING_FEATURES_CSV)
    print(
        json.dumps(
            {
                "rows": int(len(training)),
                "stations": int(training["station_id"].nunique()),
                "gtfs_frequency_rows": int((training["has_gtfs_frequency"] > 0).sum()),
                "time_bin_minutes": args.time_bin_minutes,
                "output": str(output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
