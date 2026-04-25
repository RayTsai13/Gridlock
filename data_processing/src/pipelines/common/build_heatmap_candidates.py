#!/usr/bin/env python3
"""Build city-generic heatmap candidate features for baseline or scenario scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.artifacts import (
    CITY_HEATMAP_CANDIDATE_FEATURES_CSV,
    DEFAULT_GTFS_DIR,
    DEFAULT_PROCESSED_DIR,
    HEATMAP_TIMELAPSE_GRID_GEOJSON,
    SEATTLE_STATION_VECTORS_CSV,
)
from src.common.gtfs_utils import (
    DEFAULT_SEATTLE_STATION_AGENCY_IDS,
    DEFAULT_STATION_ROUTE_TYPES,
    build_station_hourly_frequency,
    parse_agency_ids,
    parse_route_types,
)
from src.common.heatmap_utils import (
    add_hour_context,
    bbox_from_points,
    build_grid,
    build_station_exposure,
    haversine_m,
    write_grid_geojson,
)
from src.common.io_utils import ensure_dir, write_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build heatmap candidate features for a city.")
    parser.add_argument(
        "--station-vectors",
        default=str(DEFAULT_PROCESSED_DIR / SEATTLE_STATION_VECTORS_CSV),
        help="Station vectors for the city to score.",
    )
    parser.add_argument("--gtfs-dir", default=str(DEFAULT_GTFS_DIR), help="GTFS directory for the city.")
    parser.add_argument("--out-dir", default=str(DEFAULT_PROCESSED_DIR), help="Output directory.")
    parser.add_argument("--output-name", default=CITY_HEATMAP_CANDIDATE_FEATURES_CSV)
    parser.add_argument("--grid-output-name", default=HEATMAP_TIMELAPSE_GRID_GEOJSON)
    parser.add_argument("--cell-size-m", type=int, default=500)
    parser.add_argument("--bbox", help="Optional bbox as min_lon,min_lat,max_lon,max_lat.")
    parser.add_argument("--decay-m", type=float, default=800.0, help="Distance decay for station exposure.")
    parser.add_argument(
        "--route-types",
        default=",".join(str(route_type) for route_type in DEFAULT_STATION_ROUTE_TYPES),
        help="Comma-separated GTFS route_type values to keep for frequency. Default keeps rail/station modes: 0,1,2.",
    )
    parser.add_argument(
        "--agency-ids",
        default=",".join(DEFAULT_SEATTLE_STATION_AGENCY_IDS),
        help="Comma-separated GTFS agency_id values to keep for frequency. Default keeps Sound Transit: 40.",
    )
    parser.add_argument("--added-stations-csv", help="Optional station rows to add before scoring.")
    parser.add_argument("--removed-stations-csv", help="Optional CSV with station_id rows to remove.")
    parser.add_argument(
        "--frequency-delta-csv",
        help="Optional CSV with station_id,hour,scheduled_trains_delta rows for route/frequency scenarios.",
    )
    return parser.parse_args()


def parse_bbox(value: str | None, stations: pd.DataFrame) -> tuple[float, float, float, float]:
    if value:
        parts = [float(part.strip()) for part in value.split(",")]
        if len(parts) != 4:
            raise ValueError("--bbox must be min_lon,min_lat,max_lon,max_lat")
        return tuple(parts)  # type: ignore[return-value]
    return bbox_from_points(stations["lat"], stations["lon"], padding_degrees=0.02)


def apply_station_scenarios(stations: pd.DataFrame, added_csv: str | None, removed_csv: str | None) -> pd.DataFrame:
    result = stations.copy()
    if removed_csv:
        removed = pd.read_csv(removed_csv)
        if "station_id" not in removed:
            raise ValueError("--removed-stations-csv must include station_id")
        result = result[~result["station_id"].isin(removed["station_id"].astype(str))]
    if added_csv:
        added = pd.read_csv(added_csv)
        required = {"station_id", "lat", "lon"}
        missing = required.difference(added.columns)
        if missing:
            raise ValueError(f"--added-stations-csv missing columns: {', '.join(sorted(missing))}")
        for column in result.columns:
            if column not in added:
                added[column] = 0
        result = pd.concat([result, added[result.columns]], ignore_index=True)
    return result.dropna(subset=["lat", "lon"])


def load_frequency(
    gtfs_dir: Path,
    stations: pd.DataFrame,
    delta_csv: str | None,
    route_types: tuple[int, ...] | None,
    agency_ids: tuple[str, ...] | None,
) -> pd.DataFrame:
    station_ids = sorted(stations["station_id"].dropna().astype(str).unique())
    if all((gtfs_dir / name).exists() for name in ["stops.txt", "stop_times.txt", "trips.txt"]):
        frequency = build_station_hourly_frequency(
            gtfs_dir, station_ids=station_ids, route_types=route_types, agency_ids=agency_ids
        )
    else:
        full_index = pd.MultiIndex.from_product([station_ids, range(24)], names=["station_id", "hour"])
        frequency = full_index.to_frame(index=False)
        frequency["scheduled_trains"] = 0
        frequency["daily_scheduled_trains"] = 0
        frequency["has_gtfs_frequency"] = 0

    if delta_csv:
        delta = pd.read_csv(delta_csv)
        required = {"station_id", "hour", "scheduled_trains_delta"}
        missing = required.difference(delta.columns)
        if missing:
            raise ValueError(f"--frequency-delta-csv missing columns: {', '.join(sorted(missing))}")
        delta["hour"] = pd.to_numeric(delta["hour"], errors="coerce").astype(int)
        frequency = frequency.merge(delta, on=["station_id", "hour"], how="left")
        frequency["scheduled_trains_delta"] = pd.to_numeric(
            frequency["scheduled_trains_delta"], errors="coerce"
        ).fillna(0)
        frequency["scheduled_trains"] = (
            pd.to_numeric(frequency["scheduled_trains"], errors="coerce").fillna(0)
            + frequency["scheduled_trains_delta"]
        ).clip(lower=0)
        daily = frequency.groupby("station_id", as_index=False)["scheduled_trains"].sum().rename(
            columns={"scheduled_trains": "daily_scheduled_trains"}
        )
        frequency = frequency.drop(columns=["daily_scheduled_trains"], errors="ignore").merge(
            daily, on="station_id", how="left"
        )
        frequency["has_gtfs_frequency"] = (frequency["daily_scheduled_trains"] > 0).astype(int)
    return frequency


def frequency_exposure(grid: pd.DataFrame, stations: pd.DataFrame, frequency: pd.DataFrame, decay_m: float) -> pd.DataFrame:
    grid_lat = grid["center_lat"].to_numpy()[:, None]
    grid_lon = grid["center_lon"].to_numpy()[:, None]
    station_lat = pd.to_numeric(stations["lat"], errors="coerce").to_numpy()[None, :]
    station_lon = pd.to_numeric(stations["lon"], errors="coerce").to_numpy()[None, :]
    distances = haversine_m(grid_lat, grid_lon, station_lat, station_lon)
    weights = np.exp(-distances / decay_m)
    station_ids = stations["station_id"].astype(str).tolist()

    hourly = (
        frequency.pivot_table(index="station_id", columns="hour", values="scheduled_trains", aggfunc="sum")
        .reindex(station_ids)
        .fillna(0)
    )
    for hour in range(24):
        if hour not in hourly:
            hourly[hour] = 0
    hourly = hourly[range(24)]
    hourly_exposure = weights @ hourly.to_numpy()
    daily = hourly.sum(axis=1).to_numpy()
    daily_exposure = weights @ daily

    rows = []
    for hour in range(24):
        frame = grid[["cell_id"]].copy()
        frame["hour"] = hour
        frame["scheduled_trains"] = hourly_exposure[:, hour]
        frame["daily_scheduled_trains"] = daily_exposure
        frame["has_gtfs_frequency"] = (frame["daily_scheduled_trains"] > 0).astype(int)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    args = parse_args()
    out_dir = ensure_dir(Path(args.out_dir))
    stations = pd.read_csv(args.station_vectors)
    route_types = parse_route_types(args.route_types)
    agency_ids = parse_agency_ids(args.agency_ids)
    stations = apply_station_scenarios(stations, args.added_stations_csv, args.removed_stations_csv)
    bbox = parse_bbox(args.bbox, stations)
    grid, _ = build_grid(bbox, args.cell_size_m)
    exposure = build_station_exposure(grid, stations, decay_m=args.decay_m)
    frequency = load_frequency(
        Path(args.gtfs_dir), stations, args.frequency_delta_csv, route_types, agency_ids
    )
    freq_exposure = frequency_exposure(grid, stations, frequency, args.decay_m)

    base = grid[["cell_id", "center_lat", "center_lon", "row", "col", "min_lat", "min_lon", "max_lat", "max_lon"]]
    candidates = base.merge(exposure, on="cell_id", how="left").merge(freq_exposure, on="cell_id", how="left")
    days = pd.DataFrame({"day_of_week": range(7)})
    candidates = candidates.merge(days, how="cross")
    candidates = add_hour_context(candidates)
    output_path = write_csv(candidates, out_dir / args.output_name)
    write_grid_geojson(grid, out_dir / args.grid_output_name)
    print(
        json.dumps(
            {
                "rows": int(len(candidates)),
                "grid_cells": int(grid["cell_id"].nunique()),
                "stations": int(len(stations)),
                "route_types": list(route_types) if route_types is not None else "all",
                "agency_ids": list(agency_ids) if agency_ids is not None else "all",
                "output": str(output_path),
                "grid": str(out_dir / args.grid_output_name),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
