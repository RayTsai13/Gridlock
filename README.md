# Seattle Transit Sim

Seattle-focused map prototype for building and eventually visualizing foot-traffic heatmaps.

The current frontend is a `React + TypeScript + Vite` app that uses `MapLibre` for the base map, cached local Seattle building region files for structure, and an SSE heatmap overlay for simulated/model output.

## Project Areas

- `src/`
  - frontend app, MapLibre map, Seattle building rendering, SSE heatmap overlay
- `docs/`
  - frontend/API documentation
- `seattle/`
  - Seattle-specific data pipeline, cached asset export scripts, processed artifacts
- `data_processing/`
  - shared or non-Seattle data processing utilities
- `public/seattle/`
  - cached Seattle building region assets served directly by the frontend

## Current Map Architecture

- Buildings load from local cached Seattle GeoJSON region files in `public/seattle/`
- Region loading starts with downtown, then expands outward as additional areas are needed
- Extrusion heights come from Seattle's official `Seattle_BuildingShells` scene data, joined offline onto `Building_Outlines_2023` footprints
- Heatmap data is a separate SSE overlay path documented in [`docs/frontend-heatmap.md`](docs/frontend-heatmap.md)

See:
- [`docs/seattle-map-architecture.md`](docs/seattle-map-architecture.md)
- [`seattle/README.md`](seattle/README.md)

## Development

Install dependencies:

```bash
npm install
```

Run the frontend:

```bash
npm run dev
```

Build the frontend:

```bash
npm run build
```

## Heatmap Mock Server

The repository includes a local mock SSE server for heatmap development:

```bash
pip install fastapi uvicorn
uvicorn mock.server:app --host 0.0.0.0 --port 8000
```

The frontend listens to:

- `http://localhost:8000/api/heatmap/stream`

## Seattle Data Pipeline

Seattle-specific scripts now live under `seattle/scripts/`.

Typical building-data flow:

1. Extract official 3D shell heights from the City scene layer
2. Join heights onto official 2023 building footprints
3. Export cached neighborhood GeoJSON chunks into `public/seattle/`

Typical heatmap-data flow:

1. Build Seattle grid features
2. Train or evaluate the Seattle heatmap model

See [`seattle/README.md`](seattle/README.md) for the Seattle workspace layout and commands.
