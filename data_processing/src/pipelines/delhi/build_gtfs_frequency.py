#!/usr/bin/env python3
"""Build Delhi station-hour train frequency features from GTFS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.common.artifacts import (
    DEFAULT_PROCESSED_DIR,
    DELHI_GTFS_DIR,
    DELHI_STATION_GTFS_FREQUENCY_CSV,
    DELHI_STATION_VECTORS_CSV,
)
from src.common.gtfs_utils import (
    DEFAULT_STATION_ROUTE_TYPES,
    build_station_hourly_frequency,
    parse_agency_ids,
    parse_route_types,
    read_stop_station_map,
)
from src.common.io_utils import ensure_dir, write_csv
from src.common.station_utils import match_station_name, station_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Delhi GTFS station-hour frequency features.")
    parser.add_argument("--gtfs-dir", default=DELHI_GTFS_DIR, help="Directory containing Delhi GTFS txt files.")
    parser.add_argument(
        "--station-vectors",
        default=str(DEFAULT_PROCESSED_DIR / DELHI_STATION_VECTORS_CSV),
        help="Delhi station vectors used as the canonical station universe.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_PROCESSED_DIR), help="Output directory.")
    parser.add_argument(
        "--route-types",
        default=",".join(str(route_type) for route_type in DEFAULT_STATION_ROUTE_TYPES),
        help="Comma-separated GTFS route_type values to keep. Default keeps rail/station modes: 0,1,2.",
    )
    parser.add_argument(
        "--agency-ids",
        default="",
        help="Optional comma-separated GTFS agency_id values to keep. Default keeps all agencies.",
    )
    return parser.parse_args()


def station_name_lookup(
    vectors: pd.DataFrame,
    gtfs_dir: Path,
    route_types: tuple[int, ...] | None,
    agency_ids: tuple[str, ...] | None,
) -> pd.DataFrame:
    gtfs_stops = read_stop_station_map(gtfs_dir, route_types=route_types, agency_ids=agency_ids)
    canonical_names = vectors["station_name"].dropna().astype(str).tolist()
    matched = []
    for stop in gtfs_stops.itertuples(index=False):
        match = match_station_name(stop.station_name, canonical_names, cutoff=0.8)
        matched.append(
            {
                "gtfs_station_id": stop.station_id,
                "station_id": station_id(match) if match else stop.station_id,
                "matched_station_name": match,
            }
        )
    return pd.DataFrame(matched).drop_duplicates("gtfs_station_id")


def main() -> None:
    args = parse_args()
    gtfs_dir = Path(args.gtfs_dir)
    out_dir = ensure_dir(Path(args.out_dir))
    vectors = pd.read_csv(args.station_vectors)
    route_types = parse_route_types(args.route_types)
    agency_ids = parse_agency_ids(args.agency_ids)

    if not all((gtfs_dir / name).exists() for name in ["stops.txt", "stop_times.txt", "trips.txt"]):
        station_ids = sorted(vectors["station_id"].dropna().astype(str).unique())
        full_index = pd.MultiIndex.from_product([station_ids, range(24)], names=["station_id", "hour"])
        frequency = full_index.to_frame(index=False)
        frequency["scheduled_trains"] = 0
        frequency["daily_scheduled_trains"] = 0
        frequency["has_gtfs_frequency"] = 0
        output_path = write_csv(frequency, out_dir / DELHI_STATION_GTFS_FREQUENCY_CSV)
        print(
            json.dumps(
                {
                    "gtfs_available": False,
                    "route_types": list(route_types) if route_types is not None else "all",
                    "agency_ids": list(agency_ids) if agency_ids is not None else "all",
                    "output": str(output_path),
                },
                indent=2,
            )
        )
        return

    raw_frequency = build_station_hourly_frequency(
        gtfs_dir, route_types=route_types, agency_ids=agency_ids
    )
    lookup = station_name_lookup(vectors, gtfs_dir, route_types, agency_ids)
    frequency = raw_frequency.merge(
        lookup[["gtfs_station_id", "station_id"]],
        left_on="station_id",
        right_on="gtfs_station_id",
        how="left",
        suffixes=("_gtfs", ""),
    )
    frequency["station_id"] = frequency["station_id"].fillna(frequency["station_id_gtfs"])
    frequency = (
        frequency.groupby(["station_id", "hour"], as_index=False)
        .agg(scheduled_trains=("scheduled_trains", "sum"))
    )

    station_ids = sorted(vectors["station_id"].dropna().astype(str).unique())
    full_index = pd.MultiIndex.from_product([station_ids, range(24)], names=["station_id", "hour"])
    frequency = frequency.set_index(["station_id", "hour"]).reindex(full_index, fill_value=0).reset_index()
    daily = frequency.groupby("station_id", as_index=False)["scheduled_trains"].sum().rename(
        columns={"scheduled_trains": "daily_scheduled_trains"}
    )
    frequency = frequency.merge(daily, on="station_id", how="left")
    frequency["has_gtfs_frequency"] = (frequency["daily_scheduled_trains"] > 0).astype(int)
    output_path = write_csv(frequency, out_dir / DELHI_STATION_GTFS_FREQUENCY_CSV)
    print(
        json.dumps(
            {
                "gtfs_available": True,
                "stations_with_frequency": int((daily["daily_scheduled_trains"] > 0).sum()),
                "route_types": list(route_types) if route_types is not None else "all",
                "agency_ids": list(agency_ids) if agency_ids is not None else "all",
                "output": str(output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
