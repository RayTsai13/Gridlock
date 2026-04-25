# Heatmap Data API Contract

## Overview

The prediction model streams foot traffic density data to the frontend map via **Server-Sent Events (SSE)** over a local HTTP connection. The spatial model is a fixed rectangular grid over Seattle.

Both processes run locally:
- **Python model server**: `http://localhost:8000`
- **React frontend dev server**: `http://localhost:5173`

---

## Grid Configuration

Both sides share a single grid definition. The grid partitions a bounding box into `rows x cols` equal-sized rectangular cells.

```json
{
  "bounds": {
    "west": -122.4357,
    "south": 47.4957,
    "east": -122.2358,
    "north": 47.7352
  },
  "rows": 120,
  "cols": 100
}
```

### Cell Indexing

- **Origin**: top-left (northwest corner of the bounding box).
- **Row**: increases southward (row 0 = northernmost strip).
- **Col**: increases eastward (col 0 = westernmost strip).
- **Cell size**: derived from bounds and grid dimensions.
  - `cell_width = (east - west) / cols`
  - `cell_height = (north - south) / rows`
- **Cell center** for `(row, col)`:
  - `lon = west + (col + 0.5) * cell_width`
  - `lat = north - (row + 0.5) * cell_height`

No geometry is transmitted — both sides compute cell positions from this shared config.

---

## Transport: Server-Sent Events (SSE)

### Endpoint

```
GET http://localhost:8000/api/heatmap/stream
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

The Python backend serves this endpoint. The frontend connects with `new EventSource(url)`.

### Event Types

#### `config`

Sent once on connection. Confirms the grid parameters the stream will use.

```
id: 0
event: config
data: {"bounds":{"west":-122.4357,"south":47.4957,"east":-122.2358,"north":47.7352},"rows":120,"cols":100}
```

#### `frame`

Sent repeatedly as the simulation runs. Each frame is a sparse set of cell updates.

```
id: 42
event: frame
data: {"timestamp":1714070400.0,"cells":[[12,34,0.82],[13,34,0.65],[14,35,0.41]]}
```

#### `clear`

Resets all cells to zero density. Sent when the simulation restarts or resets.

```
id: 43
event: clear
data: {}
```

### Event IDs

Every event includes an `id` field (monotonically increasing integer). On reconnect, the browser sends a `Last-Event-ID` header. The backend can use this to resume from where the client left off, or ignore it and re-send `config` + the latest frame.

---

## Frame Schema

```
{
  "timestamp": <float>,     // Unix seconds (simulation time)
  "cells": [                // Sparse array — only nonzero cells
    [<row>, <col>, <density>],
    ...
  ]
}
```

| Field       | Type              | Description                                      |
|-------------|-------------------|--------------------------------------------------|
| `timestamp` | float             | Unix timestamp in seconds (simulation clock)     |
| `cells`     | array of 3-tuples | Each entry is `[row, col, density]`              |
| `row`       | int               | 0-indexed, 0 = north edge                       |
| `col`       | int               | 0-indexed, 0 = west edge                        |
| `density`   | float             | Normalized intensity, range `[0.0, 1.0]`        |

### Semantics

- **Sparse**: Only cells with `density > 0` need to appear. Omitted cells are treated as `0.0` by the frontend.
- **Full-frame**: Each frame is a complete snapshot, not a delta. The frontend replaces the previous frame entirely.
- **Normalization**: The backend is responsible for normalizing density to `[0.0, 1.0]` before sending.

---

## Backend Implementation Requirements

The backend must serve a standard SSE endpoint. Any Python HTTP framework works (FastAPI, Flask, etc.) as long as the response meets these requirements:

1. **Response headers**:
   - `Content-Type: text/event-stream`
   - `Cache-Control: no-cache`
   - `X-Accel-Buffering: no`
2. **CORS**: Must allow requests from `http://localhost:5173` (or `*`).
3. **SSE format**: Each event is formatted as `id: <int>\nevent: <type>\ndata: <json>\n\n`.
4. **On new connection**: Send `config` event, then begin streaming `frame` events.
5. **On client disconnect**: Stop generating frames for that connection.

---

## Frontend Connection

```typescript
const source = new EventSource("http://localhost:8000/api/heatmap/stream");

source.addEventListener("config", (e) => {
  const config = JSON.parse(e.data);
  // initialize grid
});

source.addEventListener("frame", (e) => {
  const frame = JSON.parse(e.data);
  // update heatmap layer
});

source.addEventListener("clear", () => {
  // reset all cells to zero
});
```

The heatmap stream is independent from the Seattle building layer. The current frontend map loads buildings from local cached files in `public/seattle/` and then overlays the SSE heatmap on top.

---

## Error Handling

- If the SSE connection drops, `EventSource` auto-reconnects (built-in browser behavior).
- On reconnect, the browser sends `Last-Event-ID` header with the last received event ID.
- The backend re-sends the `config` event followed by the latest frame on each new connection.
- The frontend should handle receiving `config` multiple times (idempotent initialization).
