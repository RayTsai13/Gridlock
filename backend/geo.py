"""Small geographic helpers for the heatmap simulation."""

from __future__ import annotations

import math


EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two WGS84 points."""
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def local_xy_m(
    lat: float,
    lon: float,
    *,
    origin_lat: float,
    origin_lon: float,
) -> tuple[float, float]:
    """Project a nearby WGS84 point to a local equirectangular meter plane."""
    lat_rad = math.radians(lat)
    origin_lat_rad = math.radians(origin_lat)
    x = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(origin_lat_rad)
    y = (lat_rad - origin_lat_rad) * EARTH_RADIUS_M
    return x, y


def point_segment_distance_m(
    point_lat: float,
    point_lon: float,
    a_lat: float,
    a_lon: float,
    b_lat: float,
    b_lon: float,
) -> tuple[float, float]:
    """Distance from a point to a segment, plus clamped segment progress.

    The returned progress is ``0`` at ``a`` and ``1`` at ``b``.
    """
    px, py = local_xy_m(point_lat, point_lon, origin_lat=point_lat, origin_lon=point_lon)
    ax, ay = local_xy_m(a_lat, a_lon, origin_lat=point_lat, origin_lon=point_lon)
    bx, by = local_xy_m(b_lat, b_lon, origin_lat=point_lat, origin_lon=point_lon)

    abx = bx - ax
    aby = by - ay
    length_sq = abx * abx + aby * aby
    if length_sq <= 1e-9:
        dx = px - ax
        dy = py - ay
        return math.hypot(dx, dy), 0.0

    progress = ((px - ax) * abx + (py - ay) * aby) / length_sq
    clamped = max(0.0, min(1.0, progress))
    closest_x = ax + clamped * abx
    closest_y = ay + clamped * aby
    return math.hypot(px - closest_x, py - closest_y), clamped


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))
