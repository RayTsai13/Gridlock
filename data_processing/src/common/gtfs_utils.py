"""GTFS helpers shared by station and heatmap pipelines."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pandas as pd

from src.common.station_utils import station_id


DEFAULT_STATION_ROUTE_TYPES = (0, 1, 2)
DEFAULT_SEATTLE_STATION_AGENCY_IDS = ("40",)

GTFS_TABLES = {
    "agency": "agency.txt",
    "calendar": "calendar.txt",
    "routes": "routes.txt",
    "stop_times": "stop_times.txt",
    "stops": "stops.txt",
    "trips": "trips.txt",
}


def parse_route_types(value: str | None) -> tuple[int, ...] | None:
    if value is None or value.strip() == "":
        return None
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def parse_agency_ids(value: str | None) -> tuple[str, ...] | None:
    if value is None or value.strip() == "":
        return None
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_gtfs_hour(value: object) -> int | None:
    if pd.isna(value):
        return None
    try:
        hour = int(str(value).split(":", 1)[0])
    except ValueError:
        return None
    return hour % 24


def parse_gtfs_minute_of_day(value: object) -> int | None:
    if pd.isna(value):
        return None
    parts = str(value).split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0]) % 24
        minute = int(parts[1])
    except ValueError:
        return None
    if minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def time_bin_for_minute(minute_of_day: int, bin_minutes: int) -> int:
    return int(minute_of_day // bin_minutes * bin_minutes)


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


def filtered_trip_ids(
    gtfs_dir: Path,
    route_types: tuple[int, ...] | None,
    agency_ids: tuple[str, ...] | None = None,
) -> set[str] | None:
    if route_types is None and agency_ids is None:
        return None

    routes = read_gtfs_table(
        gtfs_dir,
        "routes",
        usecols=["agency_id", "route_id", "route_type"],
        dtype={"agency_id": "string", "route_id": "string", "route_type": "Int64"},
    )
    route_mask = pd.Series(True, index=routes.index)
    if route_types is not None:
        route_mask &= routes["route_type"].isin(route_types)
    if agency_ids is not None:
        route_mask &= routes["agency_id"].isin(agency_ids)
    route_ids = set(routes.loc[route_mask, "route_id"].astype("string").dropna())
    trips = read_gtfs_table(
        gtfs_dir,
        "trips",
        usecols=["route_id", "trip_id"],
        dtype={"route_id": "string", "trip_id": "string"},
    )
    return set(trips.loc[trips["route_id"].isin(route_ids), "trip_id"].astype("string").dropna())


def filtered_stop_ids(
    gtfs_dir: Path,
    route_types: tuple[int, ...] | None,
    agency_ids: tuple[str, ...] | None = None,
) -> set[str] | None:
    trip_ids = filtered_trip_ids(gtfs_dir, route_types, agency_ids=agency_ids)
    if trip_ids is None:
        return None
    if not trip_ids:
        return set()
    stop_times = read_gtfs_table(
        gtfs_dir,
        "stop_times",
        usecols=["trip_id", "stop_id"],
        dtype={"trip_id": "string", "stop_id": "string"},
    )
    return set(stop_times.loc[stop_times["trip_id"].isin(trip_ids), "stop_id"].astype("string").dropna())


def read_stop_station_map(
    gtfs_dir: Path,
    route_types: tuple[int, ...] | None = None,
    agency_ids: tuple[str, ...] | None = None,
) -> pd.DataFrame:
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
    stop_ids = filtered_stop_ids(gtfs_dir, route_types, agency_ids=agency_ids)
    if stop_ids is not None:
        stops = stops[stops["stop_id"].isin(stop_ids)]
    return stops.dropna(subset=["lat", "lon"])[["stop_id", "station_id", "station_name", "lat", "lon"]]


def build_station_hourly_frequency(
    gtfs_dir: Path,
    station_ids: list[str] | None = None,
    route_types: tuple[int, ...] | None = None,
    agency_ids: tuple[str, ...] | None = None,
    bin_minutes: int = 60,
) -> pd.DataFrame:
    if 1440 % bin_minutes != 0:
        raise ValueError("bin_minutes must divide evenly into 1440")
    stops = read_stop_station_map(gtfs_dir, route_types=route_types, agency_ids=agency_ids)[
        ["stop_id", "station_id"]
    ]
    stop_times = read_gtfs_table(
        gtfs_dir,
        "stop_times",
        usecols=["trip_id", "departure_time", "stop_id"],
        dtype={"trip_id": "string", "departure_time": "string", "stop_id": "string"},
    )
    trip_ids = filtered_trip_ids(gtfs_dir, route_types, agency_ids=agency_ids)
    if trip_ids is not None:
        stop_times = stop_times[stop_times["trip_id"].isin(trip_ids)]
    stop_times["minute_of_day"] = stop_times["departure_time"].map(parse_gtfs_minute_of_day)
    stop_times = stop_times.dropna(subset=["minute_of_day"])
    stop_times["minute_of_day"] = stop_times["minute_of_day"].astype(int)
    stop_times["time_bin"] = stop_times["minute_of_day"].map(lambda value: time_bin_for_minute(value, bin_minutes))
    stop_times["hour"] = (stop_times["time_bin"] // 60).astype(int)
    stop_times["minute"] = (stop_times["time_bin"] % 60).astype(int)
    joined = stop_times.merge(stops, on="stop_id", how="inner")
    grouped = (
        joined.groupby(["station_id", "time_bin"], as_index=False)
        .agg(scheduled_trains=("trip_id", "nunique"))
    )

    if station_ids is None:
        station_ids = sorted(grouped["station_id"].dropna().unique())
    bins = list(range(0, 1440, bin_minutes))
    full_index = pd.MultiIndex.from_product([station_ids, bins], names=["station_id", "time_bin"])
    result = grouped.set_index(["station_id", "time_bin"]).reindex(full_index, fill_value=0).reset_index()
    result["hour"] = (result["time_bin"] // 60).astype(int)
    result["minute"] = (result["time_bin"] % 60).astype(int)
    result["scheduled_trains"] = pd.to_numeric(result["scheduled_trains"], errors="coerce").fillna(0)
    daily = result.groupby("station_id", as_index=False)["scheduled_trains"].sum().rename(
        columns={"scheduled_trains": "daily_scheduled_trains"}
    )
    result = result.merge(daily, on="station_id", how="left")
    result["has_gtfs_frequency"] = (result["daily_scheduled_trains"] > 0).astype(int)
    return result
