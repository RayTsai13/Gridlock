# Frontend Heatmap Implementation

How the frontend consumes the heatmap data stream and renders it on the map.

See [heatmap-api-contract.md](./heatmap-api-contract.md) for the full wire protocol.

---

## SSE Connection Lifecycle

1. On app mount, open an `EventSource` to `http://localhost:8000/api/heatmap/stream`.
2. On `config` event: store the grid parameters (bounds, rows, cols). Precompute a lookup from `(row, col)` to `[lon, lat]` cell centroids using the formulas in the API contract. This lookup is static and only rebuilt if a new `config` arrives.
3. On `frame` event: convert the sparse cell array into GeoJSON and update the map source.
4. On `clear` event: set the map source to an empty FeatureCollection.
5. On component unmount: close the EventSource.

Reconnection is automatic (built-in `EventSource` behavior). A new `config` event on reconnect re-initializes the grid idempotently.

---

## Grid-to-GeoJSON Conversion

Each frame arrives as a sparse array of `[row, col, density]` tuples. The frontend converts this to a GeoJSON `FeatureCollection` of **Point** features, one per active cell, positioned at the cell centroid:

```
Frame input:
  { "timestamp": ..., "cells": [[12, 34, 0.82], [13, 34, 0.65]] }

GeoJSON output:
  {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": { "type": "Point", "coordinates": [<lon>, <lat>] },
        "properties": { "density": 0.82 }
      },
      {
        "type": "Feature",
        "geometry": { "type": "Point", "coordinates": [<lon>, <lat>] },
        "properties": { "density": 0.65 }
      }
    ]
  }
```

The `[lon, lat]` for each cell is read from the precomputed centroid lookup (see above). No geometry math happens per-frame — just an array index.

---

## MapLibre Heatmap Layer

The GeoJSON point source feeds a MapLibre `heatmap` layer. This gives smooth, blurred heat visuals rather than showing raw grid cells.

Key layer properties:

| Property               | Value                                      | Purpose                                             |
|------------------------|--------------------------------------------|-----------------------------------------------------|
| `heatmap-weight`       | `["get", "density"]`                       | Each point's contribution scales with its density   |
| `heatmap-intensity`    | Interpolated by zoom                       | Keeps visual intensity consistent across zoom levels|
| `heatmap-radius`       | Interpolated by zoom                       | Blur radius grows/shrinks with zoom                 |
| `heatmap-color`        | Color ramp from transparent → yellow → red | Standard density color scale                        |
| `heatmap-opacity`      | ~0.7                                       | Semi-transparent so buildings show through           |

The heatmap layer is placed **above** the building fill/outline layers in the map's layer stack so density is visible over the building footprints.

---

## Data Flow Summary

```
Python model
    │
    │  SSE frame: { timestamp, cells: [[row, col, density], ...] }
    ▼
EventSource listener
    │
    │  Sparse cells + precomputed centroid lookup
    ▼
Grid-to-GeoJSON conversion
    │
    │  FeatureCollection of Points with density property
    ▼
MapLibre GeoJSON source (react-map-gl <Source>)
    │
    ▼
MapLibre heatmap layer (react-map-gl <Layer>)
```

---

## Module Structure

| Module              | Responsibility                                                        |
|---------------------|-----------------------------------------------------------------------|
| `src/heatmap/grid.ts`   | Grid config types, centroid precomputation, frame-to-GeoJSON conversion |
| `src/heatmap/stream.ts` | EventSource connection, event parsing, lifecycle management            |
| `src/heatmap/layer.ts`  | MapLibre heatmap layer style definition                                |
| `src/App.tsx`            | Wires stream → grid → Source/Layer into the existing map              |
