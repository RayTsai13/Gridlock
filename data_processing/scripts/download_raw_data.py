#!/usr/bin/env python3
"""Download and validate raw inputs for the data-processing pipelines."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.common.artifacts import (  # noqa: E402
    DEFAULT_GTFS_DIR,
    DEFAULT_RAW_DIR,
    DELHI_KAGGLE_ARCHIVE_ZIP,
    DELHI_STATION_COORDINATES_CSV,
    DELHI_TRIPS_CSV,
    DELHI_WARD_POPULATION_CSV,
    DELHI_WARDS_GEOJSON,
    FREMONT_BRIDGE_COUNTS_CSV,
    KING_COUNTY_ACS_TRACT_POPULATION_CSV,
    PUGET_SOUND_GTFS_ZIP,
    SEATTLE_ACS_PLACE_POPULATION_CSV,
    TRANSIT_ACCESSIBILITY_CSV,
    US_COUNTIES_GEOJSON,
    WASHINGTON_PLACE_SHAPEFILE_ZIP,
    WASHINGTON_TRACT_SHAPEFILE_ZIP,
)

DELHI_STATION_URL = (
    "https://raw.githubusercontent.com/kunalgupta2616/Classification-of-Delhi-Metro-stations/"
    "master/DELHI_METRO_DATA.csv"
)
DELHI_WARD_GEOJSON_URL = (
    "https://raw.githubusercontent.com/datameet/Municipal_Spatial_Data/master/Delhi/"
    "Delhi_Wards.geojson"
)
DELHI_WARD_POP_URL = (
    "https://data.opencity.in/dataset/c41aec9d-04a1-4a33-9254-4f7d50c7f8fa/"
    "resource/372c35ad-ae9e-418f-a2e6-faa3351de767/download/"
    "c16ccda1-eb93-40d9-8f78-b2f0327fcaca.csv"
)

DEFAULT_KAGGLE_DELHI_DATASET = "nikhilkumar766/delhi-metro-dataset"
GTFS_URL = "https://gtfs.sound.obaweb.org/prod/gtfs_puget_sound_consolidated.zip"
TRACT_ZIP_URL = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_53_tract_500k.zip"
PLACE_ZIP_URL = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_53_place_500k.zip"
ACS_URL = "https://api.census.gov/data/2022/acs/acs5"
FREMONT_CSV_URL = "https://data.seattle.gov/resource/65db-xm6k.csv"
TRANSIT_ACCESS_CSV_URL = "https://performance.seattle.gov/resource/pmj3-v6fx.csv"
LODES_BASE_URL = "https://lehd.ces.census.gov/data/lodes/LODES8/wa"
US_COUNTIES_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"

DELHI_TRIPS_REQUIRED_COLUMNS = {
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
        description="Download and cache public raw inputs used by the data-processing pipelines."
    )
    parser.add_argument(
        "--raw-dir",
        default=os.environ.get("RAW_DIR", str(DEFAULT_RAW_DIR)),
        help=f"Raw cache directory. Default: {DEFAULT_RAW_DIR}",
    )
    parser.add_argument(
        "--gtfs-dir",
        default=os.environ.get("GTFS_DIR", str(DEFAULT_GTFS_DIR)),
        help=f"Directory for extracted GTFS txt files. Default: {DEFAULT_GTFS_DIR}",
    )
    parser.add_argument(
        "--delhi-trips-url",
        default=os.environ.get("DELHI_TRIPS_URL", ""),
        help=f"Direct URL for {DELHI_TRIPS_CSV}. Kaggle URLs are also accepted.",
    )
    parser.add_argument(
        "--kaggle-delhi-dataset",
        default=os.environ.get("KAGGLE_DELHI_DATASET", DEFAULT_KAGGLE_DELHI_DATASET),
        help=f"Kaggle dataset for Delhi trips. Default: {DEFAULT_KAGGLE_DELHI_DATASET}",
    )
    parser.add_argument(
        "--fremont-limit",
        type=int,
        default=int(os.environ.get("FREMONT_LIMIT", "50000")),
        help="Seattle Fremont Bridge rows to cache. Default: 50000",
    )
    parser.add_argument(
        "--skip-gtfs",
        action="store_true",
        help="Do not download/extract Puget Sound GTFS.",
    )
    parser.add_argument(
        "--include-lehd",
        action="store_true",
        help="Also cache optional LEHD workplace files.",
    )
    parser.add_argument(
        "--lehd-year",
        type=int,
        default=int(os.environ.get("LEHD_YEAR", "2022")),
        help="LEHD WAC year. Default: 2022",
    )
    return parser.parse_args()


def resolve_path(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    return resolved


def cache_status(path: Path) -> str:
    if path.exists() and path.stat().st_size > 0:
        return "cached"
    return "download"


def download(url: str, destination: Path, headers: dict[str, str] | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if cache_status(destination) == "cached":
        print(f"cached  {destination}")
        return destination

    print(f"fetch   {destination}")
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    return destination


def require_nonempty(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Required raw input is missing or empty: {path}")


def validate_csv_columns(path: Path, required: set[str]) -> None:
    require_nonempty(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
    columns = {column.strip() for column in header}
    missing = sorted(required.difference(columns))
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")


def url_with_params(url: str, params: dict[str, object]) -> str:
    return f"{url}?{urllib.parse.urlencode(params)}"


def download_socrata(url: str, destination: Path, params: dict[str, object]) -> Path:
    return download(url_with_params(url, params), destination)


def kaggle_headers() -> dict[str, str]:
    headers = {"User-Agent": "seattle-transit-sim-data-processing/1.0"}
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if username and key:
        token = base64.b64encode(f"{username}:{key}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def kaggle_dataset_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if "kaggle.com" not in parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    try:
        datasets_index = parts.index("datasets")
    except ValueError:
        return None
    if len(parts) <= datasets_index + 2:
        return None
    return "/".join(parts[datasets_index + 1 : datasets_index + 3])


def extract_delhi_trips_from_kaggle_zip(zip_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        csv_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv") and not name.endswith("/")
        ]
        selected = None
        for name in csv_names:
            with archive.open(name) as member:
                text = io.TextIOWrapper(
                    member, encoding="utf-8-sig", errors="replace", newline=""
                )
                reader = csv.reader(text)
                header = next(reader, [])
            columns = {column.strip() for column in header}
            if DELHI_TRIPS_REQUIRED_COLUMNS.issubset(columns):
                selected = name
                break
        if selected is None:
            raise ValueError(
                "No CSV in the Kaggle archive has the required Delhi trip columns. "
                f"CSV files found: {', '.join(csv_names) or 'none'}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"extract {selected} -> {destination}")
        with archive.open(selected) as member, destination.open("wb") as output:
            shutil.copyfileobj(member, output)
    validate_csv_columns(destination, DELHI_TRIPS_REQUIRED_COLUMNS)
    return destination


def download_delhi_trips(
    destination: Path, delhi_trips_url: str, kaggle_dataset_setting: str, raw_dir: Path
) -> Path:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"cached  {destination}")
        validate_csv_columns(destination, DELHI_TRIPS_REQUIRED_COLUMNS)
        return destination

    kaggle_dataset = kaggle_dataset_from_url(delhi_trips_url) if delhi_trips_url else None
    if kaggle_dataset is not None:
        dataset = kaggle_dataset
    elif delhi_trips_url:
        download(delhi_trips_url, destination)
        validate_csv_columns(destination, DELHI_TRIPS_REQUIRED_COLUMNS)
        return destination
    else:
        dataset = kaggle_dataset_setting

    if not dataset or "/" not in dataset:
        raise ValueError("Kaggle dataset must use OWNER/SLUG format")

    zip_path = raw_dir / DELHI_KAGGLE_ARCHIVE_ZIP
    api_url = f"https://www.kaggle.com/api/v1/datasets/download/{dataset}"
    try:
        download(api_url, zip_path, headers=kaggle_headers())
    except Exception as exc:
        print(
            "Failed to download the Delhi trip dataset from Kaggle. "
            "If Kaggle requires auth in your environment, set KAGGLE_USERNAME and KAGGLE_KEY, "
            "or pass --delhi-trips-url with a direct CSV URL.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    return extract_delhi_trips_from_kaggle_zip(zip_path, destination)


def write_rows_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"write   {path}")
    return path


def cache_acs_tract_population(raw_dir: Path) -> None:
    path = raw_dir / KING_COUNTY_ACS_TRACT_POPULATION_CSV
    if path.exists() and path.stat().st_size > 0:
        print(f"cached  {path}")
        return
    params = {"get": "NAME,B01003_001E", "for": "tract:*", "in": "state:53 county:033"}
    with urllib.request.urlopen(url_with_params(ACS_URL, params), timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    header = payload[0] + ["GEOID", "population"]
    rows = []
    for row in payload[1:]:
        record = dict(zip(payload[0], row))
        geoid = record["state"] + record["county"] + record["tract"]
        rows.append(row + [geoid, record["B01003_001E"]])
    write_rows_csv(path, header, rows)


def cache_acs_place_population(raw_dir: Path) -> None:
    path = raw_dir / SEATTLE_ACS_PLACE_POPULATION_CSV
    if path.exists() and path.stat().st_size > 0:
        print(f"cached  {path}")
        return
    params = {"get": "NAME,B01003_001E", "for": "place:63000", "in": "state:53"}
    with urllib.request.urlopen(url_with_params(ACS_URL, params), timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    header = payload[0] + ["population"]
    rows = [row + [dict(zip(payload[0], row))["B01003_001E"]] for row in payload[1:]]
    write_rows_csv(path, header, rows)


def extract_gtfs(zip_path: Path, gtfs_dir: Path) -> None:
    required = ["stops.txt", "stop_times.txt", "trips.txt"]
    if all((gtfs_dir / name).exists() for name in required):
        print(f"cached  {gtfs_dir}")
        return
    gtfs_dir.mkdir(parents=True, exist_ok=True)
    print(f"extract {zip_path} -> {gtfs_dir}")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(gtfs_dir)


def required_files(raw_dir: Path, gtfs_dir: Path, include_gtfs: bool, include_lehd: bool, lehd_year: int) -> list[Path]:
    paths = [
        raw_dir / DELHI_STATION_COORDINATES_CSV,
        raw_dir / DELHI_WARDS_GEOJSON,
        raw_dir / DELHI_WARD_POPULATION_CSV,
        raw_dir / DELHI_TRIPS_CSV,
        raw_dir / WASHINGTON_TRACT_SHAPEFILE_ZIP,
        raw_dir / WASHINGTON_PLACE_SHAPEFILE_ZIP,
        raw_dir / KING_COUNTY_ACS_TRACT_POPULATION_CSV,
        raw_dir / SEATTLE_ACS_PLACE_POPULATION_CSV,
        raw_dir / FREMONT_BRIDGE_COUNTS_CSV,
        raw_dir / TRANSIT_ACCESSIBILITY_CSV,
    ]
    if include_gtfs:
        paths.append(raw_dir / PUGET_SOUND_GTFS_ZIP)
        paths.extend(gtfs_dir / name for name in ["stops.txt", "stop_times.txt", "trips.txt"])
    if include_lehd:
        paths.extend(
            [
                raw_dir / f"wa_wac_S000_JT00_{lehd_year}.csv.gz",
                raw_dir / "wa_xwalk.csv.gz",
                raw_dir / US_COUNTIES_GEOJSON,
            ]
        )
    return paths


def main() -> None:
    args = parse_args()
    raw_dir = resolve_path(args.raw_dir)
    gtfs_dir = resolve_path(args.gtfs_dir)
    include_gtfs = not args.skip_gtfs

    raw_dir.mkdir(parents=True, exist_ok=True)

    download(DELHI_STATION_URL, raw_dir / DELHI_STATION_COORDINATES_CSV)
    download(DELHI_WARD_GEOJSON_URL, raw_dir / DELHI_WARDS_GEOJSON)
    download(DELHI_WARD_POP_URL, raw_dir / DELHI_WARD_POPULATION_CSV)
    download_delhi_trips(
        raw_dir / DELHI_TRIPS_CSV,
        args.delhi_trips_url.strip(),
        args.kaggle_delhi_dataset.strip(),
        raw_dir,
    )

    download(TRACT_ZIP_URL, raw_dir / WASHINGTON_TRACT_SHAPEFILE_ZIP)
    download(PLACE_ZIP_URL, raw_dir / WASHINGTON_PLACE_SHAPEFILE_ZIP)
    cache_acs_tract_population(raw_dir)
    cache_acs_place_population(raw_dir)

    if include_gtfs:
        gtfs_zip = download(GTFS_URL, raw_dir / PUGET_SOUND_GTFS_ZIP)
        extract_gtfs(gtfs_zip, gtfs_dir)

    download_socrata(
        FREMONT_CSV_URL,
        raw_dir / FREMONT_BRIDGE_COUNTS_CSV,
        {
            "$limit": args.fremont_limit,
            "$order": "date DESC",
            "$select": "date,fremont_bridge,fremont_bridge_nb,fremont_bridge_sb",
        },
    )
    download_socrata(TRANSIT_ACCESS_CSV_URL, raw_dir / TRANSIT_ACCESSIBILITY_CSV, {"$limit": 5000})

    if args.include_lehd:
        download(
            f"{LODES_BASE_URL}/wac/wa_wac_S000_JT00_{args.lehd_year}.csv.gz",
            raw_dir / f"wa_wac_S000_JT00_{args.lehd_year}.csv.gz",
        )
        download(f"{LODES_BASE_URL}/wa_xwalk.csv.gz", raw_dir / "wa_xwalk.csv.gz")
        download(US_COUNTIES_GEOJSON_URL, raw_dir / US_COUNTIES_GEOJSON)

    for path in required_files(raw_dir, gtfs_dir, include_gtfs, args.include_lehd, args.lehd_year):
        require_nonempty(path)

    print(f"Raw cache ready: {raw_dir}")


if __name__ == "__main__":
    main()
