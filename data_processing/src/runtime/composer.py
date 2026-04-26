"""Compose backend heatmap frames from baseline, scenario state, and the demo dispersion overlay."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from src.runtime.clock import SimulationClock, SimTime
from src.runtime.demo_corridor import (
    PointKernel,
    is_demo_scenario,
    merge_demo_corridor_boost,
)
from src.runtime.overlays import LiveOverlayManager
from src.runtime.state import ScenarioStateManager
from src.runtime.stores import DemandFrameStore, FrameValues, clamp


@dataclass
class HeatmapFrame:
    timestamp: float
    state_version: str
    sim_time: SimTime
    cells: list[list[float | int]]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "state_version": self.state_version,
            "sim_time": self.sim_time.to_dict(),
            "cells": self.cells,
        }


class FrameComposer:
    """Produces complete SSE frame snapshots for the current simulation state.

    Composition order:
      1. Baseline predictions for the current sim time.
      2. Precomputed scenario deltas (scaled by `scenario_delta_multiplier`).
         When `demo_corridor_replaces_scenarios` is True and the active scenario
         is one of the demo IDs, this step is skipped so the runtime corridor
         model is the single source of truth.
      3. Live overlays (people / events drag-drops).
      4. Demo dispersion overlay (`merge_demo_corridor_boost`) - latent demand
         + per-line relief + extra-stop relief, scaled by `relief_strength`.
      5. Display gamma / floor / ceiling, or per-frame quantile normalization.
    """

    def __init__(
        self,
        *,
        baseline: DemandFrameStore,
        scenario_state: ScenarioStateManager,
        clock: SimulationClock,
        live_overlays: LiveOverlayManager | None = None,
        display_threshold: float = 0.0,
        display_floor: float = 0.05,
        display_ceiling: float = 0.78,
        display_gamma: float = 0.62,
        scenario_delta_multiplier: float = 0.0,
        per_frame_quantile_normalize: bool = False,
        demo_corridor_boost: bool = True,
        demo_corridor_relief_strength: float = 1.0,
        demo_corridor_replaces_scenarios: bool = True,
        per_frame_low_quantile: float = 0.06,
        per_frame_high_quantile: float = 0.94,
    ) -> None:
        self.baseline = baseline
        self.scenario_state = scenario_state
        self.clock = clock
        self.live_overlays = live_overlays
        self.display_threshold = display_threshold
        self.display_floor = display_floor
        self.display_ceiling = display_ceiling
        self.display_gamma = display_gamma
        self.scenario_delta_multiplier = scenario_delta_multiplier
        self.per_frame_quantile_normalize = per_frame_quantile_normalize
        self.demo_corridor_boost = demo_corridor_boost
        self.demo_corridor_relief_strength = demo_corridor_relief_strength
        self.demo_corridor_replaces_scenarios = demo_corridor_replaces_scenarios
        self.per_frame_low_quantile = per_frame_low_quantile
        self.per_frame_high_quantile = per_frame_high_quantile
        self.demo_extra_stops: list[PointKernel] = []

    def next_frame(self, *, display_scenario_id: str | None = None) -> HeatmapFrame:
        return self.compose(
            tick=self.clock.current_tick,
            sim_time=self.clock.current_time,
            display_scenario_id=display_scenario_id,
        )

    def compose(
        self,
        *,
        tick: int,
        sim_time: SimTime,
        display_scenario_id: str | None = None,
    ) -> HeatmapFrame:
        values = self.baseline.frame_for(sim_time)

        skip_scenario_state = (
            self.demo_corridor_boost
            and self.demo_corridor_replaces_scenarios
            and is_demo_scenario(display_scenario_id)
        )
        if not skip_scenario_state and self.scenario_delta_multiplier != 0.0:
            for record in self.scenario_state.active_records(tick):
                values = apply_delta(
                    values,
                    record.delta_store.frame_for(sim_time),
                    multiplier=self.scenario_delta_multiplier,
                )

        if self.live_overlays:
            values = apply_delta(values, self.live_overlays.frame_delta(sim_time))

        values = merge_demo_corridor_boost(
            values,
            self.baseline.config,
            display_scenario_id,
            enabled=self.demo_corridor_boost,
            relief_strength=self.demo_corridor_relief_strength,
            extra_stops=self.demo_extra_stops or None,
        )

        lo: float | None = None
        hi: float | None = None
        if self.per_frame_quantile_normalize and values:
            arr = np.fromiter((float(v) for v in values.values()), dtype=float, count=len(values))
            lo = float(np.quantile(arr, self.per_frame_low_quantile))
            hi = float(np.quantile(arr, self.per_frame_high_quantile))
            if hi <= lo + 1e-9:
                lo = float(arr.min())
                hi = float(arr.max())
            if hi <= lo + 1e-9:
                lo, hi = 0.0, 1.0

        cells: list[list[float | int]] = []
        for (row, col), density in sorted(values.items()):
            if lo is not None and hi is not None:
                scaled = (float(density) - lo) / (hi - lo)
                display_density = clamp(scaled) ** self.display_gamma
            else:
                display_density = self.display_density(float(density))
            if display_density > self.display_threshold:
                cells.append([row, col, round(display_density, 6)])
        return HeatmapFrame(
            timestamp=time.time(),
            state_version=self.scenario_state.current_state_version,
            sim_time=sim_time,
            cells=cells,
        )

    def display_density(self, raw_density: float) -> float:
        if self.display_ceiling <= self.display_floor:
            return clamp(raw_density)
        scaled = (raw_density - self.display_floor) / (self.display_ceiling - self.display_floor)
        return clamp(scaled) ** self.display_gamma


def apply_delta(base: FrameValues, delta: FrameValues, *, multiplier: float = 1.0) -> FrameValues:
    if not delta:
        return dict(base)

    result = dict(base)
    for cell, value in delta.items():
        result[cell] = clamp(result.get(cell, 0.0) + value * multiplier)
        if result[cell] == 0.0:
            del result[cell]
    return result
