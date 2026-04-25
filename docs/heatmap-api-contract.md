# Heatmap Data API Contract

## Overview

The frontend talks to the intermediary process over three surfaces:

1. **SSE stream** (intermediary → frontend): heatmap frames + scenario confirmations
2. **`POST /api/scenario`** (frontend → intermediary): pick the active scenario
3. **`POST /api/people`** + friends (frontend → intermediary): inject / remove people in the simulation

SSE is one-way (server → client), so the upstream control actions are plain HTTP requests on the side. Both processes run locally:

- **Intermediary**: `http://localhost:8000`
- **Frontend dev server**: `http://localhost:5173`

The intermediary is the only piece that knows about both the model and the frontend; the model itself is out of scope for this document.

---

## Grid Configuration

The intermediary owns the grid. It partitions a bounding box into `rows x cols` equal-sized rectangular cells and tells the frontend on connect.

```json
{
  "bounds": {
    "west": -122.4357,
    "south": 47.4957,
    "east": -122.2358,
    "north": 47.7352
  },
  "rows": 200,
  "cols": 170
}
```

### Cell Indexing

- **Origin**: top-left (northwest corner of the bounding box)
- **Row**: increases southward (row 0 = northernmost strip)
- **Col**: increases eastward (col 0 = westernmost strip)
- **Cell size**:
  - `cell_width = (east - west) / cols`
  - `cell_height = (north - south) / rows`
- **Cell center** for `(row, col)`:
  - `lon = west + (col + 0.5) * cell_width`
  - `lat = north - (row + 0.5) * cell_height`

No geometry is transmitted on the wire — both sides compute cell positions from this shared config.

---

## SSE Stream

### Endpoint

```
GET http://localhost:8000/api/heatmap/stream
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

The frontend connects with `new EventSource(url)`.

### Event Types

#### `config`

Sent once on connect. Confirms the grid parameters the stream will use.

```
id: 0
event: config
data: {"bounds":{"west":-122.4357,"south":47.4957,"east":-122.2358,"north":47.7352},"rows":200,"cols":170}
```

#### `scenario`

Sent on connect (with the current scenario), and again every time the scenario changes (i.e. after a successful `POST /api/scenario`). Confirms which scenario the next batch of frames belongs to.

```
id: 1
event: scenario
data: {"scenario_id":"line-1-2-ballard"}
```

This is the authoritative source of truth for "what the heatmap is currently showing." See [Scenario change ordering](#scenario-change-ordering) below for how the frontend should handle in-flight frames during a switch.

#### `frame`

Sent continuously while the simulation runs. Each frame is a sparse snapshot of the grid.

```
id: 42
event: frame
data: {"timestamp":1714070400.0,"cells":[[12,34,0.82],[13,34,0.65],[14,35,0.41]]}
```

#### `clear`

Resets all cells to zero density. Sent when the simulation restarts.

```
id: 43
event: clear
data: {}
```

### Event IDs

Every event includes a monotonically increasing `id`. On reconnect, the browser sends a `Last-Event-ID` header. The intermediary may use this to resume, or simply re-send `config` + `scenario` + the latest frame on every new connection.

---

## Frame Schema

```
{
  "timestamp": <float>,     // Unix seconds (simulation time)
  "cells": [                // Sparse — only nonzero cells
    [<row>, <col>, <density>],
    ...
  ]
}
```

| Field       | Type              | Description                                  |
|-------------|-------------------|----------------------------------------------|
| `timestamp` | float             | Unix timestamp in seconds (simulation clock) |
| `cells`     | array of 3-tuples | Each entry is `[row, col, density]`          |
| `row`       | int               | 0-indexed, 0 = north edge                    |
| `col`       | int               | 0-indexed, 0 = west edge                     |
| `density`   | float             | Normalized intensity, range `[0.0, 1.0]`     |

**Semantics:**

- **Sparse**: cells with `density == 0` may be omitted; the frontend treats omitted cells as zero.
- **Full snapshot**: each frame replaces the previous frame entirely. No deltas.
- **Normalization**: the intermediary is responsible for normalizing density to `[0.0, 1.0]` before sending.

---

## `POST /api/scenario`

Change the active scenario. Affects the next frames emitted on the SSE stream.

### Request

```
POST /api/scenario
Content-Type: application/json

{ "scenario_id": "line-1-2-ballard" }
```

### Response

`200 OK`

```json
{ "scenario_id": "line-1-2-ballard" }
```

### Valid `scenario_id` values

These match the IDs in [`src/stops/data.ts`](../src/stops/data.ts) `EXPANSION_MODES`:

| `scenario_id`         | Description                                          |
|-----------------------|------------------------------------------------------|
| `line-1`              | Today's Link 1 Line — Northgate to Rainier Beach     |
| `line-1-2`            | Adds the 2 Line east branch                          |
| `line-1-2-ballard`    | Adds the Ballard extension                           |

### Behavior

After the POST returns `200`, the intermediary will:

1. Emit a `scenario` event on the SSE stream with the new `scenario_id`
2. Begin emitting `frame` events generated under the new scenario

### Errors

- `400 Bad Request` — unknown `scenario_id`

---

## `POST /api/people`

Inject a group of people at a location. Persists in the intermediary's state until explicitly removed.

### Request

```
POST /api/people
Content-Type: application/json

{ "lat": 47.6074, "lon": -122.3337, "count": 25 }
```

| Field   | Type  | Description                                         |
|---------|-------|-----------------------------------------------------|
| `lat`   | float | Latitude                                            |
| `lon`   | float | Longitude                                           |
| `count` | int   | Number of people in this group (default `1` if omitted) |

### Response

`201 Created`

```json
{ "id": "p_abc123", "lat": 47.6074, "lon": -122.3337, "count": 25 }
```

The `id` is opaque, assigned by the intermediary. Use it to remove the group later.

### Errors

- `400 Bad Request` — `lat`/`lon` out of the configured grid bounds

---

## `DELETE /api/people/{id}`

Remove a single placed group.

### Response

`204 No Content`

### Errors

- `404 Not Found` — unknown `id`

---

## `DELETE /api/people`

Clear all placed groups in one call. Useful for a frontend "reset" button.

### Response

`204 No Content`

---

## `GET /api/people`

List currently placed groups. Optional — useful if the frontend wants to render markers for placed groups, or recover state after a reload.

### Response

`200 OK`

```json
{
  "people": [
    { "id": "p_abc123", "lat": 47.6074, "lon": -122.3337, "count": 25 },
    { "id": "p_def456", "lat": 47.6190, "lon": -122.3209, "count": 10 }
  ]
}
```

---

## Behavior Notes

### People persistence

Placed groups persist until explicitly removed via `DELETE /api/people/{id}` or `DELETE /api/people`. They do not decay over time.

### People scope

Placed groups are **global**, not scoped to a scenario. Switching from `line-1` to `line-1-2-ballard` does not reset placed people; the intermediary feeds the same people list to the model regardless of which scenario is active.

### Scenario change ordering

When the frontend POSTs a new scenario, frames already in flight on the SSE stream may still belong to the old scenario. The intermediary emits the `scenario` event before any frame from the new scenario.

Recommended frontend handling:

1. On `POST /api/scenario`, store the requested `scenario_id` as a "pending" value.
2. Discard incoming `frame` events until a `scenario` event matching the pending value arrives.
3. After the matching `scenario` event, apply frames normally.

### Initial state on connect

On a fresh SSE connect, the intermediary sends:

1. `config` (once)
2. `scenario` (once, with whatever scenario is currently active — defaults to `line-1` on cold start)
3. `frame` events at the intermediary's chosen cadence

The frontend does not need to POST a scenario to get frames flowing; it only needs to POST when the user changes the dropdown.

---

## Intermediary Implementation Requirements

1. **CORS**: allow requests from `http://localhost:5173` (or `*`) on all endpoints, including `OPTIONS` preflight for the POST/DELETE routes.
2. **SSE response headers**:
   - `Content-Type: text/event-stream`
   - `Cache-Control: no-cache`
   - `X-Accel-Buffering: no`
3. **SSE event format**: `id: <int>\nevent: <type>\ndata: <json>\n\n`
4. **JSON request bodies**: `Content-Type: application/json` on all POST/DELETE endpoints.
5. **On client disconnect**: stop generating frames for that connection.
6. **Single source of truth for state**: scenario and placed people are intermediary state, not per-connection. Multiple SSE connections (e.g. two browser tabs) should see the same scenario and the same people list.

---

## Frontend Connection Example

```typescript
// SSE stream — heatmap frames + scenario confirmations
const source = new EventSource("http://localhost:8000/api/heatmap/stream");

source.addEventListener("config", (e) => {
  const config = JSON.parse(e.data);
  // initialize grid
});

source.addEventListener("scenario", (e) => {
  const { scenario_id } = JSON.parse(e.data);
  // record current scenario; clear pending flag if it matches
});

source.addEventListener("frame", (e) => {
  const frame = JSON.parse(e.data);
  // update heatmap layer (after checking for stale-scenario frames)
});

source.addEventListener("clear", () => {
  // reset all cells to zero
});

// Scenario change
async function setScenario(scenarioId: string) {
  await fetch("http://localhost:8000/api/scenario", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId }),
  });
}

// Add a group of people at a clicked location
async function addPeople(lat: number, lon: number, count: number) {
  const res = await fetch("http://localhost:8000/api/people", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat, lon, count }),
  });
  const { id } = await res.json();
  return id;
}

// Remove a single group
async function removePeople(id: string) {
  await fetch(`http://localhost:8000/api/people/${id}`, { method: "DELETE" });
}

// Clear all placed people
async function clearPeople() {
  await fetch("http://localhost:8000/api/people", { method: "DELETE" });
}
```

The heatmap stream is independent from the Seattle building layer. The frontend map loads buildings from local cached files in `public/seattle/` and overlays the SSE heatmap on top.

---

## Error Handling

- **SSE drops**: `EventSource` auto-reconnects (built-in browser behavior). The browser sends `Last-Event-ID` on the new connection. The intermediary re-sends `config`, `scenario`, and the latest frame.
- **Frontend should handle receiving `config` and `scenario` multiple times** (idempotent initialization).
- **POST/DELETE failures**: surface to the user via a small toast or status line. Do not retry automatically — these are user-initiated actions.
