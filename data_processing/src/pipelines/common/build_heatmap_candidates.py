#!/usr/bin/env python3
"""Build city-generic heatmap candidate features for baseline or scenario scoring."""

from __future__ import annotations

import argparse
import json
import math
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


SEATTLE_BBOX = (-122.4597, 47.4810, -122.2244, 47.7340)


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
    parser.add_argument("--time-bin-minutes", type=int, default=30, help="Timelapse interval size.")
    parser.add_argument(
        "--bbox",
        default=",".join(str(value) for value in SEATTLE_BBOX),
        help=(
            "Grid bbox as min_lon,min_lat,max_lon,max_lat. Defaults to a full Seattle "
            "bbox; pass a city-specific bbox for other cities."
        ),
    )
    parser.add_argument("--decay-m", type=float, default=800.0, help="Distance decay for station exposure.")
    parser.add_argument(
        "--office-features-csv",
        default=str(DEFAULT_PROCESSED_DIR / "seattle_heatmap_features.csv"),
        help="Optional grid features with employment_jobs used as office demand signal.",
    )
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
    parser.add_argument(
        "--ballard-corridor-density-proxy",
        action="store_true",
        help=(
            "Add a localized residential-density bump only within ~2 km of the Ballard extension "
            "polyline (examples/scenarios/ballard_line_stations.csv). Does NOT lift the whole west side."
        ),
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
    bin_minutes: int,
) -> pd.DataFrame:
    station_ids = sorted(stations["station_id"].dropna().astype(str).unique())
    if all((gtfs_dir / name).exists() for name in ["stops.txt", "stop_times.txt", "trips.txt"]):
        frequency = build_station_hourly_frequency(
            gtfs_dir,
            station_ids=station_ids,
            route_types=route_types,
            agency_ids=agency_ids,
            bin_minutes=bin_minutes,
        )
    else:
        bins = list(range(0, 1440, bin_minutes))
        full_index = pd.MultiIndex.from_product([station_ids, bins], names=["station_id", "time_bin"])
        frequency = full_index.to_frame(index=False)
        frequency["hour"] = (frequency["time_bin"] // 60).astype(int)
        frequency["minute"] = (frequency["time_bin"] % 60).astype(int)
        frequency["scheduled_trains"] = 0
        frequency["daily_scheduled_trains"] = 0
        frequency["has_gtfs_frequency"] = 0

    if delta_csv:
        delta = pd.read_csv(delta_csv)
        required = {"station_id", "scheduled_trains_delta"}
        missing = required.difference(delta.columns)
        if missing:
            raise ValueError(f"--frequency-delta-csv missing columns: {', '.join(sorted(missing))}")
        if "time_bin" not in delta:
            if "hour" not in delta:
                raise ValueError("--frequency-delta-csv must include hour or time_bin")
            delta["hour"] = pd.to_numeric(delta["hour"], errors="coerce").fillna(0).astype(int)
            if "minute" in delta:
                delta["time_bin"] = delta["hour"] * 60 + pd.to_numeric(
                    delta["minute"], errors="coerce"
                ).fillna(0).astype(int)
            else:
                repeats = []
                for row in delta.itertuples(index=False):
                    base = int(row.hour) * 60
                    for offset in range(0, 60, bin_minutes):
                        values = row._asdict()
                        values["time_bin"] = base + offset
                        repeats.append(values)
                delta = pd.DataFrame(repeats)
        delta["time_bin"] = pd.to_numeric(delta["time_bin"], errors="coerce").astype(int)
        frequency = frequency.merge(delta, on=["station_id", "time_bin"], how="left")
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


def frequency_exposure(
    grid: pd.DataFrame,
    stations: pd.DataFrame,
    frequency: pd.DataFrame,
    decay_m: float,
    bin_minutes: int,
) -> pd.DataFrame:
    grid_lat = grid["center_lat"].to_numpy()[:, None]
    grid_lon = grid["center_lon"].to_numpy()[:, None]
    station_lat = pd.to_numeric(stations["lat"], errors="coerce").to_numpy()[None, :]
    station_lon = pd.to_numeric(stations["lon"], errors="coerce").to_numpy()[None, :]
    distances = haversine_m(grid_lat, grid_lon, station_lat, station_lon)
    weights = np.exp(-distances / decay_m)
    station_ids = stations["station_id"].astype(str).tolist()

    hourly = (
        frequency.pivot_table(index="station_id", columns="time_bin", values="scheduled_trains", aggfunc="sum")
        .reindex(station_ids)
        .fillna(0)
    )
    bins = list(range(0, 1440, bin_minutes))
    for time_bin in bins:
        if time_bin not in hourly:
            hourly[time_bin] = 0
    hourly = hourly[bins]
    hourly_exposure = weights @ hourly.to_numpy()
    daily = hourly.sum(axis=1).to_numpy()
    daily_exposure = weights @ daily

    rows = []
    for index, time_bin in enumerate(bins):
        frame = grid[["cell_id"]].copy()
        frame["time_bin"] = time_bin
        frame["hour"] = time_bin // 60
        frame["minute"] = time_bin % 60
        frame["scheduled_trains"] = hourly_exposure[:, index]
        frame["daily_scheduled_trains"] = daily_exposure
        frame["has_gtfs_frequency"] = (frame["daily_scheduled_trains"] > 0).astype(int)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def office_exposure(grid: pd.DataFrame, office_features_csv: str | None, decay_m: float) -> pd.DataFrame:
    result = grid[["cell_id"]].copy()
    result["distance_weighted_office_jobs"] = 0.0
    result["office_jobs_nearby"] = 0.0
    if not office_features_csv:
        return result
    path = Path(office_features_csv)
    if not path.exists() or path.stat().st_size == 0:
        return result
    office = pd.read_csv(path, usecols=lambda col: col in {"cell_id", "center_lat", "center_lon", "employment_jobs"})
    if not {"center_lat", "center_lon", "employment_jobs"}.issubset(office.columns):
        return result
    office = (
        office[["cell_id", "center_lat", "center_lon", "employment_jobs"]]
        .drop_duplicates("cell_id")
        .dropna(subset=["center_lat", "center_lon"])
    )
    office["employment_jobs"] = pd.to_numeric(office["employment_jobs"], errors="coerce").fillna(0)
    office = office[office["employment_jobs"] > 0]
    if office.empty:
        return result

    grid_lat = grid["center_lat"].to_numpy()[:, None]
    grid_lon = grid["center_lon"].to_numpy()[:, None]
    office_lat = office["center_lat"].to_numpy()[None, :]
    office_lon = office["center_lon"].to_numpy()[None, :]
    distances = haversine_m(grid_lat, grid_lon, office_lat, office_lon)
    weights = np.exp(-distances / decay_m)
    jobs = office["employment_jobs"].to_numpy()
    result["distance_weighted_office_jobs"] = weights @ jobs
    result["office_jobs_nearby"] = ((distances <= 1000) * jobs).sum(axis=1)
    return result


_BALLARD_FALLBACK_POLY: list[tuple[float, float]] = [
    (47.6677, -122.3765),
    (47.6478, -122.3765),
    (47.6378, -122.3635),
    (47.6243, -122.3520),
    (47.6258, -122.3377),
    (47.6188, -122.3405),
]


def _read_ballard_polyline() -> list[tuple[float, float]]:
    csv_path = Path(__file__).resolve().parents[3] / "examples" / "scenarios" / "ballard_line_stations.csv"
    if not csv_path.exists():
        return _BALLARD_FALLBACK_POLY
    df = pd.read_csv(csv_path)
    if "sequence" in df.columns:
        df = df.sort_values("sequence")
    df = df.assign(
        lat=pd.to_numeric(df["lat"], errors="coerce"),
        lon=pd.to_numeric(df["lon"], errors="coerce"),
    ).dropna(subset=["lat", "lon"])
    if len(df) < 2:
        return _BALLARD_FALLBACK_POLY
    return list(zip(df["lat"].astype(float).tolist(), df["lon"].astype(float).tolist()))


def _polyline_min_distance_m(
    lat: np.ndarray, lon: np.ndarray, poly: list[tuple[float, float]]
) -> np.ndarray:
    if len(poly) < 2:
        return np.full(lat.shape, 1e9)
    origin_lat = float(np.mean([p[0] for p in poly]))
    origin_lon = float(np.mean([p[1] for p in poly]))
    mplat = 111_320.0
    mplon = 111_320.0 * math.cos(math.radians(origin_lat))
    xs = np.array([(p[1] - origin_lon) * mplon for p in poly], dtype=float)
    ys = np.array([(p[0] - origin_lat) * mplat for p in poly], dtype=float)
    px = (lon - origin_lon) * mplon
    py = (lat - origin_lat) * mplat
    stacks: list[np.ndarray] = []
    for i in range(len(poly) - 1):
        abx = xs[i + 1] - xs[i]
        aby = ys[i + 1] - ys[i]
        length_sq = abx * abx + aby * aby
        if length_sq == 0:
            stacks.append(np.sqrt((px - xs[i]) ** 2 + (py - ys[i]) ** 2))
            continue
        t = np.clip(((px - xs[i]) * abx + (py - ys[i]) * aby) / length_sq, 0, 1)
        nx = xs[i] + t * abx
        ny = ys[i] + t * aby
        stacks.append(np.sqrt((px - nx) ** 2 + (py - ny) ** 2))
    return np.vstack(stacks).min(axis=0)


def ballard_corridor_density_proxy(
    candidates: pd.DataFrame,
    *,
    decay_m: float = 700.0,
    max_influence_m: float = 2200.0,
    amplitude_ratio: float = 0.50,
) -> pd.DataFrame:
    """Localized residential-density bump within ~2 km of the Ballard extension polyline.

    Operates per-cell (one row per cell_id) and is invoked BEFORE the day-of-week
    cross-merge so the bump is not duplicated 7x.
    """
    out = candidates.copy()
    if "distance_weighted_residential_density" not in out.columns:
        return out
    poly = _read_ballard_polyline()
    lat = pd.to_numeric(out["center_lat"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    lon = pd.to_numeric(out["center_lon"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    res = pd.to_numeric(out["distance_weighted_residential_density"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if not res.size:
        return out
    ref = float(np.percentile(res, 82))
    ref = max(ref, 0.10)
    d = _polyline_min_distance_m(lat, lon, poly)
    bump = np.where(
        d <= max_influence_m,
        amplitude_ratio * ref * np.exp(-d / decay_m),
        0.0,
    )
    out["distance_weighted_residential_density"] = res + bump
    return out


def add_temporal_land_use_demand(candidates: pd.DataFrame) -> pd.DataFrame:
    result = candidates.copy()
    residential = pd.to_numeric(result["distance_weighted_residential_density"], errors="coerce").fillna(0)
    office = pd.to_numeric(result.get("distance_weighted_office_jobs", 0), errors="coerce").fillna(0)
    residential_factor = np.select(
        [
            result["is_weekend"] == 1,
            result["is_morning_commute"] == 1,
            result["is_evening_commute"] == 1,
            result["is_workday_midday"] == 1,
            result["is_off_peak"] == 1,
        ],
        [1.10, 1.15, 1.20, 0.75, 0.50],
        default=0.90,
    )
    office_factor = np.select(
        [
            result["is_weekend"] == 1,
            result["is_morning_commute"] == 1,
            result["is_evening_commute"] == 1,
            result["is_workday_midday"] == 1,
            result["is_off_peak"] == 1,
        ],
        [0.25, 1.20, 1.20, 1.00, 0.10],
        default=0.60,
    )
    result["residential_temporal_demand"] = residential * residential_factor
    result["office_temporal_demand"] = office * office_factor
    result["commute_demand_score"] = (
        result["residential_temporal_demand"] + result["office_temporal_demand"]
    )
    return result


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
        Path(args.gtfs_dir),
        stations,
        args.frequency_delta_csv,
        route_types,
        agency_ids,
        args.time_bin_minutes,
    )
    freq_exposure = frequency_exposure(grid, stations, frequency, args.decay_m, args.time_bin_minutes)
    offices = office_exposure(grid, args.office_features_csv, args.decay_m)

    base = grid[["cell_id", "center_lat", "center_lon", "row", "col", "min_lat", "min_lon", "max_lat", "max_lon"]]
    candidates = (
        base.merge(exposure, on="cell_id", how="left")
        .merge(offices, on="cell_id", how="left")
    )
    if args.ballard_corridor_density_proxy:
        candidates = ballard_corridor_density_proxy(candidates)
    candidates = candidates.merge(freq_exposure, on="cell_id", how="left")
    days = pd.DataFrame({"day_of_week": range(7)})
    candidates = candidates.merge(days, how="cross")
    candidates = add_hour_context(candidates)
    candidates = add_temporal_land_use_demand(candidates)
    output_path = write_csv(candidates, out_dir / args.output_name)
    write_grid_geojson(grid, out_dir / args.grid_output_name)
    print(
        json.dumps(
            {
                "rows": int(len(candidates)),
                "grid_cells": int(grid["cell_id"].nunique()),
                "stations": int(len(stations)),
                "time_bin_minutes": args.time_bin_minutes,
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
