"""Input/output helpers for cached public data downloads."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import requests


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_download(url: str, destination: Path, timeout: int = 120) -> Path:
    ensure_dir(destination.parent)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def read_csv_url_or_cache(url: str, destination: Path, **read_csv_kwargs) -> pd.DataFrame:
    path = cached_download(url, destination)
    return pd.read_csv(path, **read_csv_kwargs)


def extract_zip_once(zip_path: Path, destination_dir: Path) -> Path:
    ensure_dir(destination_dir)
    marker = destination_dir / ".extracted"
    if marker.exists():
        return destination_dir

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination_dir)
    marker.write_text("ok\n")
    return destination_dir


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    ensure_dir(path.parent)
    df.to_csv(path, index=False)
    return path
