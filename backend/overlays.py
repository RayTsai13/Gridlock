"""Live crowd overlays with visual diffusion and decay."""

from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass

from .geo import clamp, haversine_m, point_segment_distance_m
from .network import NetworkInfluence, TransitStop
from .seeds import CellCenter
from .sim_time import MINUTES_PER_WEEK, SimTime


@dataclass
class CrowdOverlay:
    id: str
    kind: str
    lat: float
    lon: float
    count: int
    created_at_real_time: float
    created_at_minute: int
    duration_minutes: int
    radius_m: float
    decay_m: float

    def to_public_dict(self, *, include_tuning: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "lat": self.lat,
            "lon": self.lon,
            "count": self.count,
        }
        if include_tuning:
            payload.update(
                {
                    "kind": self.kind,
                    "duration_minutes": self.duration_minutes,
                    "radius_m": self.radius_m,
                    "decay_m": self.decay_m,
                }
            )
        return payload


class LiveOverlayManager:
    def __init__(self, centers: list[CellCenter]) -> None:
        self.centers = centers
        self.people: dict[str, CrowdOverlay] = {}

    def add(
        self,
        *,
        lat: float,
        lon: float,
        count: int,
        sim_time: SimTime,
        kind: str | None = None,
        duration_minutes: int | None = None,
        radius_m: float | None = None,
        decay_m: float | None = None,
    ) -> CrowdOverlay:
        count = max(1, int(count))
        resolved_duration = duration_minutes
        if resolved_duration is None:
            resolved_duration = 240 if count >= 10_000 else 180
        resolved_radius = radius_m
        if resolved_radius is None:
            resolved_radius = min(4200.0, max(1450.0, 780.0 + math.sqrt(count) * 24.0))
        resolved_decay = decay_m
        if resolved_decay is None:
            resolved_decay = max(420.0, resolved_radius / 2.6)

        overlay = CrowdOverlay(
            id=f"p_{secrets.token_hex(4)}",
            kind=str(kind or "crowd"),
            lat=float(lat),
            lon=float(lon),
            count=count,
            created_at_real_time=time.time(),
            created_at_minute=sim_time.minute_of_week,
            duration_minutes=max(30, int(resolved_duration)),
            radius_m=max(250.0, float(resolved_radius)),
            decay_m=max(100.0, float(resolved_decay)),
        )
        self.people[overlay.id] = overlay
        return overlay

    def remove(self, overlay_id: str) -> None:
        if overlay_id not in self.people:
            raise KeyError(overlay_id)
        del self.people[overlay_id]

    def clear(self) -> None:
        self.people.clear()

    def values_for(
        self,
        sim_time: SimTime,
        network_influence: NetworkInfluence,
    ) -> list[float]:
        values = [0.0] * len(self.centers)
        expired: list[str] = []
        for overlay_id, overlay in self.people.items():
            age_minutes = overlay_age_minutes(overlay, sim_time)
            if age_minutes > overlay.duration_minutes:
                expired.append(overlay_id)
                continue

            nearest_distance_m, nearest_stop = network_influence.nearest_station_distance(
                overlay.lat,
                overlay.lon,
            )
            station_nearby = nearest_stop is not None and nearest_distance_m <= 1250.0
            self._add_overlay_values(
                values=values,
                overlay=overlay,
                age_minutes=age_minutes,
                nearest_stop=nearest_stop if station_nearby else None,
            )

        for overlay_id in expired:
            self.people.pop(overlay_id, None)
        return values

    def _add_overlay_values(
        self,
        *,
        values: list[float],
        overlay: CrowdOverlay,
        age_minutes: int,
        nearest_stop: TransitStop | None,
    ) -> None:
        progress = clamp(age_minutes / overlay.duration_minutes)
        served = nearest_stop is not None
        decay_scale = 0.42 if served else 0.78
        temporal = math.exp(-age_minutes / max(18.0, overlay.duration_minutes * decay_scale))
        linger = 0.26 * (1.0 - progress) if not served else 0.08 * (1.0 - progress)
        count_strength = min(1.15, 0.24 + 0.125 * math.log1p(overlay.count))
        peak = count_strength * (temporal + linger)

        early_core_m = 230.0 + min(650.0, math.sqrt(overlay.count) * 4.2)
        spread_m = early_core_m + overlay.radius_m * (0.18 + 0.82 * math.sqrt(progress))
        if not served:
            spread_m *= 0.74 + 0.24 * progress

        for idx, center in enumerate(self.centers):
            distance_m = haversine_m(overlay.lat, overlay.lon, center.lat, center.lon)
            if distance_m <= spread_m:
                spatial = math.exp(-((distance_m / max(1.0, overlay.decay_m + spread_m * 0.28)) ** 2))
                wave_center = 0.42 * spread_m + 0.46 * spread_m * progress
                wave = math.exp(-((distance_m - wave_center) / max(180.0, spread_m * 0.24)) ** 2)
                values[idx] += peak * (0.72 * spatial + 0.22 * wave)

            if served and nearest_stop is not None:
                segment_distance_m, segment_progress = point_segment_distance_m(
                    center.lat,
                    center.lon,
                    overlay.lat,
                    overlay.lon,
                    nearest_stop.lat,
                    nearest_stop.lon,
                )
                moving_front = min(1.0, progress * 1.65 + 0.18)
                if segment_distance_m < 520.0 and segment_progress <= moving_front:
                    along = math.exp(-((segment_progress - moving_front) / 0.33) ** 2)
                    cross = math.exp(-((segment_distance_m / 310.0) ** 2))
                    values[idx] += peak * 0.28 * along * cross


def overlay_age_minutes(overlay: CrowdOverlay, sim_time: SimTime) -> int:
    return (sim_time.minute_of_week - overlay.created_at_minute) % MINUTES_PER_WEEK
