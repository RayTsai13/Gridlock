"""Geospatial helpers for station-buffer population density vectors."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd


def points_from_lon_lat(df: pd.DataFrame, lon_col: str = "lon", lat_col: str = "lat") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        df.copy(),
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )


def estimate_utm_crs(gdf: gpd.GeoDataFrame) -> str:
    estimated = gdf.estimate_utm_crs()
    if estimated is None:
        return "EPSG:3857"
    return estimated.to_string()


def compute_population_density_vectors(
    stations: pd.DataFrame,
    population_polygons: gpd.GeoDataFrame,
    population_col: str,
    radius_m: int = 1000,
    station_id_col: str = "station_id",
    lon_col: str = "lon",
    lat_col: str = "lat",
    city_boundary: gpd.GeoDataFrame | None = None,
    city_population: float | None = None,
) -> pd.DataFrame:
    """Area-weight population polygons into station buffers and normalize by city average."""
    if population_col not in population_polygons.columns:
        raise ValueError(f"Population column not found: {population_col}")

    station_points = points_from_lon_lat(stations, lon_col=lon_col, lat_col=lat_col)
    city_crs = estimate_utm_crs(population_polygons.to_crs("EPSG:4326"))

    polygons = population_polygons.to_crs(city_crs).copy()
    polygons[population_col] = pd.to_numeric(polygons[population_col], errors="coerce").fillna(0)
    polygons["polygon_area_sq_m"] = polygons.geometry.area
    polygons = polygons[polygons["polygon_area_sq_m"] > 0].copy()

    station_buffers = station_points.to_crs(city_crs).copy()
    station_buffers["geometry"] = station_buffers.geometry.buffer(radius_m)
    station_buffers["buffer_area_sq_km"] = station_buffers.geometry.area / 1_000_000

    intersections = gpd.overlay(
        station_buffers[[station_id_col, "buffer_area_sq_km", "geometry"]],
        polygons[[population_col, "polygon_area_sq_m", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    if intersections.empty:
        result = stations[[station_id_col]].copy()
        result["population_within_radius"] = 0.0
    else:
        intersections["intersection_area_sq_m"] = intersections.geometry.area
        intersections["weighted_population"] = (
            intersections[population_col]
            * intersections["intersection_area_sq_m"]
            / intersections["polygon_area_sq_m"]
        )
        result = (
            intersections.groupby(station_id_col, as_index=False)["weighted_population"]
            .sum()
            .rename(columns={"weighted_population": "population_within_radius"})
        )

    result = stations[[station_id_col]].merge(result, on=station_id_col, how="left")
    result["population_within_radius"] = result["population_within_radius"].fillna(0.0)
    result["population_density_within_radius"] = result["population_within_radius"] / (
        3.141592653589793 * (radius_m / 1000) ** 2
    )

    if city_boundary is not None and not city_boundary.empty:
        city_area_sq_km = city_boundary.to_crs(city_crs).geometry.area.sum() / 1_000_000
        total_population = city_population if city_population is not None else polygons[population_col].sum()
    else:
        total_population = polygons[population_col].sum()
        city_area_sq_km = polygons.geometry.area.sum() / 1_000_000
    city_density = total_population / city_area_sq_km if city_area_sq_km else 0.0
    result["city_average_population_density"] = city_density
    result["residential_density_ratio"] = (
        result["population_density_within_radius"] / city_density if city_density else 0.0
    )
    return result
