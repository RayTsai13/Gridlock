"""Reusable grid, exposure, and scenario helpers for heatmap features."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GridSpec:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    cell_size_m: int
    lat_step: float
    lon_step: float
    rows: int
    cols: int


def make_grid_spec(bbox: tuple[float, float, float, float], cell_size_m: int) -> GridSpec:
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    lat_step = cell_size_m / 111_320
    lon_step = cell_size_m / (111_320 * math.cos(math.radians(mid_lat)))
    rows = math.ceil((max_lat - min_lat) / lat_step)
    cols = math.ceil((max_lon - min_lon) / lon_step)
    return GridSpec(min_lon, min_lat, max_lon, max_lat, cell_size_m, lat_step, lon_step, rows, cols)


def bbox_from_points(lat: pd.Series, lon: pd.Series, padding_degrees: float = 0.02) -> tuple[float, float, float, float]:
    return (
        float(pd.to_numeric(lon, errors="coerce").min() - padding_degrees),
        float(pd.to_numeric(lat, errors="coerce").min() - padding_degrees),
        float(pd.to_numeric(lon, errors="coerce").max() + padding_degrees),
        float(pd.to_numeric(lat, errors="coerce").max() + padding_degrees),
    )


def cell_id_for(lat: float, lon: float, spec: GridSpec) -> str | None:
    if lon < spec.min_lon or lon > spec.max_lon or lat < spec.min_lat or lat > spec.max_lat:
        return None
    row = int((lat - spec.min_lat) / spec.lat_step)
    col = int((lon - spec.min_lon) / spec.lon_step)
    if row < 0 or col < 0 or row >= spec.rows or col >= spec.cols:
        return None
    return f"r{row:03d}_c{col:03d}"


def iter_grid_rows(spec: GridSpec) -> Iterable[dict]:
    for row in range(spec.rows):
        for col in range(spec.cols):
            min_lat = spec.min_lat + row * spec.lat_step
            max_lat = min(min_lat + spec.lat_step, spec.max_lat)
            min_lon = spec.min_lon + col * spec.lon_step
            max_lon = min(min_lon + spec.lon_step, spec.max_lon)
            yield {
                "cell_id": f"r{row:03d}_c{col:03d}",
                "row": row,
                "col": col,
                "center_lat": (min_lat + max_lat) / 2,
                "center_lon": (min_lon + max_lon) / 2,
                "min_lat": min_lat,
                "min_lon": min_lon,
                "max_lat": max_lat,
                "max_lon": max_lon,
            }


def build_grid(bbox: tuple[float, float, float, float], cell_size_m: int) -> tuple[pd.DataFrame, GridSpec]:
    spec = make_grid_spec(bbox, cell_size_m)
    return pd.DataFrame(iter_grid_rows(spec)), spec


def haversine_m(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    radius_m = 6_371_000
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    return 2 * radius_m * np.arcsin(np.sqrt(a))


def add_hour_context(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    if "time_bin" not in result:
        result["time_bin"] = result["hour"] * 60
    result["minute"] = pd.to_numeric(result["time_bin"], errors="coerce").fillna(0).astype(int) % 60
    result["is_weekend"] = result["day_of_week"].isin([5, 6]).astype(int)
    result["is_peak"] = result["hour"].isin([7, 8, 9, 16, 17, 18]).astype(int)
    result["is_off_peak"] = (~result["hour"].between(6, 21)).astype(int)
    result["is_morning_commute"] = result["hour"].isin([6, 7, 8, 9]).astype(int)
    result["is_evening_commute"] = result["hour"].isin([16, 17, 18, 19]).astype(int)
    result["is_workday_midday"] = ((result["is_weekend"] == 0) & result["hour"].between(10, 15)).astype(int)
    if "is_festival" not in result:
        result["is_festival"] = 0
    if "is_maintenance" not in result:
        result["is_maintenance"] = 0
    return result


def context_hours(row: pd.Series) -> list[int]:
    if int(row.get("is_peak", 0)) == 1:
        return [8, 18]
    if int(row.get("is_off_peak", 0)) == 1:
        return [11, 14, 21]
    if int(row.get("is_festival", 0)) == 1:
        return [12, 18, 21]
    if int(row.get("is_weekend", 0)) == 1:
        return [11, 15, 19]
    return [8, 12, 18]


def min_max(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    span = values.max() - values.min()
    if span == 0:
        return values * 0
    return (values - values.min()) / span


def build_station_exposure(
    grid: pd.DataFrame,
    stations: pd.DataFrame,
    decay_m: float = 800.0,
) -> pd.DataFrame:
    stations = stations.dropna(subset=["lat", "lon"]).copy()
    if stations.empty:
        result = grid[["cell_id"]].copy()
        for column in [
            "nearest_station_distance_m",
            "stations_within_500m",
            "stations_within_1000m",
            "distance_weighted_station_activity",
            "distance_weighted_connectivity",
            "distance_weighted_residential_density",
            "distance_weighted_transfer_score",
        ]:
            result[column] = 0.0
        return result

    grid_lat = grid["center_lat"].to_numpy()[:, None]
    grid_lon = grid["center_lon"].to_numpy()[:, None]
    station_lat = pd.to_numeric(stations["lat"], errors="coerce").to_numpy()[None, :]
    station_lon = pd.to_numeric(stations["lon"], errors="coerce").to_numpy()[None, :]
    distances = haversine_m(grid_lat, grid_lon, station_lat, station_lon)
    weights = np.exp(-distances / decay_m)

    def weighted(column: str) -> np.ndarray:
        values = pd.to_numeric(stations.get(column, 0), errors="coerce").fillna(0).to_numpy()
        return weights @ values

    result = grid[["cell_id"]].copy()
    result["nearest_station_distance_m"] = distances.min(axis=1)
    result["stations_within_500m"] = (distances <= 500).sum(axis=1)
    result["stations_within_1000m"] = (distances <= 1000).sum(axis=1)
    result["distance_weighted_station_activity"] = weighted("activity_score")
    result["distance_weighted_connectivity"] = weighted("connectivity")
    result["distance_weighted_residential_density"] = weighted("residential_density_ratio")
    result["distance_weighted_transfer_score"] = weighted("is_transfer_proxy")
    return result


def write_grid_geojson(grid: pd.DataFrame, output_path: Path) -> None:
    features = []
    for row in grid.itertuples(index=False):
        polygon = [
            [
                [row.min_lon, row.min_lat],
                [row.max_lon, row.min_lat],
                [row.max_lon, row.max_lat],
                [row.min_lon, row.max_lat],
                [row.min_lon, row.min_lat],
            ]
        ]
        properties = {
            "cell_id": row.cell_id,
            "row": int(row.row),
            "col": int(row.col),
        }
        for column in ["demand_score", "scenario_demand_score", "demand_delta", "percent_change"]:
            if hasattr(row, column):
                value = getattr(row, column)
                properties[column] = None if pd.isna(value) else round(float(value), 6)
        features.append({"type": "Feature", "properties": properties, "geometry": {"type": "Polygon", "coordinates": polygon}})
    output_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
