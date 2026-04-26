"""Deterministic Seattle demand seeds and time-of-week profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .geo import haversine_m
from .grid import Grid
from .sim_time import SimTime


@dataclass(frozen=True)
class DemandAnchor:
    name: str
    category: str
    lat: float
    lon: float
    weight: float
    radius_m: float


@dataclass(frozen=True)
class CellCenter:
    row: int
    col: int
    lat: float
    lon: float


@dataclass(frozen=True)
class TimeProfile:
    name: str
    category_weights: dict[str, float]
    pulse: float


SEATTLE_ANCHORS: tuple[DemandAnchor, ...] = (
    DemandAnchor("Downtown office core", "office", 47.6064, -122.3343, 1.35, 1700),
    DemandAnchor("South Lake Union", "office", 47.6244, -122.3385, 1.18, 1500),
    DemandAnchor("First Hill medical", "office", 47.6095, -122.3237, 0.72, 1150),
    DemandAnchor("SODO industrial", "industrial", 47.5828, -122.3310, 0.82, 1800),
    DemandAnchor("University District", "campus", 47.6614, -122.3148, 1.10, 1550),
    DemandAnchor("UW campus", "campus", 47.6540, -122.3076, 0.92, 1400),
    DemandAnchor("Capitol Hill", "nightlife", 47.6230, -122.3197, 1.15, 1500),
    DemandAnchor("Belltown", "nightlife", 47.6144, -122.3458, 0.88, 1250),
    DemandAnchor("Ballard", "nightlife", 47.6680, -122.3820, 1.00, 1700),
    DemandAnchor("Fremont", "nightlife", 47.6515, -122.3500, 0.72, 1350),
    DemandAnchor("Seattle Center", "venue", 47.6212, -122.3500, 1.02, 1350),
    DemandAnchor("Stadium District", "venue", 47.5907, -122.3325, 1.10, 1650),
    DemandAnchor("Waterfront / Pike Place", "tourism", 47.6096, -122.3425, 1.10, 1450),
    DemandAnchor("Alki / West Seattle", "tourism", 47.5799, -122.4104, 0.78, 1900),
    DemandAnchor("Green Lake", "tourism", 47.6802, -122.3344, 0.58, 1700),
    DemandAnchor("West Seattle Junction", "residential", 47.5612, -122.3868, 1.10, 2100),
    DemandAnchor("Queen Anne", "residential", 47.6376, -122.3567, 0.86, 1700),
    DemandAnchor("Wallingford", "residential", 47.6592, -122.3360, 0.78, 1750),
    DemandAnchor("Lake City", "residential", 47.7192, -122.2950, 0.72, 2100),
    DemandAnchor("Northgate", "residential", 47.7040, -122.3250, 0.78, 1850),
    DemandAnchor("Rainier Valley", "residential", 47.5475, -122.2873, 1.02, 2600),
    DemandAnchor("Beacon Hill", "residential", 47.5714, -122.3085, 0.76, 1850),
    DemandAnchor("Central District", "residential", 47.6077, -122.3002, 0.72, 1700),
    DemandAnchor("Magnolia", "residential", 47.6465, -122.3996, 0.58, 1850),
)


def cell_centers(grid: Grid) -> list[CellCenter]:
    bounds = grid.bounds
    cell_w = (bounds.east - bounds.west) / grid.cols
    cell_h = (bounds.north - bounds.south) / grid.rows
    centers: list[CellCenter] = []
    for row in range(grid.rows):
        lat = bounds.north - (row + 0.5) * cell_h
        for col in range(grid.cols):
            lon = bounds.west + (col + 0.5) * cell_w
            centers.append(CellCenter(row=row, col=col, lat=lat, lon=lon))
    return centers


def profile_for_time(sim_time: SimTime) -> TimeProfile:
    minute = sim_time.minute_of_day
    weekend = sim_time.is_weekend

    if weekend:
        if 600 <= minute < 1020:
            return TimeProfile(
                "weekend_day",
                {
                    "residential": 0.35,
                    "office": 0.10,
                    "campus": 0.25,
                    "industrial": 0.10,
                    "venue": 1.25,
                    "tourism": 1.75,
                    "nightlife": 0.45,
                },
                pulse=1.10,
            )
        if 1020 <= minute < 1380:
            return TimeProfile(
                "weekend_evening",
                {
                    "residential": 0.30,
                    "office": 0.08,
                    "campus": 0.22,
                    "industrial": 0.08,
                    "venue": 1.55,
                    "tourism": 1.20,
                    "nightlife": 1.75,
                },
                pulse=1.12,
            )
        return TimeProfile(
            "weekend_quiet",
            {
                "residential": 0.52,
                "office": 0.15,
                "campus": 0.20,
                "industrial": 0.10,
                "venue": 0.50,
                "tourism": 0.42,
                "nightlife": 0.72,
            },
            pulse=0.78,
        )

    if 390 <= minute < 570:
        return TimeProfile(
            "weekday_am",
            {
                "residential": 1.35,
                "office": 1.05,
                "campus": 1.05,
                "industrial": 0.72,
                "venue": 0.28,
                "tourism": 0.38,
                "nightlife": 0.22,
            },
            pulse=1.18,
        )
    if 570 <= minute < 930:
        return TimeProfile(
            "weekday_midday",
            {
                "residential": 0.45,
                "office": 1.08,
                "campus": 0.95,
                "industrial": 0.62,
                "venue": 0.48,
                "tourism": 0.78,
                "nightlife": 0.24,
            },
            pulse=0.92,
        )
    if 930 <= minute < 1140:
        return TimeProfile(
            "weekday_pm",
            {
                "residential": 1.18,
                "office": 1.20,
                "campus": 0.92,
                "industrial": 0.70,
                "venue": 0.55,
                "tourism": 0.44,
                "nightlife": 0.34,
            },
            pulse=1.16,
        )
    if 1140 <= minute < 1410:
        return TimeProfile(
            "weekday_evening",
            {
                "residential": 0.62,
                "office": 0.38,
                "campus": 0.42,
                "industrial": 0.25,
                "venue": 1.18,
                "tourism": 0.70,
                "nightlife": 1.32,
            },
            pulse=1.04,
        )
    return TimeProfile(
        "weekday_late",
        {
            "residential": 0.36,
            "office": 0.15,
            "campus": 0.22,
            "industrial": 0.10,
            "venue": 0.42,
            "tourism": 0.28,
            "nightlife": 0.92,
        },
        pulse=0.70,
    )


class SeedField:
    """Precomputes static anchor distances and emits time-shaped base pressure."""

    def __init__(self, grid: Grid, anchors: tuple[DemandAnchor, ...] = SEATTLE_ANCHORS):
        self.grid = grid
        self.centers = cell_centers(grid)
        self.anchors = anchors
        self._anchor_weights: list[list[float]] = []
        for center in self.centers:
            weights: list[float] = []
            for anchor in anchors:
                distance_m = haversine_m(center.lat, center.lon, anchor.lat, anchor.lon)
                weights.append(math.exp(-((distance_m / anchor.radius_m) ** 2)))
            self._anchor_weights.append(weights)
        self._city_fallback = [self._fallback_for_center(center) for center in self.centers]
        self._source_density = [
            grid.density[center.row][center.col] if grid.density else 0.0
            for center in self.centers
        ]

    def values_for(self, sim_time: SimTime) -> list[float]:
        profile = profile_for_time(sim_time)
        values: list[float] = []

        for idx, center in enumerate(self.centers):
            anchor_total = 0.0
            for anchor, spatial_weight in zip(self.anchors, self._anchor_weights[idx]):
                category_weight = profile.category_weights.get(anchor.category, 0.0)
                anchor_total += anchor.weight * category_weight * spatial_weight

            source_hint = self._source_density[idx]
            fallback = self._city_fallback[idx]
            cell_texture = 0.035 * source_hint + 0.028 * fallback
            ripple = 1.0 + 0.045 * math.sin(
                center.row * 0.83 + center.col * 1.17 + sim_time.time_bin / 95.0
            )
            value = (anchor_total * 0.36 + cell_texture) * profile.pulse * ripple
            if is_probable_water(center.lat, center.lon):
                value *= 0.12
            values.append(max(0.0, value))

        return values

    def _fallback_for_center(self, center: CellCenter) -> float:
        north_south = math.exp(-((center.lat - 47.61) / 0.085) ** 2)
        west_east = math.exp(-((center.lon + 122.335) / 0.085) ** 2)
        diagonal = math.exp(-(((center.lat - 47.62) + (center.lon + 122.33)) / 0.09) ** 2)
        return 0.50 * north_south + 0.35 * west_east + 0.15 * diagonal


_PUGET_COAST = (
    (47.74, -122.42),
    (47.69, -122.41),
    (47.67, -122.40),
    (47.645, -122.41),
    (47.635, -122.39),
    (47.625, -122.37),
    (47.615, -122.355),
    (47.605, -122.347),
    (47.595, -122.347),
    (47.58, -122.36),
    (47.565, -122.375),
    (47.55, -122.39),
    (47.50, -122.40),
)

_LAKE_WA_COAST = (
    (47.70, -122.255),
    (47.68, -122.260),
    (47.66, -122.262),
    (47.645, -122.270),
    (47.635, -122.275),
    (47.62, -122.272),
    (47.60, -122.270),
    (47.58, -122.268),
    (47.56, -122.262),
    (47.50, -122.255),
)


def _interp_lon(lat: float, waypoints: tuple[tuple[float, float], ...]) -> float:
    if lat >= waypoints[0][0]:
        return waypoints[0][1]
    if lat <= waypoints[-1][0]:
        return waypoints[-1][1]
    for idx in range(len(waypoints) - 1):
        lat_a, lon_a = waypoints[idx]
        lat_b, lon_b = waypoints[idx + 1]
        if lat_b <= lat <= lat_a:
            t = (lat - lat_b) / (lat_a - lat_b)
            return lon_b + t * (lon_a - lon_b)
    return waypoints[-1][1]


def is_probable_water(lat: float, lon: float) -> bool:
    if lon < _interp_lon(lat, _PUGET_COAST):
        return True
    if 47.628 < lat < 47.646 and -122.344 < lon < -122.328:
        return True
    return 47.52 < lat < 47.70 and lon > _interp_lon(lat, _LAKE_WA_COAST)
