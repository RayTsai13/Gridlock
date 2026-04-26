"""Load a heatmap grid from a GeoJSON file.

The GeoJSON is expected to be a ``FeatureCollection`` of polygon cells where
each feature carries:

- ``properties.cell_id``: string of form ``r{row}_c{col}`` (zero-padded ints)
- one or more numeric ``properties.<name>`` fields used as density signals

The grid bounds, ``rows``, and ``cols`` are inferred from the cell ids and the
union of polygon coordinates, so the loader works with any rectangular grid
without hard-coded geometry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CELL_ID_RE = re.compile(r"^r(\d+)_c(\d+)$")


@dataclass(frozen=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    def to_dict(self) -> dict[str, float]:
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
        }


@dataclass
class Grid:
    bounds: Bounds
    rows: int
    cols: int
    # Dense rows x cols matrix of floats in [0, 1].
    density: list[list[float]]

    def config(self) -> dict:
        """Return the payload sent on the SSE ``config`` event."""
        return {
            "bounds": self.bounds.to_dict(),
            "rows": self.rows,
            "cols": self.cols,
        }


def _parse_cell_id(cell_id: str) -> tuple[int, int]:
    match = CELL_ID_RE.match(cell_id)
    if not match:
        raise ValueError(f"Unexpected cell_id format: {cell_id!r}")
    return int(match.group(1)), int(match.group(2))


def _polygon_bbox(coordinates) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for ring in coordinates:
        for lon, lat in ring:
            lons.append(lon)
            lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def load_grid(
    path: str | Path,
    density_property: str = "congestion_score",
) -> Grid:
    """Load a grid from a GeoJSON file and normalize density to ``[0, 1]``.

    Cells missing the requested property contribute ``0``. If every cell is
    zero (or the property is absent everywhere), the returned grid is empty
    (no nonzero density), which is still a valid frame.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    features = data.get("features") or []
    if not features:
        raise ValueError(f"No features in {path}")

    max_row = max_col = 0
    west = south = float("inf")
    east = north = float("-inf")
    for feature in features:
        row, col = _parse_cell_id(feature["properties"]["cell_id"])
        if row > max_row:
            max_row = row
        if col > max_col:
            max_col = col
        w, s, e, n = _polygon_bbox(feature["geometry"]["coordinates"])
        if w < west:
            west = w
        if s < south:
            south = s
        if e > east:
            east = e
        if n > north:
            north = n

    rows, cols = max_row + 1, max_col + 1
    density: list[list[float]] = [[0.0] * cols for _ in range(rows)]
    raw_max = 0.0
    for feature in features:
        row, col = _parse_cell_id(feature["properties"]["cell_id"])
        value = float(feature["properties"].get(density_property) or 0.0)
        density[row][col] = value
        if value > raw_max:
            raw_max = value

    if raw_max > 0:
        for row_values in density:
            for col_idx in range(cols):
                row_values[col_idx] = row_values[col_idx] / raw_max

    return Grid(
        bounds=Bounds(west=west, south=south, east=east, north=north),
        rows=rows,
        cols=cols,
        density=density,
    )
