"""Display-side demand dispersion overlay.

Two design constraints from the demo brief:

1. **Heat must live in the Ballard neighborhood, not strung along the planned
   track.** The user does not want the baseline to telegraph the future Ballard
   line by lighting up a thin Interbay -> SLU -> Westlake corridor. They want a
   wide *blob* over the Ballard area that disappears when the line opens.

2. **Cause and effect has to be unmistakable.** The frontend's heatmap-weight
   ramp treats cells <= 0.05 as effectively invisible and cells >= 0.35 as
   bright orange. We pick latent peaks well above 0.35 and relief peaks that
   over-subtract the latent kernel so the entire blob cleanly vanishes — not
   "redistributes."

Layers
------
Latent demand (always on):
  * Ballard neighborhood blob (NW Seattle)
  * East-side commuter blob (Mercer Island / I-90 catchment, mostly anchored at
    the western end inside the bbox)
  * Downtown peak-hour congestion
  * Stadium / SoDo congestion (so the World Cup demo has a hot spot to absorb)

Per-line relief (subtracted when active):
  * East Link active (`line-1-2*`):
      east-side blob -> over-subtracted (gone)
      stadium / downtown -> notable drops (commuters now arrive by train)
  * Ballard line active (`*ballard*`):
      Ballard blob -> over-subtracted (gone)
      downtown -> additional drop (Ballard riders skip downtown drive)

Knobs
-----
`relief_strength` scales every subtraction. The frontend's "more train cars"
slider should POST to `/api/demo/relief`. Above 1.0, even the residual baseline
heat in catchment areas is fully drained — useful for the world cup demo to
show "extra service absorbs the crowd."

`extra_stops` is a list of point-Gaussian relief sites the user can drag onto
the map (POST `/api/demo/stops`). Each acts like a mini-station that absorbs
its catchment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.runtime.stores import FrameValues, GridConfig, clamp


_DATA_PROCESSING_ROOT = Path(__file__).resolve().parents[2]


# --- Geometry ------------------------------------------------------------

@dataclass(frozen=True)
class PointKernel:
    lat: float
    lon: float
    peak: float
    decay_m: float
    max_m: float


# Latent demand layers (always added).
LATENT_BALLARD = PointKernel(
    lat=47.6680, lon=-122.3850, peak=0.78,
    decay_m=1600.0, max_m=4800.0,
)
LATENT_EAST_SIDE = PointKernel(
    lat=47.5905, lon=-122.2430, peak=0.62,
    decay_m=1800.0, max_m=5200.0,
)
LATENT_DOWNTOWN = PointKernel(
    lat=47.6101, lon=-122.3344, peak=0.30,
    decay_m=1100.0, max_m=3000.0,
)
LATENT_STADIUM = PointKernel(
    lat=47.5952, lon=-122.3316, peak=0.32,
    decay_m=850.0, max_m=2400.0,
)

# Per-scenario relief kernels (subtracted; designed to over-subtract latent).
EAST_LINK_RELIEF = (
    PointKernel(  # cancels east-side latent and over-subtracts ~0.20
        lat=47.5905, lon=-122.2430, peak=0.86,
        decay_m=1800.0, max_m=5400.0,
    ),
    PointKernel(  # downtown drop - east-link riders no longer drive in
        lat=47.6101, lon=-122.3344, peak=0.28,
        decay_m=1100.0, max_m=3000.0,
    ),
    PointKernel(  # stadium catchment relief (world cup demo)
        lat=47.5952, lon=-122.3316, peak=0.36,
        decay_m=850.0, max_m=2400.0,
    ),
)
BALLARD_LINE_RELIEF = (
    PointKernel(  # cancels Ballard latent and over-subtracts ~0.20
        lat=47.6680, lon=-122.3850, peak=0.98,
        decay_m=1600.0, max_m=4800.0,
    ),
    PointKernel(  # secondary downtown drop
        lat=47.6101, lon=-122.3344, peak=0.20,
        decay_m=1100.0, max_m=3000.0,
    ),
)


# --- Math --------------------------------------------------------------

def _project_xy(
    lat: np.ndarray, lon: np.ndarray, origin_lat: float, origin_lon: float
) -> tuple[np.ndarray, np.ndarray]:
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * math.cos(math.radians(origin_lat))
    x = (lon - origin_lon) * meters_per_degree_lon
    y = (lat - origin_lat) * meters_per_degree_lat
    return x, y


def _distance_m_to(point_lat: float, point_lon: float, lat_a: np.ndarray, lon_a: np.ndarray) -> np.ndarray:
    px, py = _project_xy(lat_a, lon_a, point_lat, point_lon)
    return np.sqrt(px * px + py * py)


def _gauss_point(lat_a: np.ndarray, lon_a: np.ndarray, kernel: PointKernel) -> np.ndarray:
    d = _distance_m_to(kernel.lat, kernel.lon, lat_a, lon_a)
    return np.where(d <= kernel.max_m, kernel.peak * np.exp(-d / kernel.decay_m), 0.0)


def _cell_grid(config: GridConfig) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    cell_width = (config.east - config.west) / config.cols
    cell_height = (config.north - config.south) / config.rows
    keys: list[tuple[int, int]] = []
    lats: list[float] = []
    lons: list[float] = []
    for row in range(config.rows):
        clat = config.north - (row + 0.5) * cell_height
        for col in range(config.cols):
            clon = config.west + (col + 0.5) * cell_width
            keys.append((row, col))
            lats.append(clat)
            lons.append(clon)
    return np.array(lats, dtype=float), np.array(lons, dtype=float), keys


def _normalize_scenario(scenario_id: str | None) -> tuple[bool, bool]:
    """Return (east_link_active, ballard_active)."""
    if not scenario_id:
        return False, False
    sid = scenario_id.strip().lower()
    east_active = sid in ("line-1-2", "line-1-2-ballard") or sid.startswith("line-1-2")
    ballard_active = "ballard" in sid
    return east_active, ballard_active


# --- Public --------------------------------------------------------------

def is_demo_scenario(scenario_id: str | None) -> bool:
    east, ballard = _normalize_scenario(scenario_id)
    return east or ballard or (scenario_id or "").strip().lower() in {
        "state_baseline",
        "line-1",
        "default",
    }


def merge_demo_corridor_boost(
    values: FrameValues,
    config: GridConfig,
    scenario_id: str | None,
    *,
    enabled: bool = True,
    relief_strength: float = 1.0,
    extra_stops: list[PointKernel] | None = None,
) -> FrameValues:
    if not enabled:
        return values

    east_active, ballard_active = _normalize_scenario(scenario_id)
    lat_a, lon_a, keys = _cell_grid(config)

    add = (
        _gauss_point(lat_a, lon_a, LATENT_BALLARD)
        + _gauss_point(lat_a, lon_a, LATENT_EAST_SIDE)
        + _gauss_point(lat_a, lon_a, LATENT_DOWNTOWN)
        + _gauss_point(lat_a, lon_a, LATENT_STADIUM)
    )

    sub = np.zeros(lat_a.shape, dtype=float)
    if east_active:
        for kernel in EAST_LINK_RELIEF:
            sub += _gauss_point(lat_a, lon_a, kernel)
    if ballard_active:
        for kernel in BALLARD_LINE_RELIEF:
            sub += _gauss_point(lat_a, lon_a, kernel)

    if extra_stops:
        for stop in extra_stops:
            sub += _gauss_point(lat_a, lon_a, stop)

    sub *= max(0.0, float(relief_strength))
    delta = add - sub

    out: FrameValues = dict(values)
    eps = 1e-4
    for i, key in enumerate(keys):
        bump = float(delta[i])
        if bump > eps or (key in out and bump < -eps):
            new_val = clamp(out.get(key, 0.0) + bump)
            if new_val > 1e-6:
                out[key] = new_val
            elif key in out:
                out.pop(key, None)
    return out


# Convenience CSV loader used by tests / scripts -------------------------

_BALLARD_STATIONS_CSV = _DATA_PROCESSING_ROOT / "examples" / "scenarios" / "ballard_line_stations.csv"
_LINE2_STATIONS_CSV = _DATA_PROCESSING_ROOT / "examples" / "scenarios" / "line_2_stations.csv"


def load_ballard_polyline_from_csv(path: Path | None = None) -> list[tuple[float, float]] | None:
    """Compatibility helper. Returns ordered station coordinates for the Ballard line.

    The latent demand layer no longer uses this; the polyline still feeds the
    pipeline-side `ballard_corridor_density_proxy` if anyone wants per-cell
    residential density to follow the Ballard alignment.
    """
    target = path if path is not None else _BALLARD_STATIONS_CSV
    if not target.exists():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(target)
        if "sequence" in df.columns:
            df = df.sort_values("sequence")
        df = df.assign(
            lat=pd.to_numeric(df["lat"], errors="coerce"),
            lon=pd.to_numeric(df["lon"], errors="coerce"),
        ).dropna(subset=["lat", "lon"])
        if len(df) < 2:
            return None
        return list(zip(df["lat"].astype(float).tolist(), df["lon"].astype(float).tolist()))
    except (OSError, ValueError, ImportError, KeyError):
        return None
