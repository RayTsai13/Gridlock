"""Active transit network parsing and pressure relief curves."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .geo import clamp, haversine_m, point_segment_distance_m
from .grid import Grid
from .seeds import CellCenter, cell_centers


VALID_SCENARIO_IDS = frozenset({"line-1", "line-1-2", "line-1-2-ballard"})
DEFAULT_SCENARIO_ID = "line-1"


@dataclass(frozen=True)
class TransitStop:
    id: str
    name: str
    lon: float
    lat: float


@dataclass(frozen=True)
class TransitLine:
    id: str
    name: str
    stop_ids: tuple[str, ...]
    path: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ActiveNetwork:
    stops: tuple[TransitStop, ...]
    lines: tuple[TransitLine, ...]

    @property
    def stop_by_id(self) -> dict[str, TransitStop]:
        return {stop.id: stop for stop in self.stops}


@dataclass(frozen=True)
class CellInfluence:
    relief: float
    underserved_bonus: float
    nearest_station_m: float


LINE_1_STOPS: tuple[TransitStop, ...] = (
    TransitStop("northgate", "Northgate", -122.3272, 47.6992),
    TransitStop("roosevelt", "Roosevelt", -122.3167, 47.6768),
    TransitStop("u-district", "U District", -122.3155, 47.6614),
    TransitStop("uw", "UW", -122.3037, 47.6498),
    TransitStop("capitol-hill", "Capitol Hill", -122.3209, 47.6190),
    TransitStop("westlake", "Westlake", -122.3371, 47.6113),
    TransitStop("symphony", "Symphony", -122.3361, 47.6074),
    TransitStop("pioneer-square", "Pioneer Square", -122.3314, 47.6021),
    TransitStop("id-chinatown", "Intl District / Chinatown", -122.3278, 47.5983),
    TransitStop("stadium", "Stadium", -122.3275, 47.5911),
    TransitStop("sodo", "SODO", -122.3271, 47.5807),
    TransitStop("beacon-hill", "Beacon Hill", -122.3115, 47.5793),
    TransitStop("mount-baker", "Mount Baker", -122.2975, 47.5764),
    TransitStop("columbia-city", "Columbia City", -122.2922, 47.5599),
    TransitStop("othello", "Othello", -122.2812, 47.5383),
    TransitStop("rainier-beach", "Rainier Beach", -122.2688, 47.5222),
)

LINE_2_STOPS: tuple[TransitStop, ...] = (
    TransitStop("judkins-park", "Judkins Park", -122.3043, 47.5907),
    TransitStop("mercer-island", "Mercer Island", -122.2350, 47.5871),
    TransitStop("bellevue-downtown", "Bellevue Downtown", -122.1960, 47.6155),
)

BALLARD_STOPS: tuple[TransitStop, ...] = (
    TransitStop("midtown", "Midtown", -122.3322, 47.6088),
    TransitStop("denny", "Denny", -122.3405, 47.6188),
    TransitStop("south-lake-union", "South Lake Union", -122.3377, 47.6258),
    TransitStop("seattle-center", "Seattle Center", -122.3520, 47.6243),
    TransitStop("smith-cove", "Smith Cove", -122.3635, 47.6378),
    TransitStop("interbay", "Interbay", -122.3765, 47.6478),
    TransitStop("ballard", "Ballard", -122.3765, 47.6677),
)


def default_network_for_scenario(scenario_id: str) -> ActiveNetwork:
    if scenario_id not in VALID_SCENARIO_IDS:
        raise ValueError(f"Unknown scenario_id: {scenario_id!r}")

    stops = list(LINE_1_STOPS)
    lines: list[TransitLine] = [
        _line_from_stop_ids(
            "link-1-line",
            "1 Line",
            [
                "northgate",
                "roosevelt",
                "u-district",
                "uw",
                "capitol-hill",
                "westlake",
                "symphony",
                "pioneer-square",
                "id-chinatown",
                "stadium",
                "sodo",
                "beacon-hill",
                "mount-baker",
                "columbia-city",
                "othello",
                "rainier-beach",
            ],
            stops,
        )
    ]
    if scenario_id in {"line-1-2", "line-1-2-ballard"}:
        stops.extend(LINE_2_STOPS)
        lines.append(
            _line_from_stop_ids(
                "link-2-line",
                "2 Line",
                [
                    "northgate",
                    "roosevelt",
                    "u-district",
                    "uw",
                    "capitol-hill",
                    "westlake",
                    "symphony",
                    "pioneer-square",
                    "id-chinatown",
                    "judkins-park",
                    "mercer-island",
                    "bellevue-downtown",
                ],
                stops,
            )
        )
    if scenario_id == "line-1-2-ballard":
        stops.extend(BALLARD_STOPS)
        lines.append(
            _line_from_stop_ids(
                "ballard-line",
                "Ballard Line",
                [
                    "ballard",
                    "interbay",
                    "smith-cove",
                    "seattle-center",
                    "south-lake-union",
                    "denny",
                    "westlake",
                    "midtown",
                    "id-chinatown",
                    "sodo",
                ],
                stops,
            )
        )

    deduped: dict[str, TransitStop] = {}
    for stop in stops:
        deduped[stop.id] = stop
    return ActiveNetwork(stops=tuple(deduped.values()), lines=tuple(lines))


def parse_network_payload(
    *,
    scenario_id: str,
    stops_payload: Any = None,
    lines_payload: Any = None,
) -> ActiveNetwork:
    if not isinstance(stops_payload, list) or not isinstance(lines_payload, list):
        return default_network_for_scenario(scenario_id)

    stops: list[TransitStop] = []
    for raw_stop in stops_payload:
        if not isinstance(raw_stop, dict):
            continue
        coordinates = raw_stop.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            continue
        try:
            stop = TransitStop(
                id=str(raw_stop["id"]),
                name=str(raw_stop.get("name") or raw_stop["id"]),
                lon=float(coordinates[0]),
                lat=float(coordinates[1]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        stops.append(stop)

    stop_by_id = {stop.id: stop for stop in stops}
    lines: list[TransitLine] = []
    for raw_line in lines_payload:
        if not isinstance(raw_line, dict):
            continue
        stop_ids = tuple(str(stop_id) for stop_id in raw_line.get("stopIds", ()))
        path = _path_from_payload(raw_line.get("path"))
        if len(path) < 2:
            path = tuple(
                (stop_by_id[stop_id].lon, stop_by_id[stop_id].lat)
                for stop_id in stop_ids
                if stop_id in stop_by_id
            )
        if len(path) < 2:
            continue
        lines.append(
            TransitLine(
                id=str(raw_line.get("id") or f"line-{len(lines) + 1}"),
                name=str(raw_line.get("name") or raw_line.get("id") or "Line"),
                stop_ids=stop_ids,
                path=path,
            )
        )

    if not stops or not lines:
        return default_network_for_scenario(scenario_id)
    return ActiveNetwork(stops=tuple(stops), lines=tuple(lines))


class NetworkInfluence:
    """Precomputed station and corridor relief for the active network."""

    def __init__(self, grid: Grid, network: ActiveNetwork) -> None:
        self.grid = grid
        self.network = network
        self.centers = cell_centers(grid)
        self._segments = list(_line_segments(network))
        self._line_count_by_stop_id = _line_count_by_stop_id(network)
        self.systemwide_relief = _systemwide_relief(network)
        self.influences = [self._influence_for_center(center) for center in self.centers]

    @property
    def line_count_by_stop_id(self) -> dict[str, int]:
        return dict(self._line_count_by_stop_id)

    def apply(self, values: list[float]) -> list[float]:
        if not values:
            return []
        positive = [value for value in values if value > 0.0]
        avg_positive = sum(positive) / len(positive) if positive else 0.0
        output: list[float] = []
        for value, influence in zip(values, self.influences):
            local_cooled = value * (1.0 - influence.relief)
            system_cooled = local_cooled * (1.0 - self.systemwide_relief)
            bonus = (
                avg_positive
                * influence.underserved_bonus
                * (1.0 - self.systemwide_relief * 0.5)
            )
            output.append(max(0.0, system_cooled + bonus))
        return output

    @property
    def display_scale(self) -> float:
        return 1.0 - self.systemwide_relief

    def nearest_station_distance(self, lat: float, lon: float) -> tuple[float, TransitStop | None]:
        nearest_distance = float("inf")
        nearest_stop: TransitStop | None = None
        for stop in self.network.stops:
            distance = haversine_m(lat, lon, stop.lat, stop.lon)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_stop = stop
        return nearest_distance, nearest_stop

    def _influence_for_center(self, center: CellCenter) -> CellInfluence:
        stop_relief = 0.0
        nearest_station_m = float("inf")
        for stop in self.network.stops:
            distance_m = haversine_m(center.lat, center.lon, stop.lat, stop.lon)
            nearest_station_m = min(nearest_station_m, distance_m)
            service_count = self._line_count_by_stop_id.get(stop.id, 1)
            station_throughput = float(max(1, service_count))
            base_relief = (
                0.56 * math.exp(-((distance_m / 620.0) ** 2))
                + 0.18 * math.exp(-((distance_m / 1350.0) ** 2))
            )
            throughput_bonus = (
                0.04
                * max(0, service_count - 1)
                * math.exp(-((distance_m / 480.0) ** 2))
            )
            local_relief = base_relief * station_throughput + throughput_bonus
            local_cap = min(0.9, 0.72 + 0.12 * max(0, service_count - 1))
            stop_relief = _combine_probability(stop_relief, min(local_cap, local_relief))

        line_relief = 0.0
        nearest_line_m = float("inf")
        for a, b in self._segments:
            distance_m, _ = point_segment_distance_m(
                center.lat,
                center.lon,
                a.lat,
                a.lon,
                b.lat,
                b.lon,
            )
            nearest_line_m = min(nearest_line_m, distance_m)
            local_relief = 0.30 * math.exp(-((distance_m / 980.0) ** 2))
            line_relief = _combine_probability(line_relief, min(0.32, local_relief))

        relief = min(0.84, _combine_probability(stop_relief, line_relief))

        far_station = _smoothstep(1200.0, 3100.0, nearest_station_m)
        far_line = _smoothstep(1000.0, 2600.0, nearest_line_m)
        underserved_bonus = 0.16 * far_station * far_line
        return CellInfluence(
            relief=relief,
            underserved_bonus=underserved_bonus,
            nearest_station_m=nearest_station_m,
        )


@dataclass(frozen=True)
class _SegmentPoint:
    lat: float
    lon: float


def _line_from_stop_ids(
    line_id: str,
    name: str,
    stop_ids: list[str],
    stops: list[TransitStop],
) -> TransitLine:
    stop_by_id = {stop.id: stop for stop in stops}
    path = tuple(
        (stop_by_id[stop_id].lon, stop_by_id[stop_id].lat)
        for stop_id in stop_ids
        if stop_id in stop_by_id
    )
    return TransitLine(id=line_id, name=name, stop_ids=tuple(stop_ids), path=path)


def _path_from_payload(raw_path: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw_path, list):
        return ()
    path: list[tuple[float, float]] = []
    for raw_point in raw_path:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
            continue
        try:
            path.append((float(raw_point[0]), float(raw_point[1])))
        except (TypeError, ValueError):
            continue
    return tuple(path)


def _line_segments(network: ActiveNetwork):
    for line in network.lines:
        for idx in range(len(line.path) - 1):
            lon_a, lat_a = line.path[idx]
            lon_b, lat_b = line.path[idx + 1]
            yield _SegmentPoint(lat=lat_a, lon=lon_a), _SegmentPoint(lat=lat_b, lon=lon_b)


def _line_count_by_stop_id(network: ActiveNetwork) -> dict[str, int]:
    line_count_by_stop: dict[str, int] = {}
    for line in network.lines:
        for stop_id in line.stop_ids:
            line_count_by_stop[stop_id] = line_count_by_stop.get(stop_id, 0) + 1
    return line_count_by_stop


def _systemwide_relief(network: ActiveNetwork) -> float:
    extra_lines = max(0, len(network.lines) - 1)
    extra_stops = max(0, len(network.stops) - len(LINE_1_STOPS))
    return min(0.26, 0.075 * extra_lines + 0.006 * extra_stops)


def _combine_probability(current: float, next_value: float) -> float:
    return 1.0 - (1.0 - clamp(current)) * (1.0 - clamp(next_value))


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 0.0
    x = clamp((value - edge0) / (edge1 - edge0))
    return x * x * (3.0 - 2.0 * x)
