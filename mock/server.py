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

GRID_CONFIG = {
    "bounds": {"west": -122.4357, "south": 47.4957, "east": -122.2358, "north": 47.7352},
    "rows": 120,
    "cols": 100,
}

# Fixed hotspots to simulate realistic clusters (row, col, strength)
# Grid is 120 rows x 100 cols covering all of Seattle
HOTSPOTS = [
    (55, 50, 1.0),   # downtown core
    (50, 55, 0.9),   # capitol hill
    (45, 45, 0.8),   # south lake union
    (60, 40, 0.7),   # pioneer square
    (35, 50, 0.6),   # university district
    (70, 55, 0.5),   # beacon hill
]


def generate_frame(t: float) -> dict:
    """Generate a frame with density clusters that drift over time."""
    cells = []
    rows = GRID_CONFIG["rows"]
    cols = GRID_CONFIG["cols"]

    for r in range(rows):
        for c in range(cols):
            density = 0.0
            for hr, hc, strength in HOTSPOTS:
                # Hotspots drift slowly
                dr = hr + 3 * math.sin(t * 0.3 + hr)
                dc = hc + 3 * math.cos(t * 0.2 + hc)
                dist = math.sqrt((r - dr) ** 2 + (c - dc) ** 2)
                density += strength * math.exp(-(dist ** 2) / 200)

            # Add noise
            density += random.gauss(0, 0.03)
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
