"""Build representative train animation profiles from Sound Transit rail GTFS."""

from __future__ import annotations

import csv
import json
import math
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable


FEED_URL = "https://www.soundtransit.org/GTFS-rail/40_gtfs.zip"
SERVICE_WINDOW_MINUTES = 30
DEFAULT_DWELL_SECONDS = 20
WEEK_MINUTES = 7 * 24 * 60


@dataclass(frozen=True)
class AppStop:
    stop_id: str
    name: str
    coordinates: tuple[float, float]


@dataclass(frozen=True)
class LineConfig:
    line_id: str
    name: str
    route_short_name: str
    route_id_fallbacks: tuple[str, ...]
    path_name: str
    display_stop_ids: tuple[str, ...]
    synthetic: bool = False


@dataclass
class TripSlice:
    line_id: str
    direction_id: int
    service_id: str
    departure_minute: float
    trip_runtime_minutes: float
    segment_runtime_minutes: list[float]


APP_STOPS: dict[str, AppStop] = {
    "northgate": AppStop("northgate", "Northgate", (-122.3272, 47.6992)),
    "roosevelt": AppStop("roosevelt", "Roosevelt", (-122.3167, 47.6768)),
    "u-district": AppStop("u-district", "U District", (-122.3155, 47.6614)),
    "uw": AppStop("uw", "UW", (-122.3037, 47.6498)),
    "capitol-hill": AppStop("capitol-hill", "Capitol Hill", (-122.3209, 47.6190)),
    "westlake": AppStop("westlake", "Westlake", (-122.3371, 47.6113)),
    "symphony": AppStop("symphony", "Symphony", (-122.3361, 47.6074)),
    "pioneer-square": AppStop("pioneer-square", "Pioneer Square", (-122.3314, 47.6021)),
    "id-chinatown": AppStop(
        "id-chinatown",
        "Intl District / Chinatown",
        (-122.3278, 47.5983),
    ),
    "stadium": AppStop("stadium", "Stadium", (-122.3275, 47.5911)),
    "sodo": AppStop("sodo", "SODO", (-122.3271, 47.5807)),
    "beacon-hill": AppStop("beacon-hill", "Beacon Hill", (-122.3115, 47.5793)),
    "mount-baker": AppStop("mount-baker", "Mount Baker", (-122.2975, 47.5764)),
    "columbia-city": AppStop("columbia-city", "Columbia City", (-122.2922, 47.5599)),
    "othello": AppStop("othello", "Othello", (-122.2812, 47.5383)),
    "rainier-beach": AppStop("rainier-beach", "Rainier Beach", (-122.2688, 47.5222)),
    "judkins-park": AppStop("judkins-park", "Judkins Park", (-122.3043, 47.5907)),
    "mercer-island": AppStop("mercer-island", "Mercer Island", (-122.2350, 47.5871)),
    "bellevue-downtown": AppStop(
        "bellevue-downtown",
        "Bellevue Downtown",
        (-122.1960, 47.6155),
    ),
    "midtown": AppStop("midtown", "Midtown", (-122.3322, 47.6088)),
    "denny": AppStop("denny", "Denny", (-122.3405, 47.6188)),
    "south-lake-union": AppStop(
        "south-lake-union",
        "South Lake Union",
        (-122.3377, 47.6258),
    ),
    "seattle-center": AppStop("seattle-center", "Seattle Center", (-122.3520, 47.6243)),
    "smith-cove": AppStop("smith-cove", "Smith Cove", (-122.3635, 47.6378)),
    "interbay": AppStop("interbay", "Interbay", (-122.3765, 47.6478)),
    "ballard": AppStop("ballard", "Ballard", (-122.3765, 47.6677)),
}


LINE_CONFIGS: tuple[LineConfig, ...] = (
    LineConfig(
        line_id="link-1-line",
        name="1 Line",
        route_short_name="1 Line",
        route_id_fallbacks=("100479", "1LINE"),
        path_name="LINE_1_TRACK",
        display_stop_ids=(
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
        ),
    ),
    LineConfig(
        line_id="link-2-line",
        name="2 Line",
        route_short_name="2 Line",
        route_id_fallbacks=("2LINE",),
        path_name="LINE_2_TRACK",
        display_stop_ids=(
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
        ),
    ),
    LineConfig(
        line_id="ballard-line",
        name="Ballard Line",
        route_short_name="Ballard Line",
        route_id_fallbacks=(),
        path_name="BALLARD_TRACK",
        display_stop_ids=(
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
        ),
        synthetic=True,
    ),
)


STOP_ALIASES: dict[str, set[str]] = {
    "northgate": {"northgate"},
    "roosevelt": {"roosevelt"},
    "u-district": {"u district"},
    "uw": {"uw", "univ of washington", "university of washington"},
    "capitol-hill": {"capitol hill"},
    "westlake": {"westlake"},
    "symphony": {"symphony"},
    "pioneer-square": {"pioneer square"},
    "id-chinatown": {
        "intl district chinatown",
        "int l dist chinatown",
        "intl dist chinatown",
        "international district chinatown",
        "int dist chinatown",
    },
    "stadium": {"stadium"},
    "sodo": {"sodo"},
    "beacon-hill": {"beacon hill"},
    "mount-baker": {"mount baker"},
    "columbia-city": {"columbia city"},
    "othello": {"othello"},
    "rainier-beach": {"rainier beach"},
    "judkins-park": {"judkins park"},
    "mercer-island": {"mercer island"},
    "bellevue-downtown": {"bellevue downtown"},
    "midtown": {"midtown"},
    "denny": {"denny"},
    "south-lake-union": {"south lake union"},
    "seattle-center": {"seattle center"},
    "smith-cove": {"smith cove"},
    "interbay": {"interbay"},
    "ballard": {"ballard"},
}


DAY_TYPES = ("weekday", "saturday", "sunday")


def normalize_stop_name(name: str) -> str:
    value = name.lower()
    value = value.replace("&", " and ")
    value = value.replace("@", " at ")
    value = value.replace("int'l", "intl")
    value = value.replace("intl.", "intl")
    value = value.replace("univ", "university")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = [token for token in value.split() if token not in {"station"}]
    return " ".join(tokens)


def build_stop_name_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for stop_id, aliases in STOP_ALIASES.items():
        for alias in aliases:
            lookup[normalize_stop_name(alias)] = stop_id
    return lookup


def parse_gtfs_minutes(value: str) -> float:
    hour_text, minute_text, second_text, *_ = (*value.split(":"), "0")
    return int(hour_text) * 60 + int(minute_text) + int(second_text) / 60.0


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def date_to_day_type(value: date) -> str:
    if value.weekday() == 5:
        return "saturday"
    if value.weekday() == 6:
        return "sunday"
    return "weekday"


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(hav))


def median_or_zero(values: Iterable[float]) -> float:
    collected = [value for value in values if value is not None]
    if not collected:
        return 0.0
    return float(median(collected))


def read_zip_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as handle:
        return list(csv.DictReader((line.decode("utf-8-sig") for line in handle)))


def parse_track_geometry(track_geometry_path: Path) -> dict[str, list[tuple[float, float]]]:
    text = track_geometry_path.read_text(encoding="utf-8")
    tracks: dict[str, list[tuple[float, float]]] = {}
    for line_config in LINE_CONFIGS:
        pattern = re.compile(
            rf"export const {line_config.path_name}: LonLat\[\] = \[(.*?)\];",
            re.S,
        )
        match = pattern.search(text)
        if not match:
            raise ValueError(f"Could not find {line_config.path_name} in {track_geometry_path}")
        coordinates = [
            (float(lon), float(lat))
            for lon, lat in re.findall(
                r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
                match.group(1),
            )
        ]
        tracks[line_config.path_name] = coordinates
    return tracks


def build_cumulative_meters(path: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    total = 0.0
    for start, end in zip(path, path[1:]):
        total += haversine_meters(start, end)
        cumulative.append(total)
    return cumulative


def project_point_to_polyline(
    point: tuple[float, float],
    path: list[tuple[float, float]],
    cumulative: list[float],
    start_segment_index: int = 0,
) -> tuple[float, int]:
    best_distance = float("inf")
    best_cumulative = 0.0
    best_segment = start_segment_index

    point_lon, point_lat = point
    for index in range(start_segment_index, len(path) - 1):
        start = path[index]
        end = path[index + 1]
        mean_lat = math.radians((start[1] + end[1] + point_lat) / 3.0)
        lon_scale = 111320.0 * math.cos(mean_lat)
        lat_scale = 111320.0

        ax = start[0] * lon_scale
        ay = start[1] * lat_scale
        bx = end[0] * lon_scale
        by = end[1] * lat_scale
        px = point_lon * lon_scale
        py = point_lat * lat_scale

        vx = bx - ax
        vy = by - ay
        length_sq = vx * vx + vy * vy
        if length_sq == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length_sq))

        proj_x = ax + vx * t
        proj_y = ay + vy * t
        distance = math.hypot(px - proj_x, py - proj_y)
        if distance < best_distance:
            best_distance = distance
            best_segment = index
            best_cumulative = cumulative[index] + haversine_meters(start, end) * t

    return best_cumulative, best_segment


def build_path_profile(line_config: LineConfig, path: list[tuple[float, float]]) -> dict[str, object]:
    cumulative = build_cumulative_meters(path)
    stop_distances: list[float] = []
    search_index = 0
    for stop_id in line_config.display_stop_ids:
        app_stop = APP_STOPS[stop_id]
        distance, search_index = project_point_to_polyline(
            app_stop.coordinates,
            path,
            cumulative,
            start_segment_index=search_index,
        )
        stop_distances.append(round(distance, 3))

    return {
        "pathName": line_config.path_name,
        "pathCumulativeMeters": [round(value, 3) for value in cumulative],
        "stopDistanceMeters": stop_distances,
    }


def compute_service_dates(
    calendar_rows: list[dict[str, str]],
    calendar_date_rows: list[dict[str, str]],
    feed_start: date,
    feed_end: date,
) -> dict[str, set[date]]:
    service_dates: dict[str, set[date]] = defaultdict(set)

    for row in calendar_rows:
        service_id = row["service_id"]
        start = max(parse_date(row["start_date"]), feed_start)
        end = min(parse_date(row["end_date"]), feed_end)
        current = start
        while current <= end:
            weekday_flags = (
                row["monday"],
                row["tuesday"],
                row["wednesday"],
                row["thursday"],
                row["friday"],
                row["saturday"],
                row["sunday"],
            )
            if weekday_flags[current.weekday()] == "1":
                service_dates[service_id].add(current)
            current += timedelta(days=1)

    for row in calendar_date_rows:
        service_id = row["service_id"]
        current = parse_date(row["date"])
        if current < feed_start or current > feed_end:
            continue
        if row["exception_type"] == "1":
            service_dates[service_id].add(current)
        elif row["exception_type"] == "2":
            service_dates[service_id].discard(current)

    return service_dates


def find_route_ids(routes: list[dict[str, str]]) -> dict[str, str]:
    route_ids: dict[str, str] = {}
    for line_config in LINE_CONFIGS:
        if line_config.synthetic:
            continue
        matched = next(
            (
                row["route_id"]
                for row in routes
                if row.get("route_short_name") == line_config.route_short_name
            ),
            None,
        )
        if matched is None:
            for route_id in line_config.route_id_fallbacks:
                if any(row["route_id"] == route_id for row in routes):
                    matched = route_id
                    break
        if matched is None:
            raise ValueError(f"Could not find route for {line_config.name}")
        route_ids[line_config.line_id] = matched
    return route_ids


def resolve_display_stop_sequence(
    stop_rows: list[dict[str, object]],
    line_config: LineConfig,
    direction_id: int,
    stop_name_lookup: dict[str, str],
) -> list[dict[str, object]] | None:
    expected = (
        list(line_config.display_stop_ids)
        if direction_id == 0
        else list(reversed(line_config.display_stop_ids))
    )
    matched: list[dict[str, object]] = []
    expected_index = 0

    for row in sorted(stop_rows, key=lambda item: int(item["stop_sequence"])):
        stop_name = str(row["stop_name"])
        app_stop_id = stop_name_lookup.get(normalize_stop_name(stop_name))
        if app_stop_id != expected[expected_index]:
            continue
        matched.append(row)
        expected_index += 1
        if expected_index == len(expected):
            return matched

    return None


def build_trip_slices(
    trips: list[dict[str, str]],
    stop_times: list[dict[str, str]],
    stops: list[dict[str, str]],
    route_ids: dict[str, str],
) -> dict[str, TripSlice]:
    stop_name_lookup = build_stop_name_lookup()
    stop_names = {row["stop_id"]: row["stop_name"] for row in stops}
    line_configs = {config.line_id: config for config in LINE_CONFIGS if not config.synthetic}
    trips_by_id: dict[str, dict[str, str]] = {}
    trip_line_ids: dict[str, str] = {}

    for trip in trips:
        for line_id, route_id in route_ids.items():
            if trip["route_id"] == route_id:
                trips_by_id[trip["trip_id"]] = trip
                trip_line_ids[trip["trip_id"]] = line_id
                break

    stop_rows_by_trip: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in stop_times:
        trip_id = row["trip_id"]
        if trip_id not in trips_by_id:
            continue
        stop_rows_by_trip[trip_id].append(
            {
                "stop_id": row["stop_id"],
                "stop_name": stop_names[row["stop_id"]],
                "stop_sequence": int(row["stop_sequence"]),
                "arrival_minute": parse_gtfs_minutes(row["arrival_time"]),
                "departure_minute": parse_gtfs_minutes(row["departure_time"]),
            }
        )

    trip_slices: dict[str, TripSlice] = {}
    for trip_id, stop_rows in stop_rows_by_trip.items():
        trip = trips_by_id[trip_id]
        line_id = trip_line_ids[trip_id]
        line_config = line_configs[line_id]
        direction_id = int(trip["direction_id"])
        matched = resolve_display_stop_sequence(stop_rows, line_config, direction_id, stop_name_lookup)
        if matched is None:
            continue
        segment_runtime_minutes = [
            round(
                max(0.0, matched[index + 1]["arrival_minute"] - matched[index]["departure_minute"]),
                3,
            )
            for index in range(len(matched) - 1)
        ]
        if any(runtime <= 0 for runtime in segment_runtime_minutes):
            continue
        trip_runtime_minutes = round(
            max(0.0, matched[-1]["arrival_minute"] - matched[0]["departure_minute"]),
            3,
        )
        if trip_runtime_minutes <= 0:
            continue
        trip_slices[trip_id] = TripSlice(
            line_id=line_id,
            direction_id=direction_id,
            service_id=trip["service_id"],
            departure_minute=int(matched[0]["departure_minute"]),
            trip_runtime_minutes=trip_runtime_minutes,
            segment_runtime_minutes=segment_runtime_minutes,
        )

    return trip_slices


def summarize_departure_windows(departures: list[float]) -> dict[int, dict[str, float]]:
    if len(departures) < 2:
        return {}

    sorted_departures = sorted(value % (24 * 60) for value in departures)
    windows: dict[int, dict[str, list[float]]] = defaultdict(lambda: {"headways": [], "offsets": []})
    first_departures_by_bin: dict[int, int] = {}

    for departure in sorted_departures:
        bin_start = (departure // SERVICE_WINDOW_MINUTES) * SERVICE_WINDOW_MINUTES
        first_departures_by_bin.setdefault(bin_start, departure)

    for departure, next_departure in zip(sorted_departures, sorted_departures[1:]):
        headway = next_departure - departure
        if headway <= 0 or headway > 120:
            continue
        bin_start = (departure // SERVICE_WINDOW_MINUTES) * SERVICE_WINDOW_MINUTES
        windows[bin_start]["headways"].append(float(headway))

    for bin_start, first_departure in first_departures_by_bin.items():
        windows[bin_start]["offsets"].append(float(first_departure - bin_start))

    return {
        bin_start: {
            "headwayMinutes": round(median_or_zero(values["headways"]), 3),
            "offsetMinutes": round(median_or_zero(values["offsets"]), 3),
        }
        for bin_start, values in windows.items()
        if values["headways"]
    }


def aggregate_service_windows(date_windows: list[dict[int, dict[str, float]]]) -> list[dict[str, float]]:
    headways_by_bin: dict[int, list[float]] = defaultdict(list)
    offsets_by_bin: dict[int, list[float]] = defaultdict(list)

    for windows in date_windows:
        for bin_start, values in windows.items():
            headways_by_bin[bin_start].append(values["headwayMinutes"])
            offsets_by_bin[bin_start].append(values["offsetMinutes"])

    aggregated = []
    for bin_start in sorted(headways_by_bin):
        aggregated.append(
            {
                "startMinute": bin_start,
                "endMinute": min(24 * 60, bin_start + SERVICE_WINDOW_MINUTES),
                "headwayMinutes": round(median_or_zero(headways_by_bin[bin_start]), 3),
                "offsetMinutes": round(median_or_zero(offsets_by_bin[bin_start]), 3),
            }
        )
    return aggregated


def build_real_line_profiles(
    trip_slices: dict[str, TripSlice],
    service_dates: dict[str, set[date]],
    path_profiles: dict[str, dict[str, object]],
) -> dict[str, dict[str, dict[int, dict[str, object]]]]:
    metrics_by_date: dict[tuple[str, int, date], dict[str, object]] = {}

    for trip_slice in trip_slices.values():
        dates = service_dates.get(trip_slice.service_id, set())
        for service_date in dates:
            key = (trip_slice.line_id, trip_slice.direction_id, service_date)
            metrics = metrics_by_date.setdefault(
                key,
                {
                    "departures": [],
                    "trip_runtimes": [],
                    "segment_runtimes": [],
                },
            )
            metrics["departures"].append(trip_slice.departure_minute)
            metrics["trip_runtimes"].append(trip_slice.trip_runtime_minutes)
            metrics["segment_runtimes"].append(trip_slice.segment_runtime_minutes)

    profiles: dict[str, dict[str, dict[int, dict[str, object]]]] = defaultdict(lambda: defaultdict(dict))
    line_config_by_id = {config.line_id: config for config in LINE_CONFIGS if not config.synthetic}

    for line_id, day_type_dict in profiles.items():
        _ = day_type_dict

    grouped_by_line_day_direction: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for (line_id, direction_id, service_date), metrics in metrics_by_date.items():
        grouped_by_line_day_direction[(line_id, date_to_day_type(service_date), direction_id)].append(metrics)

    for (line_id, day_type, direction_id), date_metrics_list in grouped_by_line_day_direction.items():
        line_config = line_config_by_id[line_id]
        ordered_stop_ids = (
            list(line_config.display_stop_ids)
            if direction_id == 0
            else list(reversed(line_config.display_stop_ids))
        )
        date_windows = [summarize_departure_windows(metrics["departures"]) for metrics in date_metrics_list]
        per_date_segment_medians = []
        for metrics in date_metrics_list:
            segment_sets = metrics["segment_runtimes"]
            segment_count = len(segment_sets[0])
            per_date_segment_medians.append(
                [
                    median_or_zero(segment[index] for segment in segment_sets)
                    for index in range(segment_count)
                ]
            )

        segment_runtime_minutes = [
            round(median_or_zero(values[index] for values in per_date_segment_medians), 3)
            for index in range(len(per_date_segment_medians[0]))
        ]
        trip_runtime_minutes = round(
            median_or_zero(
                median_or_zero(metrics["trip_runtimes"]) for metrics in date_metrics_list
            ),
            3,
        )
        path_profile = path_profiles[line_id]
        stop_distances = list(path_profile["stopDistanceMeters"])
        if direction_id == 1:
            stop_distances = list(reversed(stop_distances))

        profiles[line_id][day_type][direction_id] = {
            "directionId": direction_id,
            "displayStartStopId": ordered_stop_ids[0],
            "displayEndStopId": ordered_stop_ids[-1],
            "stopIds": ordered_stop_ids,
            "serviceWindows": aggregate_service_windows(date_windows),
            "tripRuntimeMinutes": trip_runtime_minutes,
            "segmentRuntimeMinutes": segment_runtime_minutes,
            "pathCumulativeMeters": path_profile["pathCumulativeMeters"],
            "stopDistanceMeters": stop_distances,
            "synthetic": False,
        }

    return profiles


def compute_observed_segment_speeds(
    profiles: dict[str, dict[str, dict[int, dict[str, object]]]]
) -> dict[str, float]:
    speeds: dict[str, list[float]] = defaultdict(list)
    for line_id, day_profiles in profiles.items():
        if line_id == "ballard-line":
            continue
        for day_type, direction_profiles in day_profiles.items():
            for direction_profile in direction_profiles.values():
                stop_distances = [float(value) for value in direction_profile["stopDistanceMeters"]]
                segment_runtimes = [float(value) for value in direction_profile["segmentRuntimeMinutes"]]
                for index, runtime in enumerate(segment_runtimes):
                    if runtime <= 0:
                        continue
                    distance = abs(stop_distances[index + 1] - stop_distances[index])
                    if distance <= 0:
                        continue
                    speeds[day_type].append(distance / runtime)
    return {
        day_type: round(median_or_zero(values) or 600.0, 3)
        for day_type, values in speeds.items()
    }


def build_synthetic_ballard_profiles(
    path_profile: dict[str, object],
    reference_profiles: dict[str, dict[str, dict[int, dict[str, object]]]],
    observed_speed_by_day_type: dict[str, float],
) -> dict[str, dict[int, dict[str, object]]]:
    reference_line_profiles = reference_profiles["link-2-line"]
    line_config = next(config for config in LINE_CONFIGS if config.line_id == "ballard-line")
    stop_distances = [float(value) for value in path_profile["stopDistanceMeters"]]
    segment_distances = [
        abs(stop_distances[index + 1] - stop_distances[index])
        for index in range(len(stop_distances) - 1)
    ]

    profiles: dict[str, dict[int, dict[str, object]]] = defaultdict(dict)
    for day_type in DAY_TYPES:
        speed = observed_speed_by_day_type.get(day_type, 600.0)
        segment_runtime_minutes = [round(distance / speed, 3) for distance in segment_distances]
        trip_runtime_minutes = round(sum(segment_runtime_minutes), 3)
        reference_direction_profiles = reference_line_profiles[day_type]
        for direction_id in (0, 1):
            ordered_stop_ids = (
                list(line_config.display_stop_ids)
                if direction_id == 0
                else list(reversed(line_config.display_stop_ids))
            )
            direction_stop_distances = stop_distances if direction_id == 0 else list(reversed(stop_distances))
            profiles[day_type][direction_id] = {
                "directionId": direction_id,
                "displayStartStopId": ordered_stop_ids[0],
                "displayEndStopId": ordered_stop_ids[-1],
                "stopIds": ordered_stop_ids,
                "serviceWindows": reference_direction_profiles[direction_id]["serviceWindows"],
                "tripRuntimeMinutes": trip_runtime_minutes,
                "segmentRuntimeMinutes": segment_runtime_minutes,
                "pathCumulativeMeters": path_profile["pathCumulativeMeters"],
                "stopDistanceMeters": direction_stop_distances,
                "synthetic": True,
            }
    return profiles


def build_artifact(
    rail_gtfs_zip: Path,
    track_geometry_path: Path,
) -> dict[str, object]:
    track_paths = parse_track_geometry(track_geometry_path)
    path_profiles = {
        line_config.line_id: build_path_profile(line_config, track_paths[line_config.path_name])
        for line_config in LINE_CONFIGS
    }

    with zipfile.ZipFile(rail_gtfs_zip) as archive:
        feed_info_rows = read_zip_csv(archive, "feed_info.txt")
        routes = read_zip_csv(archive, "routes.txt")
        trips = read_zip_csv(archive, "trips.txt")
        stop_times = read_zip_csv(archive, "stop_times.txt")
        stops = read_zip_csv(archive, "stops.txt")
        calendar_rows = read_zip_csv(archive, "calendar.txt")
        calendar_date_rows = read_zip_csv(archive, "calendar_dates.txt")

    feed_info = feed_info_rows[0]
    feed_start = parse_date(feed_info["feed_start_date"])
    feed_end = parse_date(feed_info["feed_end_date"])
    route_ids = find_route_ids(routes)
    service_dates = compute_service_dates(calendar_rows, calendar_date_rows, feed_start, feed_end)
    trip_slices = build_trip_slices(trips, stop_times, stops, route_ids)
    real_profiles = build_real_line_profiles(trip_slices, service_dates, path_profiles)
    observed_speed_by_day_type = compute_observed_segment_speeds(real_profiles)
    real_profiles["ballard-line"] = build_synthetic_ballard_profiles(
        path_profiles["ballard-line"],
        real_profiles,
        observed_speed_by_day_type,
    )

    line_profiles = []
    for line_config in LINE_CONFIGS:
        for day_type in DAY_TYPES:
            direction_profiles = [
                real_profiles[line_config.line_id][day_type][direction_id]
                for direction_id in (0, 1)
            ]
            line_profiles.append(
                {
                    "lineId": line_config.line_id,
                    "dayType": day_type,
                    "synthetic": line_config.synthetic,
                    "directionProfiles": direction_profiles,
                }
            )

    return {
        "metadata": {
            "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "sourceFeedUrl": FEED_URL,
            "sourceFeedVersion": feed_info["feed_version"],
            "sourceFeedStartDate": feed_info["feed_start_date"],
            "sourceFeedEndDate": feed_info["feed_end_date"],
            "defaultDwellSeconds": DEFAULT_DWELL_SECONDS,
        },
        "lineProfiles": line_profiles,
    }


def artifact_to_typescript(artifact: dict[str, object]) -> str:
    payload = json.dumps(artifact, indent=2, sort_keys=False)
    return f"""// Auto-generated by data_processing/scripts/build_train_service_profiles.py
// Source GTFS: {artifact["metadata"]["sourceFeedUrl"]}
// Feed version: {artifact["metadata"]["sourceFeedVersion"]}

export type TrainDayType = 'weekday' | 'saturday' | 'sunday';

export type TrainServiceWindow = {{
  startMinute: number;
  endMinute: number;
  headwayMinutes: number;
  offsetMinutes: number;
}};

export type TrainDirectionProfile = {{
  directionId: 0 | 1;
  displayStartStopId: string;
  displayEndStopId: string;
  stopIds: string[];
  serviceWindows: TrainServiceWindow[];
  tripRuntimeMinutes: number;
  segmentRuntimeMinutes: number[];
  pathCumulativeMeters: number[];
  stopDistanceMeters: number[];
  synthetic: boolean;
}};

export type TrainLineProfile = {{
  lineId: string;
  dayType: TrainDayType;
  synthetic: boolean;
  directionProfiles: TrainDirectionProfile[];
}};

export type TrainServiceArtifact = {{
  metadata: {{
    generatedAt: string;
    sourceFeedUrl: string;
    sourceFeedVersion: string;
    sourceFeedStartDate: string;
    sourceFeedEndDate: string;
    defaultDwellSeconds: number;
  }};
  lineProfiles: TrainLineProfile[];
}};

export const TRAIN_SERVICE_ARTIFACT: TrainServiceArtifact = {payload} as const;
"""


def write_artifact_typescript(artifact: dict[str, object], output_path: Path) -> None:
    output_path.write_text(artifact_to_typescript(artifact), encoding="utf-8")
