from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.common.train_service_profiles import (
    APP_STOPS,
    DAY_TYPES,
    LineConfig,
    aggregate_service_windows,
    build_path_profile,
    build_stop_name_lookup,
    build_synthetic_ballard_profiles,
    normalize_stop_name,
    resolve_display_stop_sequence,
    summarize_departure_windows,
)


class TrainServiceProfilesTests(unittest.TestCase):
    def test_normalize_stop_name_and_aliases_cover_display_stations(self) -> None:
        lookup = build_stop_name_lookup()
        self.assertEqual(lookup[normalize_stop_name("Univ of Washington")], "uw")
        self.assertEqual(
            lookup[normalize_stop_name("Int'l Dist/Chinatown Station")],
            "id-chinatown",
        )
        self.assertEqual(lookup[normalize_stop_name("South Lake Union")], "south-lake-union")

    def test_resolve_display_stop_sequence_matches_aliases(self) -> None:
        line_config = LineConfig(
            line_id="link-1-line",
            name="1 Line",
            route_short_name="1 Line",
            route_id_fallbacks=("100479",),
            path_name="LINE_1_TRACK",
            display_stop_ids=("northgate", "uw", "id-chinatown"),
        )
        rows = [
            {
                "stop_name": "Lynnwood City Center",
                "stop_sequence": 1,
            },
            {
                "stop_name": "Northgate",
                "stop_sequence": 2,
            },
            {
                "stop_name": "Univ of Washington",
                "stop_sequence": 3,
            },
            {
                "stop_name": "Int'l Dist/Chinatown Station",
                "stop_sequence": 4,
            },
        ]
        matched = resolve_display_stop_sequence(rows, line_config, 0, build_stop_name_lookup())
        self.assertIsNotNone(matched)
        self.assertEqual([row["stop_name"] for row in matched], ["Northgate", "Univ of Washington", "Int'l Dist/Chinatown Station"])

    def test_service_window_aggregation_uses_median(self) -> None:
        weekday_normal = summarize_departure_windows([360, 370, 380, 390, 400])
        weekday_outlier = summarize_departure_windows([360, 390, 420])
        aggregated = aggregate_service_windows([weekday_normal, weekday_normal, weekday_outlier])
        morning = next(window for window in aggregated if window["startMinute"] == 360)
        self.assertEqual(morning["headwayMinutes"], 10.0)
        self.assertEqual(morning["offsetMinutes"], 0.0)

    def test_ballard_profiles_are_generated_for_all_day_types(self) -> None:
        path_profile = build_path_profile(
            LineConfig(
                line_id="ballard-line",
                name="Ballard Line",
                route_short_name="Ballard Line",
                route_id_fallbacks=(),
                path_name="BALLARD_TRACK",
                display_stop_ids=("ballard", "westlake", "sodo"),
                synthetic=True,
            ),
            [
                APP_STOPS["ballard"].coordinates,
                APP_STOPS["westlake"].coordinates,
                APP_STOPS["sodo"].coordinates,
            ],
        )
        reference_profiles = {
            "link-2-line": {
                day_type: {
                    0: {"serviceWindows": [{"startMinute": 360, "endMinute": 390, "headwayMinutes": 8.0, "offsetMinutes": 2.0}]},
                    1: {"serviceWindows": [{"startMinute": 360, "endMinute": 390, "headwayMinutes": 8.0, "offsetMinutes": 4.0}]},
                }
                for day_type in DAY_TYPES
            }
        }
        profiles = build_synthetic_ballard_profiles(
            path_profile=path_profile,
            reference_profiles=reference_profiles,
            observed_speed_by_day_type={day_type: 500.0 for day_type in DAY_TYPES},
        )
        self.assertEqual(set(profiles.keys()), set(DAY_TYPES))
        for day_type in DAY_TYPES:
            self.assertTrue(profiles[day_type][0]["synthetic"])
            self.assertTrue(profiles[day_type][1]["synthetic"])


if __name__ == "__main__":
    unittest.main()
