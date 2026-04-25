"""
Mock SSE server that streams random heatmap frames.
Implements the contract defined in docs/heatmap-api-contract.md.

Usage:
    pip install fastapi uvicorn
    uvicorn mock.server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import math
import random
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Grid configuration — 200 × 170 for finer granularity (~120 m × 130 m cells)
# ---------------------------------------------------------------------------
GRID_CONFIG = {
    "bounds": {"west": -122.4357, "south": 47.4957, "east": -122.2358, "north": 47.7352},
    "rows": 200,
    "cols": 170,
}

# ---------------------------------------------------------------------------
# Water mask — precomputed at startup so frame generation just does a lookup.
#
# Three major water bodies are excluded:
#   1. Puget Sound / Elliott Bay (west of the Seattle coastline)
#   2. Lake Union (rough rectangle in central Seattle)
#   3. Lake Washington (east of the western shoreline)
#
# Coastlines are approximated as piecewise-linear curves specified by
# (lat, lon) waypoints running north-to-south.  Points are intentionally
# conservative (shifted away from land) so waterfront neighborhoods are
# never accidentally masked.
# ---------------------------------------------------------------------------

_PUGET_COAST = [
    # Eastern shore of Puget Sound / Elliott Bay (north → south)
    (47.74, -122.42),
    (47.69, -122.41),
    (47.67, -122.40),
    (47.645, -122.41),     # Magnolia headland
    (47.635, -122.39),     # Smith Cove
    (47.625, -122.37),     # Interbay
    (47.615, -122.355),    # Myrtle Edwards
    (47.605, -122.347),    # Downtown waterfront
    (47.595, -122.347),    # Pioneer Square waterfront
    (47.58, -122.36),      # SoDo
    (47.565, -122.375),    # Harbor Island
    (47.55, -122.39),      # Duwamish
    (47.50, -122.40),      # far south
]

_LAKE_WA_COAST = [
    # Western shore of Lake Washington (north → south)
    (47.70, -122.255),
    (47.68, -122.260),
    (47.66, -122.262),
    (47.645, -122.270),    # Union Bay
    (47.635, -122.275),
    (47.62, -122.272),     # Madison Park
    (47.60, -122.270),     # Leschi
    (47.58, -122.268),     # Mt Baker
    (47.56, -122.262),     # Rainier Beach
    (47.50, -122.255),     # far south
]


def _interp_lon(lat: float, waypoints: list[tuple[float, float]]) -> float:
    """Linearly interpolate a coastline longitude for a given latitude."""
    if lat >= waypoints[0][0]:
        return waypoints[0][1]
    if lat <= waypoints[-1][0]:
        return waypoints[-1][1]
    for i in range(len(waypoints) - 1):
        lat_a, lon_a = waypoints[i]
        lat_b, lon_b = waypoints[i + 1]
        if lat_b <= lat <= lat_a:
            t = (lat - lat_b) / (lat_a - lat_b)
            return lon_b + t * (lon_a - lon_b)
    return waypoints[-1][1]


def _build_water_mask() -> list[list[bool]]:
    """Return a rows × cols boolean grid.  True means the cell is water."""
    bounds = GRID_CONFIG["bounds"]
    rows = GRID_CONFIG["rows"]
    cols = GRID_CONFIG["cols"]
    cell_w = (bounds["east"] - bounds["west"]) / cols
    cell_h = (bounds["north"] - bounds["south"]) / rows

    mask: list[list[bool]] = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        lat = bounds["north"] - (r + 0.5) * cell_h
        for c in range(cols):
            lon = bounds["west"] + (c + 0.5) * cell_w

            # 1. Puget Sound — west of coastline
            if lon < _interp_lon(lat, _PUGET_COAST):
                mask[r][c] = True
                continue

            # 2. Lake Union (rough rectangle)
            if 47.628 < lat < 47.646 and -122.344 < lon < -122.328:
                mask[r][c] = True
                continue

            # 3. Lake Washington — east of western shoreline
            if 47.52 < lat < 47.70 and lon > _interp_lon(lat, _LAKE_WA_COAST):
                mask[r][c] = True

    return mask


WATER_MASK = _build_water_mask()

# ---------------------------------------------------------------------------
# Hotspots — row/col coordinates scaled for the 200 × 170 grid.
# (Row increases southward, col increases eastward.)
# ---------------------------------------------------------------------------
HOTSPOTS = [
    # --- Downtown Core ---
    (105, 82, 1.0),    # downtown center
    (97,  78, 0.85),   # Belltown / SLU
    (112, 75, 0.75),   # Pioneer Square

    # --- Capitol Hill / First Hill ---
    (97,  94, 0.9),    # Capitol Hill
    (105, 95, 0.6),    # First Hill

    # --- East Neighborhoods ---
    (87,  119, 0.6),   # Madison Valley / Montlake
    (80,  129, 0.5),   # Laurelhurst
    (95,  116, 0.5),   # Madrona / Leschi
    (92,  133, 0.4),   # Washington Park

    # --- Northwest Seattle ---
    (73,  58, 0.7),    # Queen Anne
    (63,  48, 0.6),    # Fremont / Ballard east
    (55,  37, 0.55),   # Ballard
    (60,  68, 0.5),    # Wallingford
    (50,  78, 0.55),   # University District

    # --- Beacon Hill ---
    (133, 107, 0.55),  # Beacon Hill center
    (125, 99,  0.5),   # North Beacon Hill / ID

    # --- West Seattle ---
    (135, 43, 0.55),   # West Seattle Junction
    (143, 34, 0.4),    # South West Seattle
    (128, 51, 0.45),   # North Delridge
]

_GAUSS_SPREAD = 800   # Gaussian denominator  (scaled for 200 × 170 grid)
_CUTOFF_DIST = 60     # Skip hotspot if farther than this many cells


def generate_frame(t: float) -> dict:
    """Generate a frame with density clusters that drift over time."""
    cells: list[list[int | float]] = []
    rows = GRID_CONFIG["rows"]
    cols = GRID_CONFIG["cols"]

    for r in range(rows):
        row_mask = WATER_MASK[r]
        for c in range(cols):
            if row_mask[c]:
                continue

            density = 0.0
            for hr, hc, strength in HOTSPOTS:
                # Hotspots drift slowly
                dr = hr + 5 * math.sin(t * 0.3 + hr)
                dc = hc + 5 * math.cos(t * 0.2 + hc)
                dx = r - dr
                dy = c - dc
                # Quick bounding-box rejection before expensive sqrt/exp
                if abs(dx) > _CUTOFF_DIST or abs(dy) > _CUTOFF_DIST:
                    continue
                dist_sq = dx * dx + dy * dy
                if dist_sq > _CUTOFF_DIST * _CUTOFF_DIST:
                    continue
                density += strength * math.exp(-dist_sq / _GAUSS_SPREAD)

            # Small noise for visual interest
            density += random.gauss(0, 0.02)
            density = max(0.0, min(1.0, density))

            if density > 0.05:
                cells.append([r, c, round(density, 3)])

    return {"timestamp": time.time(), "cells": cells}


async def stream_frames(request: Request):
    event_id = 0

    yield f"id: {event_id}\nevent: config\ndata: {json.dumps(GRID_CONFIG)}\n\n"
    event_id += 1

    t = 0.0
    while True:
        if await request.is_disconnected():
            break

        frame = generate_frame(t)
        yield f"id: {event_id}\nevent: frame\ndata: {json.dumps(frame)}\n\n"
        event_id += 1
        t += 0.5

        await asyncio.sleep(1)


@app.get("/api/heatmap/stream")
async def stream(request: Request):
    return StreamingResponse(
        stream_frames(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
