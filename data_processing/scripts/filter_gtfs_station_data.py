#!/usr/bin/env python3
"""Write a station-only GTFS subset by filtering route types."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.common.gtfs_utils import (  # noqa: E402
    DEFAULT_SEATTLE_STATION_AGENCY_IDS,
    DEFAULT_STATION_ROUTE_TYPES,
    parse_agency_ids,
    parse_route_types,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a filtered GTFS directory for rail/station modes.")
    parser.add_argument("--input-gtfs-dir", default="gtfs", help="Source GTFS directory.")
    parser.add_argument("--output-gtfs-dir", default="gtfs_stations", help="Filtered output GTFS directory.")
    parser.add_argument(
        "--route-types",
        default=",".join(str(route_type) for route_type in DEFAULT_STATION_ROUTE_TYPES),
        help="Comma-separated GTFS route_type values to keep. Default keeps rail/station modes: 0,1,2.",
    )
    parser.add_argument(
        "--agency-ids",
        default=",".join(DEFAULT_SEATTLE_STATION_AGENCY_IDS),
        help="Comma-separated GTFS agency_id values to keep. Default keeps Sound Transit: 40.",
    )
    return parser.parse_args()


def read_table(gtfs_dir: Path, name: str, **kwargs) -> pd.DataFrame:
    path = gtfs_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Missing GTFS table: {path}")
    return pd.read_csv(path, **kwargs)


def write_table(df: pd.DataFrame, output_dir: Path, name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / name, index=False)


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_gtfs_dir)
    output_dir = Path(args.output_gtfs_dir)
    route_types = parse_route_types(args.route_types)
    agency_ids = parse_agency_ids(args.agency_ids)
    if route_types is None:
        raise ValueError("--route-types must include at least one route_type")

    routes = read_table(input_dir, "routes.txt", dtype={"route_id": "string", "route_type": "Int64"})
    routes = routes[routes["route_type"].isin(route_types)].copy()
    if agency_ids is not None:
        routes["agency_id"] = routes["agency_id"].astype("string")
        routes = routes[routes["agency_id"].isin(agency_ids)].copy()
    route_ids = set(routes["route_id"].astype("string").dropna())

    trips = read_table(input_dir, "trips.txt", dtype={"route_id": "string", "trip_id": "string"})
    trips = trips[trips["route_id"].isin(route_ids)].copy()
    trip_ids = set(trips["trip_id"].astype("string").dropna())

    stop_times = read_table(
        input_dir,
        "stop_times.txt",
        dtype={"trip_id": "string", "stop_id": "string"},
        low_memory=False,
    )
    stop_times = stop_times[stop_times["trip_id"].isin(trip_ids)].copy()
    stop_ids = set(stop_times["stop_id"].astype("string").dropna())

    stops = read_table(input_dir, "stops.txt", dtype={"stop_id": "string"})
    stops = stops[stops["stop_id"].isin(stop_ids)].copy()

    write_table(routes, output_dir, "routes.txt")
    write_table(trips, output_dir, "trips.txt")
    write_table(stop_times, output_dir, "stop_times.txt")
    write_table(stops, output_dir, "stops.txt")

    for optional in ["agency.txt", "calendar.txt", "calendar_dates.txt", "feed_info.txt"]:
        path = input_dir / optional
        if path.exists():
            table = pd.read_csv(path)
            if optional == "agency.txt" and agency_ids is not None:
                table["agency_id"] = table["agency_id"].astype("string")
                table = table[table["agency_id"].isin(agency_ids)]
            write_table(table, output_dir, optional)

    print(
        json.dumps(
            {
                "input": str(input_dir),
                "output": str(output_dir),
                "route_types": list(route_types),
                "agency_ids": list(agency_ids) if agency_ids is not None else "all",
                "routes": int(len(routes)),
                "trips": int(len(trips)),
                "stop_times": int(len(stop_times)),
                "stops": int(len(stops)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
