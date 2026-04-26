"""FastAPI runtime for the interactive demand heatmap."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.common.artifacts import (
    DEFAULT_PROCESSED_DIR,
    DEMAND_HEATMAP_PREDICTIONS_CSV,
    PROCESSED_MODEL_OUTPUTS_DIR,
)
from src.runtime.clock import SimulationClock
from src.runtime.composer import FrameComposer
from src.runtime.state import ScenarioStateManager
from src.runtime.stores import DemandFrameStore


DATA_PROCESSING_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_CSV = (
    DATA_PROCESSING_ROOT
    / DEFAULT_PROCESSED_DIR
    / PROCESSED_MODEL_OUTPUTS_DIR
    / DEMAND_HEATMAP_PREDICTIONS_CSV
)


@dataclass
class HeatmapRuntime:
    baseline: DemandFrameStore
    clock: SimulationClock
    scenario_state: ScenarioStateManager
    composer: FrameComposer
    frame_interval_seconds: float = 1.0
    active_display_scenario_id: str = "state_baseline"

    @classmethod
    def create(
        cls,
        *,
        baseline_csv: Path = DEFAULT_BASELINE_CSV,
        sim_step_seconds: int = 30,
        time_bin_minutes: int = 30,
        frame_interval_seconds: float = 1.0,
        display_threshold: float = 0.0,
        display_floor: float = 0.13,
        display_ceiling: float = 0.75,
        display_gamma: float = 0.75,
    ) -> "HeatmapRuntime":
        baseline = DemandFrameStore.from_predictions_csv(baseline_csv)
        clock = SimulationClock(
            sim_step_seconds=sim_step_seconds,
            time_bin_minutes=time_bin_minutes,
        )
        scenario_state = ScenarioStateManager()
        composer = FrameComposer(
            baseline=baseline,
            scenario_state=scenario_state,
            clock=clock,
            display_threshold=display_threshold,
            display_floor=display_floor,
            display_ceiling=display_ceiling,
            display_gamma=display_gamma,
        )
        return cls(
            baseline=baseline,
            clock=clock,
            scenario_state=scenario_state,
            composer=composer,
            frame_interval_seconds=frame_interval_seconds,
        )


def create_app(
    *,
    baseline_csv: Path = DEFAULT_BASELINE_CSV,
    sim_step_seconds: int = 30,
    time_bin_minutes: int = 30,
    frame_interval_seconds: float = 1.0,
    display_threshold: float = 0.0,
    display_floor: float = 0.13,
    display_ceiling: float = 0.75,
    display_gamma: float = 0.75,
) -> FastAPI:
    runtime = HeatmapRuntime.create(
        baseline_csv=baseline_csv,
        sim_step_seconds=sim_step_seconds,
        time_bin_minutes=time_bin_minutes,
        frame_interval_seconds=frame_interval_seconds,
        display_threshold=display_threshold,
        display_floor=display_floor,
        display_ceiling=display_ceiling,
        display_gamma=display_gamma,
    )
    app = FastAPI(title="Demand Heatmap Runtime")
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/heatmap/stream")
    async def stream(request: Request):
        return StreamingResponse(
            stream_frames(request, runtime),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/states/current")
    async def current_state():
        state = runtime.scenario_state.to_dict(
            current_tick=runtime.clock.current_tick,
            current_sim_time=runtime.clock.current_time,
        )
        state["active_display_scenario_id"] = runtime.active_display_scenario_id
        return state

    @app.get("/api/debug/frame")
    async def debug_frame():
        frame = runtime.composer.compose(
            tick=runtime.clock.current_tick,
            sim_time=runtime.clock.current_time,
        )
        densities = [float(cell[2]) for cell in frame.cells]
        return {
            "frame": frame.to_dict(),
            "geojson": frame_to_geojson(frame.cells, runtime.baseline.config),
            "summary": {
                "cell_count": len(frame.cells),
                "min_density": min(densities) if densities else 0.0,
                "max_density": max(densities) if densities else 0.0,
                "avg_density": sum(densities) / len(densities) if densities else 0.0,
                "grid": runtime.baseline.config.to_sse_config(),
                "value_column": runtime.baseline.value_column,
                "display_floor": runtime.composer.display_floor,
                "display_ceiling": runtime.composer.display_ceiling,
                "display_gamma": runtime.composer.display_gamma,
            },
        }

    @app.post("/api/scenario")
    async def set_display_scenario(payload: dict[str, Any]):
        """Compatibility endpoint for the current frontend deployment controls.

        This only records the scenario id used by the UI. Demand-changing
        scenarios still go through `POST /api/scenarios` with a precomputed
        delta CSV.
        """
        scenario_id = payload.get("scenario_id")
        if not scenario_id:
            raise HTTPException(status_code=400, detail="Scenario payload missing scenario_id.")
        runtime.active_display_scenario_id = str(scenario_id)
        return {"scenario_id": runtime.active_display_scenario_id}

    @app.post("/api/scenarios")
    async def create_scenario(payload: dict[str, Any]):
        if payload.get("type", "precomputed_delta") != "precomputed_delta":
            raise HTTPException(
                status_code=400,
                detail="Runtime API currently accepts precomputed_delta scenarios.",
            )
        if "delta_csv" not in payload:
            raise HTTPException(status_code=400, detail="Scenario payload missing delta_csv.")

        try:
            delta_csv = resolve_path(payload["delta_csv"])
            effective_from_tick = payload.get("effective_from_tick")
            record = runtime.scenario_state.register_precomputed_delta(
                payload=payload,
                delta_csv=delta_csv,
                current_tick=runtime.clock.current_tick,
                current_sim_time=runtime.clock.current_time,
                effective_from_tick=None if effective_from_tick is None else int(effective_from_tick),
                effective_from_sim_time=runtime.clock.current_time,
            )
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return record.to_dict()

    @app.get("/api/scenarios/{scenario_id}/status")
    async def scenario_status(scenario_id: str):
        record = runtime.scenario_state.get_scenario(scenario_id)
        if not record:
            raise HTTPException(status_code=404, detail="Scenario not found.")
        return record.to_dict()

    @app.get("/api/states/{state_version}/deltas")
    async def state_delta_summary(state_version: str):
        record = runtime.scenario_state.get_state_delta(state_version)
        if not record:
            raise HTTPException(status_code=404, detail="State version not found.")
        return record.to_dict()

    return app


async def stream_frames(request: Request, runtime: HeatmapRuntime):
    event_id = 0
    yield sse_event(event_id, "config", runtime.baseline.config.to_sse_config())
    event_id += 1
    sent_display_scenario_id: str | None = None

    try:
        while True:
            if await request.is_disconnected():
                break
            if sent_display_scenario_id != runtime.active_display_scenario_id:
                sent_display_scenario_id = runtime.active_display_scenario_id
                yield sse_event(event_id, "scenario", {"scenario_id": sent_display_scenario_id})
                event_id += 1
            frame = runtime.composer.next_frame()
            yield sse_event(event_id, "frame", frame.to_dict())
            event_id += 1
            await asyncio.sleep(runtime.frame_interval_seconds)
    except asyncio.CancelledError:
        return


def sse_event(event_id: int, event: str, payload: dict) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(payload)}\n\n"


def frame_to_geojson(cells: list[list[float | int]], config) -> dict:
    cell_width = (config.east - config.west) / config.cols
    cell_height = (config.north - config.south) / config.rows
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        config.west + (int(col) + 0.5) * cell_width,
                        config.north - (int(row) + 0.5) * cell_height,
                    ],
                },
                "properties": {"density": float(density), "row": int(row), "col": int(col)},
            }
            for row, col, density in cells
        ],
    }


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path
