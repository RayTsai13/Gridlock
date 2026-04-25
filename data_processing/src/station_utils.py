"""Station cleaning, matching, and vector-normalization helpers."""

from __future__ import annotations

import re
from difflib import get_close_matches
from pathlib import Path

import pandas as pd


def clean_station(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    return re.sub(r"\s+", " ", str(value).strip())


def station_id(value: object) -> str:
    cleaned = clean_station(value).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return slug or "unknown"


def match_station_name(name: object, candidates: list[str], cutoff: float = 0.84) -> str | None:
    cleaned = clean_station(name)
    if cleaned in candidates:
        return cleaned
    normalized = {station_id(candidate): candidate for candidate in candidates}
    if station_id(cleaned) in normalized:
        return normalized[station_id(cleaned)]
    matches = get_close_matches(cleaned, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def min_max(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    span = values.max() - values.min()
    if span == 0:
        return values * 0
    return (values - values.min()) / span


def read_gtfs_stops(gtfs_dir: Path) -> pd.DataFrame:
    stops = pd.read_csv(gtfs_dir / "stops.txt")
    required = {"stop_id", "stop_name", "stop_lat", "stop_lon"}
    missing = required.difference(stops.columns)
    if missing:
        raise ValueError(f"GTFS stops missing required columns: {', '.join(sorted(missing))}")

    stops = stops.copy()
    stops["station_name"] = stops["stop_name"].map(clean_station)
    stops["station_id"] = stops["station_name"].map(station_id)
    stops["lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    return stops.dropna(subset=["lat", "lon"])


def aggregate_duplicate_stations(stops: pd.DataFrame) -> pd.DataFrame:
    return (
        stops.groupby(["station_id", "station_name"], as_index=False)
        .agg(lat=("lat", "mean"), lon=("lon", "mean"), stop_count=("stop_id", "nunique"))
        .sort_values("station_name")
    )


def add_rank_and_scores(
    df: pd.DataFrame,
    activity_column: str,
    connectivity_column: str,
    transfer_quantile: float = 0.75,
) -> pd.DataFrame:
    result = df.copy()
    result["activity_score"] = min_max(result[activity_column])
    result["connectivity_score"] = min_max(result[connectivity_column])
    result["activity_rank_pct"] = pd.to_numeric(result[activity_column], errors="coerce").rank(
        pct=True
    )
    threshold = pd.to_numeric(result[connectivity_column], errors="coerce").quantile(transfer_quantile)
    result["is_transfer_proxy"] = (
        pd.to_numeric(result[connectivity_column], errors="coerce").fillna(0) >= threshold
    ).astype(int)
    result["connectivity"] = pd.to_numeric(result[connectivity_column], errors="coerce").fillna(0)
    return result
