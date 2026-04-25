#!/usr/bin/env python3
"""Transform Delhi Metro trip data into cross-city station/trip features.

This script intentionally avoids city-specific station identifiers as model
features. It creates station vectors from reusable characteristics, then joins
those vectors back onto each trip as origin/destination features.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.station_utils import clean_station, min_max, station_id


REQUIRED_COLUMNS = {
    "TripID",
    "Date",
    "From_Station",
    "To_Station",
    "Distance_km",
    "Fare",
    "Cost_per_passenger",
    "Passengers",
    "Ticket_Type",
    "Remarks",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build station vectors and transferable trip features from Delhi Metro data."
    )
    parser.add_argument(
        "--input",
        default="data/raw/delhi_metro_updated.csv",
        help="Delhi Metro input CSV.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/processed",
        help="Directory for transformed CSV outputs.",
    )
    parser.add_argument(
        "--density-vectors",
        default="data/processed/delhi_station_density.csv",
        help="Optional density vectors from build_delhi_population_vectors.py.",
    )
    return parser.parse_args()


def prepare_trips(path: Path) -> pd.DataFrame:
    trips = pd.read_csv(path)
    missing = REQUIRED_COLUMNS.difference(trips.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    trips = trips.copy()
    trips["from_station_clean"] = trips["From_Station"].map(clean_station)
    trips["to_station_clean"] = trips["To_Station"].map(clean_station)
    trips["from_station_id"] = trips["from_station_clean"].map(station_id)
    trips["to_station_id"] = trips["to_station_clean"].map(station_id)

    trips["date"] = pd.to_datetime(trips["Date"], errors="coerce")
    trips["day_of_week"] = trips["date"].dt.dayofweek
    trips["month"] = trips["date"].dt.month
    trips["year"] = trips["date"].dt.year
    trips["is_weekend"] = trips["day_of_week"].isin([5, 6]).astype(int)

    for column in ["Distance_km", "Fare", "Cost_per_passenger", "Passengers"]:
        trips[column] = pd.to_numeric(trips[column], errors="coerce")

    trips["ticket_type_clean"] = trips["Ticket_Type"].fillna("Unknown").map(clean_station)
    trips["remarks_clean"] = trips["Remarks"].fillna("normal").map(clean_station).str.lower()
    trips["is_peak"] = (trips["remarks_clean"] == "peak").astype(int)
    trips["is_off_peak"] = (trips["remarks_clean"] == "off-peak").astype(int)
    trips["is_festival"] = (trips["remarks_clean"] == "festival").astype(int)
    trips["is_maintenance"] = (trips["remarks_clean"] == "maintenance").astype(int)
    return trips


def load_density_vectors(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["station_id"])
    density = pd.read_csv(path)
    if "station_id" not in density.columns:
        raise ValueError(f"{path} must include station_id")
    return density


def build_station_vectors(trips: pd.DataFrame, density_vectors: pd.DataFrame) -> pd.DataFrame:
    stations = pd.DataFrame(
        {"station_clean": pd.concat([trips["from_station_clean"], trips["to_station_clean"]]).unique()}
    )
    stations["station_id"] = stations["station_clean"].map(station_id)

    origin = (
        trips.groupby("from_station_clean")
        .agg(
            origin_trips=("TripID", "count"),
            origin_passengers=("Passengers", "sum"),
            outbound_connections=("to_station_clean", "nunique"),
        )
        .reset_index()
        .rename(columns={"from_station_clean": "station_clean"})
    )
    destination = (
        trips.groupby("to_station_clean")
        .agg(
            destination_trips=("TripID", "count"),
            destination_passengers=("Passengers", "sum"),
            inbound_connections=("from_station_clean", "nunique"),
        )
        .reset_index()
        .rename(columns={"to_station_clean": "station_clean"})
    )

    vectors = stations.merge(origin, on="station_clean", how="left").merge(
        destination, on="station_clean", how="left"
    )
    numeric_columns = [
        "origin_trips",
        "origin_passengers",
        "outbound_connections",
        "destination_trips",
        "destination_passengers",
        "inbound_connections",
    ]
    vectors[numeric_columns] = vectors[numeric_columns].fillna(0)
    vectors["total_trips"] = vectors["origin_trips"] + vectors["destination_trips"]
    vectors["total_passengers"] = vectors["origin_passengers"] + vectors["destination_passengers"]
    vectors["connectivity"] = vectors["outbound_connections"] + vectors["inbound_connections"]
    vectors["is_transfer_proxy"] = (vectors["connectivity"] >= vectors["connectivity"].quantile(0.75)).astype(
        int
    )
    vectors["activity_rank_pct"] = vectors["total_passengers"].rank(pct=True)
    vectors["activity_score"] = min_max(vectors["total_passengers"])
    vectors["connectivity_score"] = min_max(vectors["connectivity"])
    vectors["station_id"] = vectors["station_clean"].map(station_id)
    if not density_vectors.empty:
        vectors = vectors.merge(density_vectors, on="station_id", how="left")

    # Keep station vectors limited to dimensions we can recreate for Seattle
    # from GTFS connectivity plus demographic/activity estimates.
    ordered = [
        "station_id",
        "station_clean",
        "lat",
        "lon",
        "activity_score",
        "connectivity_score",
        "activity_rank_pct",
        "is_transfer_proxy",
        "connectivity",
        "population_within_radius",
        "population_density_within_radius",
        "city_average_population_density",
        "residential_density_ratio",
    ]
    for column in ordered:
        if column not in vectors:
            vectors[column] = pd.NA
    return vectors[ordered].sort_values("activity_score", ascending=False)


def build_trip_features(trips: pd.DataFrame, vectors: pd.DataFrame) -> pd.DataFrame:
    vector_features = [
        "station_clean",
        "activity_score",
        "connectivity_score",
        "activity_rank_pct",
        "is_transfer_proxy",
        "connectivity",
        "residential_density_ratio",
    ]
    origin_vectors = vectors[vector_features].add_prefix("origin_")
    destination_vectors = vectors[vector_features].add_prefix("destination_")

    features = trips.merge(
        origin_vectors,
        left_on="from_station_clean",
        right_on="origin_station_clean",
        how="left",
    ).merge(
        destination_vectors,
        left_on="to_station_clean",
        right_on="destination_station_clean",
        how="left",
    )

    ticket_dummies = pd.get_dummies(features["ticket_type_clean"], prefix="ticket", dtype=int)
    remark_dummies = pd.get_dummies(features["remarks_clean"], prefix="remark", dtype=int)

    output = pd.concat(
        [
            features[
                [
                    "TripID",
                    "date",
                    "from_station_id",
                    "to_station_id",
                    "day_of_week",
                    "month",
                    "year",
                    "is_weekend",
                    "is_peak",
                    "is_off_peak",
                    "is_festival",
                    "is_maintenance",
                    "Distance_km",
                    "Fare",
                    "Cost_per_passenger",
                    "origin_activity_score",
                    "origin_connectivity_score",
                    "origin_activity_rank_pct",
                    "origin_is_transfer_proxy",
                    "origin_connectivity",
                    "origin_residential_density_ratio",
                    "destination_activity_score",
                    "destination_connectivity_score",
                    "destination_activity_rank_pct",
                    "destination_is_transfer_proxy",
                    "destination_connectivity",
                    "destination_residential_density_ratio",
                    "Passengers",
                ]
            ],
            ticket_dummies,
            remark_dummies,
        ],
        axis=1,
    )
    output = output.rename(columns={"Passengers": "target_passengers"})
    output["has_target"] = output["target_passengers"].notna().astype(int)
    return output


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trips = prepare_trips(Path(args.input))
    density_vectors = load_density_vectors(Path(args.density_vectors))
    station_vectors = build_station_vectors(trips, density_vectors)
    trip_features = build_trip_features(trips, station_vectors)

    station_path = out_dir / "delhi_station_vectors.csv"
    trip_path = out_dir / "delhi_trip_features.csv"
    station_output = station_vectors.rename(columns={"station_clean": "station_name"})
    station_output.to_csv(station_path, index=False)
    trip_features.to_csv(trip_path, index=False)

    print(
        {
            "input_rows": len(trips),
            "stations": len(station_vectors),
            "trip_feature_rows": len(trip_features),
            "station_vectors": str(station_path),
            "trip_features": str(trip_path),
        }
    )


if __name__ == "__main__":
    main()
