#!/usr/bin/env python3
"""Build precomputed scenario deltas for the runtime (East Link + Ballard capstone).

Produces:
  curr_data/processed/scenarios/line-1-2/demand_heatmap_scenario_predictions.csv
  curr_data/processed/scenarios/line-1-2-ballard/demand_heatmap_scenario_predictions.csv
    where the Ballard file uses incremental deltas vs the East-Link-only scenario (stacks in the UI).

Requires baseline features and city_heatmap_candidate_features.csv from scripts/build_features.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]


def json_summary(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2)


def py(*parts: str) -> list[str]:
    return [sys.executable, *parts]


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT_DIR, check=True)


def capstone_frequency_rows(station_ids: list[str], trains_per_hour: int = 8, bin_minutes: int = 30) -> pd.DataFrame:
    rows: list[dict] = []
    for station_id in station_ids:
        for hour in (8,):
            base = hour * 60
            for offset in range(0, 60, bin_minutes):
                rows.append(
                    {
                        "station_id": station_id,
                        "time_bin": base + offset,
                        "hour": hour,
                        "minute": offset,
                        "scheduled_trains_delta": trains_per_hour / (60 / bin_minutes),
                    }
                )
    return pd.DataFrame(rows)


def incremental_ballard_deltas(line2_path: Path, capstone_path: Path, out_path: Path) -> None:
    """Rewrite demand_delta so runtime stacking matches (capstone - line2_only)."""
    left = pd.read_csv(line2_path)
    right = pd.read_csv(capstone_path)
    keys = ["cell_id", "day_of_week", "time_bin"]
    raw2 = left.rename(columns={"scenario_demand_pressure_raw": "raw_line2"})[keys + ["raw_line2"]]
    raw3 = right.rename(columns={"scenario_demand_pressure_raw": "raw_capstone"})[keys + ["raw_capstone"]]
    merged = raw3.merge(raw2, on=keys, how="left")
    merged["raw_line2"] = merged["raw_line2"].fillna(0.0)
    merged["demand_delta_incr"] = merged["raw_capstone"] - merged["raw_line2"]
    patch = merged[keys + ["demand_delta_incr"]]
    out = right.merge(patch, on=keys, how="left")
    out["demand_delta"] = out["demand_delta_incr"]
    out = out.drop(columns=["demand_delta_incr"])
    base_raw = pd.to_numeric(out["baseline_demand_pressure_raw"], errors="coerce").fillna(0.0)
    denom = base_raw.replace(0, pd.NA)
    out["percent_change"] = (out["demand_delta"] / denom * 100).replace([float("inf"), float("-inf")], pd.NA).fillna(0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(json_summary({"incremental_ballard": str(out_path), "rows": int(len(out))}))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build hackathon Line 2 + Ballard scenario prediction CSVs.")
    p.add_argument("--processed-dir", default="curr_data/processed")
    p.add_argument("--features-dir", default="curr_data/processed/features")
    p.add_argument("--station-gtfs-dir", default="gtfs_stations")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    processed = Path(args.processed_dir)
    features = Path(args.features_dir)
    city_candidates = features / "city_heatmap_candidate_features.csv"
    if not city_candidates.exists():
        raise SystemExit(f"Missing {city_candidates}; run scripts/build_features.py first.")

    line2_dir = processed / "scenarios" / "line-1-2"
    cap_wip = processed / "scenarios" / "_hackathon_capstone_wip"
    ballard_dir = processed / "scenarios" / "line-1-2-ballard"
    line2_dir.mkdir(parents=True, exist_ok=True)
    cap_wip.mkdir(parents=True, exist_ok=True)
    ballard_dir.mkdir(parents=True, exist_ok=True)

    run(
        py(
            "scripts/build_line_weights.py",
            "--line-stations-csv",
            "examples/scenarios/line_2_stations.csv",
            "--candidate-features",
            str(city_candidates),
            "--line-id",
            "line_2_east",
            "--out-dir",
            str(line2_dir),
        )
    )

    run(
        py(
            "-m",
            "src.models.train_demand_heatmap_model",
            "--training-features",
            str(features / "delhi_heatmap_training_features.csv"),
            "--candidate-features",
            str(city_candidates),
            "--scenario-features",
            str(line2_dir / "proposed_line_candidate_features.csv"),
            "--out-dir",
            str(line2_dir),
            "--demo-hackathon-transit-effects",
        )
    )

    cap_added = cap_wip / "hackathon_capstone_added_stations.csv"
    cap_freq = cap_wip / "hackathon_capstone_frequency_delta.csv"
    line2_stations = pd.read_csv(ROOT_DIR / "examples/scenarios/line_2_stations.csv")
    ballard_stations = pd.read_csv(ROOT_DIR / "examples/scenarios/ballard_line_stations.csv")
    merged_stations = pd.concat([line2_stations, ballard_stations], ignore_index=True)
    merged_stations.to_csv(cap_added, index=False)
    station_ids = merged_stations["station_id"].astype(str).tolist()
    capstone_frequency_rows(station_ids).to_csv(cap_freq, index=False)

    run(
        py(
            "-m",
            "src.pipelines.common.build_heatmap_candidates",
            "--station-vectors",
            str(features / "seattle_station_vectors.csv"),
            "--gtfs-dir",
            args.station_gtfs_dir,
            "--out-dir",
            str(cap_wip),
            "--output-name",
            "city_hackathon_capstone_candidates.csv",
            "--cell-size-m",
            "500",
            "--time-bin-minutes",
            "30",
            "--bbox=-122.4597,47.4810,-122.2244,47.7340",
            "--office-features-csv",
            str(features / "seattle_heatmap_features.csv"),
            "--added-stations-csv",
            str(cap_added),
            "--frequency-delta-csv",
            str(cap_freq),
            "--ballard-corridor-density-proxy",
        )
    )

    capstone_csv = cap_wip / "city_hackathon_capstone_candidates.csv"
    run(
        py(
            "-m",
            "src.models.train_demand_heatmap_model",
            "--training-features",
            str(features / "delhi_heatmap_training_features.csv"),
            "--candidate-features",
            str(city_candidates),
            "--scenario-features",
            str(capstone_csv),
            "--out-dir",
            str(cap_wip),
            "--demo-hackathon-transit-effects",
        )
    )

    cumulative_path = cap_wip / "demand_heatmap_scenario_predictions.csv"
    line2_pred = line2_dir / "demand_heatmap_scenario_predictions.csv"
    ballard_out = ballard_dir / "demand_heatmap_scenario_predictions.csv"
    incremental_ballard_deltas(line2_pred, cumulative_path, ballard_out)
    print(json_summary({"line_2": str(line2_pred), "line_2_ballard_incremental": str(ballard_out)}))


if __name__ == "__main__":
    main()
