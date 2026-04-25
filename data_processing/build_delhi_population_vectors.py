#!/usr/bin/env python3
"""Build Delhi station population-density vectors from metro stations and ward data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.geo_utils import compute_population_density_vectors
from src.io_utils import cached_download, ensure_dir, write_csv
from src.station_utils import clean_station, station_id


DEFAULT_STATION_URL = (
    "https://raw.githubusercontent.com/kunalgupta2616/Classification-of-Delhi-Metro-stations/"
    "master/DELHI_METRO_DATA.csv"
)
DEFAULT_WARD_GEOJSON_URL = (
    "https://raw.githubusercontent.com/datameet/Municipal_Spatial_Data/master/Delhi/"
    "Delhi_Wards.geojson"
)
DEFAULT_WARD_POP_URL = (
    "https://data.opencity.in/dataset/c41aec9d-04a1-4a33-9254-4f7d50c7f8fa/"
    "resource/372c35ad-ae9e-418f-a2e6-faa3351de767/download/"
    "c16ccda1-eb93-40d9-8f78-b2f0327fcaca.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Delhi residential-density station vectors.")
    parser.add_argument("--raw-dir", default="data/raw", help="Raw data cache directory.")
    parser.add_argument("--out-dir", default="data/processed", help="Output directory.")
    parser.add_argument("--radius-m", type=int, default=1000, help="Station population radius.")
    parser.add_argument("--stations-url", default=DEFAULT_STATION_URL)
    parser.add_argument("--ward-geojson-url", default=DEFAULT_WARD_GEOJSON_URL)
    parser.add_argument("--ward-population-url", default=DEFAULT_WARD_POP_URL)
    return parser.parse_args()


def load_station_coordinates(raw_dir: Path, url: str) -> pd.DataFrame:
    path = cached_download(url, raw_dir / "delhi_metro_station_coordinates.csv")
    stations = pd.read_csv(path)
    stations.columns = [column.strip() for column in stations.columns]
    stations = stations.rename(
        columns={"Station": "station_name", "Latitude": "lat", "Longitude": "lon"}
    )
    stations["station_name"] = stations["station_name"].map(clean_station)
    stations["station_id"] = stations["station_name"].map(station_id)
    stations["lat"] = pd.to_numeric(stations["lat"], errors="coerce")
    stations["lon"] = pd.to_numeric(stations["lon"], errors="coerce")
    stations = stations.dropna(subset=["lat", "lon"])
    return stations[["station_id", "station_name", "lat", "lon"]].drop_duplicates("station_id")


def pick_column(columns: list[str], candidates: list[str]) -> str:
    normalized = {station_id(column): column for column in columns}
    for candidate in candidates:
        if station_id(candidate) in normalized:
            return normalized[station_id(candidate)]
    raise ValueError(f"Could not find any of these columns: {', '.join(candidates)}")


def load_ward_population(raw_dir: Path, url: str) -> pd.DataFrame:
    path = cached_download(url, raw_dir / "delhi_ward_population.csv")
    population = pd.read_csv(path)
    ward_col = pick_column(list(population.columns), ["Ward", "Ward_Name", "ward"])
    pop_col = pick_column(list(population.columns), ["Population", "population"])
    population = population.rename(columns={ward_col: "ward_name", pop_col: "population"})
    population["ward_name"] = population["ward_name"].map(clean_station)
    population["ward_no"] = population["ward_name"].str.extract(r"(\d+)", expand=False)
    population["population"] = (
        population["population"].astype(str).str.replace(",", "", regex=False)
    )
    population["population"] = pd.to_numeric(population["population"], errors="coerce").fillna(0)
    return (
        population.groupby("ward_no", as_index=False)["population"]
        .sum()
        .dropna(subset=["ward_no"])
    )


def load_ward_geometry(raw_dir: Path, url: str) -> gpd.GeoDataFrame:
    path = cached_download(url, raw_dir / "delhi_wards.geojson")
    wards = gpd.read_file(path)
    if "Ward_Name" not in wards.columns:
        raise ValueError("Delhi ward GeoJSON is missing Ward_Name")
    wards["ward_name"] = wards["Ward_Name"].map(clean_station)
    return wards


def attach_population_to_wards(wards: gpd.GeoDataFrame, population: pd.DataFrame) -> gpd.GeoDataFrame:
    wards = wards.copy()
    wards["ward_no"] = wards["Ward_No"].astype(str).str.extract(r"(\d+)", expand=False)
    merged = wards.merge(
        population,
        on="ward_no",
        how="left",
    )
    merged["population"] = pd.to_numeric(merged["population"], errors="coerce").fillna(0)
    return merged


def main() -> None:
    args = parse_args()
    raw_dir = ensure_dir(Path(args.raw_dir))
    out_dir = ensure_dir(Path(args.out_dir))

    stations = load_station_coordinates(raw_dir, args.stations_url)
    ward_population = load_ward_population(raw_dir, args.ward_population_url)
    wards = attach_population_to_wards(
        load_ward_geometry(raw_dir, args.ward_geojson_url), ward_population
    )

    density = compute_population_density_vectors(
        stations=stations,
        population_polygons=wards,
        population_col="population",
        radius_m=args.radius_m,
    )
    vectors = stations.merge(density, on="station_id", how="left")
    output_path = write_csv(vectors, out_dir / "delhi_station_density.csv")

    summary = {
        "stations": int(len(stations)),
        "wards": int(len(wards)),
        "ward_population_rows": int(len(ward_population)),
        "matched_ward_population_rows": int((wards["population"] > 0).sum()),
        "radius_m": args.radius_m,
        "output": str(output_path),
    }
    (out_dir / "delhi_population_vector_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
