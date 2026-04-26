#!/usr/bin/env python3
"""Run the interactive demand heatmap runtime API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.runtime.api import DEFAULT_BASELINE_CSV, create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve composed demand heatmap frames.")
    parser.add_argument("--baseline-csv", default=str(DEFAULT_BASELINE_CSV))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sim-step-seconds", type=int, default=30)
    parser.add_argument("--time-bin-minutes", type=int, default=30)
    parser.add_argument("--frame-interval-seconds", type=float, default=1.0)
    parser.add_argument("--display-threshold", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app(
        baseline_csv=Path(args.baseline_csv),
        sim_step_seconds=args.sim_step_seconds,
        time_bin_minutes=args.time_bin_minutes,
        frame_interval_seconds=args.frame_interval_seconds,
        display_threshold=args.display_threshold,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
