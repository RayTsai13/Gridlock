"""GTFS helpers shared by station and heatmap pipelines."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pandas as pd

from src.common.station_utils import station_id


GTFS_TABLES = {
    "agency": "agency.txt",
    "calendar": "calendar.txt",
    "routes": "routes.txt",
    "stop_times": "stop_times.txt",
    "stops": "stops.txt",
    "trips": "trips.txt",
}


def parse_gtfs_hour(value: object) -> int | None:
    if pd.isna(value):
        return None
    try:
        hour = int(str(value).split(":", 1)[0])
    except ValueError:
        return None
    return hour % 24


def extract_gtfs_archive(zip_path: Path, destination_dir: Path) -> Path:
    """Extract a GTFS zip and normalize .csv/.txt table names to standard .txt files."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        for table, output_name in GTFS_TABLES.items():
            candidates = [
                name
                for name in names
                if Path(name).name.lower() in {f"{table}.txt", f"{table}.csv"}
                and "/.git/" not in name
            ]
            if not candidates:
                continue
            selected = sorted(candidates, key=lambda name: (name.count("/"), len(name)))[0]
            output_path = destination_dir / output_name
            with archive.open(selected) as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target)
    return destination_dir


def read_gtfs_table(gtfs_dir: Path, table: str, **kwargs) -> pd.DataFrame:
    path = gtfs_dir / GTFS_TABLES[table]
    if not path.exists():
        raise FileNotFoundError(f"Missing GTFS table: {path}")
    return pd.read_csv(path, **kwargs)


def read_stop_station_map(gtfs_dir: Path) -> pd.DataFrame:
    stops = read_gtfs_table(
        gtfs_dir,
        "stops",
        dtype={"stop_id": "string", "stop_name": "string"},
    )
    required = {"stop_id", "stop_name", "stop_lat", "stop_lon"}
    missing = required.difference(stops.columns)
    if missing:
        raise ValueError(f"GTFS stops missing required columns: {', '.join(sorted(missing))}")

    stops = stops.copy()
    stops["stop_id"] = stops["stop_id"].astype("string")
    stops["station_name"] = stops["stop_name"].astype("string").fillna("Unknown")
    stops["station_id"] = stops["station_name"].map(station_id)
    stops["lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    return stops.dropna(subset=["lat", "lon"])[["stop_id", "station_id", "station_name", "lat", "lon"]]


def build_station_hourly_frequency(gtfs_dir: Path, station_ids: list[str] | None = None) -> pd.DataFrame:
    stops = read_stop_station_map(gtfs_dir)[["stop_id", "station_id"]]
    stop_times = read_gtfs_table(
        gtfs_dir,
        "stop_times",
        usecols=["trip_id", "departure_time", "stop_id"],
        dtype={"trip_id": "string", "departure_time": "string", "stop_id": "string"},
    )
    stop_times["hour"] = stop_times["departure_time"].map(parse_gtfs_hour)
    stop_times = stop_times.dropna(subset=["hour"])
    stop_times["hour"] = stop_times["hour"].astype(int)
    joined = stop_times.merge(stops, on="stop_id", how="inner")
    grouped = (
        joined.groupby(["station_id", "hour"], as_index=False)
        .agg(scheduled_trains=("trip_id", "nunique"))
    )

    if station_ids is None:
        station_ids = sorted(grouped["station_id"].dropna().unique())
    full_index = pd.MultiIndex.from_product([station_ids, range(24)], names=["station_id", "hour"])
    result = grouped.set_index(["station_id", "hour"]).reindex(full_index, fill_value=0).reset_index()
    result["scheduled_trains"] = pd.to_numeric(result["scheduled_trains"], errors="coerce").fillna(0)
    daily = result.groupby("station_id", as_index=False)["scheduled_trains"].sum().rename(
        columns={"scheduled_trains": "daily_scheduled_trains"}
    )
    result = result.merge(daily, on="station_id", how="left")
    result["has_gtfs_frequency"] = (result["daily_scheduled_trains"] > 0).astype(int)
    return result
