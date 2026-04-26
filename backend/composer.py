"""Frame composition for the deterministic demand-pressure simulation."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .geo import clamp
from .network import NetworkInfluence
from .overlays import LiveOverlayManager
from .seeds import SeedField
from .sim_time import SimTime


@dataclass
class HeatmapFrame:
    timestamp: float
    state_version: str
    sim_time: SimTime
    cells: list[list[int | float]]

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "state_version": self.state_version,
            "sim_time": self.sim_time.to_dict(),
            "cells": self.cells,
        }


class FrameComposer:
    def __init__(
        self,
        *,
        seed_field: SeedField,
        display_threshold: float = 0.012,
        display_gamma: float = 0.72,
    ) -> None:
        self.seed_field = seed_field
        self.display_threshold = display_threshold
        self.display_gamma = display_gamma

    def compose(
        self,
        *,
        sim_time: SimTime,
        state_version: str,
        network_influence: NetworkInfluence,
        overlays: LiveOverlayManager,
    ) -> HeatmapFrame:
        base_values = self.seed_field.values_for(sim_time)
        overlay_values = overlays.values_for(sim_time, network_influence)
        combined = [
            max(0.0, base_value + overlay_value)
            for base_value, overlay_value in zip(base_values, overlay_values)
        ]
        network_values = network_influence.apply(combined)
        cells = self._to_sparse_cells(
            network_values,
            display_scale=network_influence.display_scale,
        )
        return HeatmapFrame(
            timestamp=time.time(),
            state_version=state_version,
            sim_time=sim_time,
            cells=cells,
        )

    def _to_sparse_cells(
        self,
        raw_values: list[float],
        *,
        display_scale: float = 1.0,
    ) -> list[list[int | float]]:
        display_values = normalize_display_values(
            raw_values,
            gamma=self.display_gamma,
        )
        if display_scale != 1.0:
            display_values = [clamp(value * display_scale) for value in display_values]
        cells: list[list[int | float]] = []
        cols = self.seed_field.grid.cols
        for idx, density in enumerate(display_values):
            if density <= self.display_threshold:
                continue
            row = idx // cols
            col = idx % cols
            cells.append([row, col, round(density, 3)])
        return cells


def normalize_display_values(raw_values: list[float], *, gamma: float = 0.72) -> list[float]:
    positives = sorted(value for value in raw_values if value > 0.0)
    if not positives:
        return [0.0] * len(raw_values)

    floor = percentile(positives, 0.18) * 0.38
    p92 = percentile(positives, 0.92)
    p98 = percentile(positives, 0.98)
    max_value = positives[-1]
    ceiling = max(p92 * 1.10, p98 * 0.86, max_value * 0.58, floor + 0.03)

    normalized: list[float] = []
    for value in raw_values:
        if value <= floor:
            normalized.append(0.0)
            continue
        scaled = clamp((value - floor) / (ceiling - floor))
        normalized.append(clamp(scaled ** gamma))
    return normalized


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = clamp(q) * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(len(sorted_values) - 1, lower + 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction
