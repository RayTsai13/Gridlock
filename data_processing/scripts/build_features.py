#!/usr/bin/env python3
"""Build the processed feature artifacts used by station and heatmap models."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Delhi and Seattle feature artifacts.")
    parser.add_argument("--raw-dir", default="curr_data/raw")
    parser.add_argument("--processed-dir", default="curr_data/processed")
    parser.add_argument("--gtfs-dir", default="gtfs", help="Raw Puget Sound GTFS directory.")
    parser.add_argument(
        "--station-gtfs-dir",
        default="gtfs_stations",
        help="Cleaned station-only GTFS directory to write and consume.",
    )
    parser.add_argument("--delhi-gtfs-dir", default="gtfs_delhi")
    parser.add_argument("--route-types", default="0,1,2")
    parser.add_argument("--agency-ids", default="40", help="Sound Transit agency_id by default.")
    parser.add_argument("--radius-m", type=int, default=1000)
    parser.add_argument("--cell-size-m", type=int, default=500)
    parser.add_argument("--fremont-limit", type=int, default=5000)
    parser.add_argument("--skip-download", action="store_true", help="Do not refresh raw data first.")
    parser.add_argument("--skip-seattle-heatmap", action="store_true")
    return parser.parse_args()


def run(command: list[str]) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}", flush=True)
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def py(*args: str) -> list[str]:
    return [sys.executable, *args]


def main() -> None:
    args = parse_args()
    raw_dir = args.raw_dir
    processed_dir = args.processed_dir

    if not args.skip_download:
        run(py("scripts/download_raw_data.py", "--raw-dir", raw_dir, "--gtfs-dir", args.gtfs_dir))

    run(
        py(
            "scripts/filter_gtfs_station_data.py",
            "--input-gtfs-dir",
            args.gtfs_dir,
            "--output-gtfs-dir",
            args.station_gtfs_dir,
            "--route-types",
            args.route_types,
            "--agency-ids",
            args.agency_ids,
        )
    )

    run(
        py(
            "-m",
            "src.pipelines.delhi.build_population_vectors",
            "--raw-dir",
            raw_dir,
            "--out-dir",
            processed_dir,
            "--radius-m",
            str(args.radius_m),
        )
    )
    run(
        py(
            "-m",
            "src.pipelines.delhi.transform_metro",
            "--input",
            f"{raw_dir}/delhi_metro_updated.csv",
            "--out-dir",
            processed_dir,
            "--density-vectors",
            f"{processed_dir}/delhi_station_density.csv",
        )
    )
    run(
        py(
            "-m",
            "src.pipelines.delhi.prepare_train_test",
            "--features-csv",
            f"{processed_dir}/delhi_trip_features.csv",
            "--out-dir",
            processed_dir,
        )
    )
    run(
        py(
            "-m",
            "src.pipelines.delhi.build_gtfs_frequency",
            "--gtfs-dir",
            args.delhi_gtfs_dir,
            "--station-vectors",
            f"{processed_dir}/delhi_station_vectors.csv",
            "--out-dir",
            processed_dir,
            "--route-types",
            args.route_types,
        )
    )
    run(
        py(
            "-m",
            "src.pipelines.delhi.build_heatmap_training_dataset",
            "--trip-features",
            f"{processed_dir}/delhi_trip_features.csv",
            "--station-vectors",
            f"{processed_dir}/delhi_station_vectors.csv",
            "--frequency-csv",
            f"{processed_dir}/delhi_station_gtfs_frequency.csv",
            "--out-dir",
            processed_dir,
        )
    )

    run(
        py(
            "-m",
            "src.pipelines.seattle.build_station_vectors",
            "--gtfs-dir",
            args.station_gtfs_dir,
            "--raw-dir",
            raw_dir,
            "--out-dir",
            processed_dir,
            "--radius-m",
            str(args.radius_m),
            "--route-types",
            args.route_types,
            "--agency-ids",
            args.agency_ids,
        )
    )

    if not args.skip_seattle_heatmap:
        run(
            py(
                "-m",
                "src.pipelines.seattle.build_heatmap_dataset",
                "--gtfs-dir",
                args.station_gtfs_dir,
                "--raw-dir",
                raw_dir,
                "--out-dir",
                processed_dir,
                "--cell-size-m",
                str(args.cell_size_m),
                "--fremont-limit",
                str(args.fremont_limit),
                "--route-types",
                args.route_types,
                "--agency-ids",
                args.agency_ids,
            )
        )

    run(
        py(
            "-m",
            "src.pipelines.common.build_heatmap_candidates",
            "--station-vectors",
            f"{processed_dir}/seattle_station_vectors.csv",
            "--gtfs-dir",
            args.station_gtfs_dir,
            "--out-dir",
            processed_dir,
            "--cell-size-m",
            str(args.cell_size_m),
            "--route-types",
            args.route_types,
            "--agency-ids",
            args.agency_ids,
        )
    )


if __name__ == "__main__":
    main()
