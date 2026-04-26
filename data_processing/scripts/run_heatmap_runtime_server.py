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
    parser.add_argument("--sim-step-seconds", type=int, default=1800)
    parser.add_argument("--time-bin-minutes", type=int, default=30)
    parser.add_argument("--frame-interval-seconds", type=float, default=1.0)
    parser.add_argument("--display-threshold", type=float, default=0.0)
    parser.add_argument("--display-floor", type=float, default=0.05)
    parser.add_argument("--display-ceiling", type=float, default=0.78)
    parser.add_argument("--display-gamma", type=float, default=0.62)
    parser.add_argument(
        "--scenario-delta-multiplier",
        type=float,
        default=0.0,
        help=(
            "Multiplier on precomputed scenario deltas. Defaults to 0.0 because the runtime demo "
            "corridor model fully drives line cause/effect. Bump above 0 to layer the trained deltas."
        ),
    )
    parser.add_argument(
        "--per-frame-quantile-normalize",
        action="store_true",
        help="Stretch each frame to 6th-94th percentile (off by default; absolute reductions show clearly).",
    )
    parser.add_argument(
        "--no-demo-corridor-boost",
        action="store_true",
        help="Disable runtime latent-demand and per-line relief overlay (revert to precomputed predictions only).",
    )
    parser.add_argument(
        "--no-demo-corridor-replaces-scenarios",
        action="store_true",
        help="Apply precomputed scenario_state deltas alongside the demo corridor instead of replacing them.",
    )
    parser.add_argument(
        "--demo-corridor-relief-strength",
        type=float,
        default=1.0,
        help="Initial relief multiplier (live POST /api/demo/relief while running).",
    )
    parser.add_argument(
        "--shutdown-timeout-seconds",
        type=int,
        default=2,
        help="Maximum time Uvicorn waits for open SSE connections to close.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app(
        baseline_csv=Path(args.baseline_csv),
        sim_step_seconds=args.sim_step_seconds,
        time_bin_minutes=args.time_bin_minutes,
        frame_interval_seconds=args.frame_interval_seconds,
        display_threshold=args.display_threshold,
        display_floor=args.display_floor,
        display_ceiling=args.display_ceiling,
        display_gamma=args.display_gamma,
        scenario_delta_multiplier=args.scenario_delta_multiplier,
        per_frame_quantile_normalize=args.per_frame_quantile_normalize,
        demo_corridor_boost=not args.no_demo_corridor_boost,
        demo_corridor_relief_strength=args.demo_corridor_relief_strength,
        demo_corridor_replaces_scenarios=not args.no_demo_corridor_replaces_scenarios,
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        timeout_graceful_shutdown=args.shutdown_timeout_seconds,
    )


if __name__ == "__main__":
    main()
