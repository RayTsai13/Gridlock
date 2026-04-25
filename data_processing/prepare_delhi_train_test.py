#!/usr/bin/env python3
"""Create train/test CSVs from transformed Delhi trip features."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from src.io_utils import ensure_dir, write_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split Delhi trip features into train/test files.")
    parser.add_argument(
        "--features-csv",
        default="data/processed/delhi_trip_features.csv",
        help="Input trip features from transform_delhi_metro.py.",
    )
    parser.add_argument("--out-dir", default="data/processed", help="Output directory.")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split fraction.")
    parser.add_argument("--random-state", type=int, default=42, help="Deterministic split seed.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = ensure_dir(Path(args.out_dir))
    features = pd.read_csv(args.features_csv)
    if "target_passengers" not in features.columns:
        raise ValueError("Input features must include target_passengers")

    usable = features[features["target_passengers"].notna()].copy()
    train, test = train_test_split(
        usable,
        test_size=args.test_size,
        random_state=args.random_state,
        stratify=usable["is_weekend"] if "is_weekend" in usable.columns else None,
    )

    train_path = write_csv(train, out_dir / "delhi_train_features.csv")
    test_path = write_csv(test, out_dir / "delhi_test_features.csv")
    summary = {
        "input_rows": int(len(features)),
        "usable_rows": int(len(usable)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train": str(train_path),
        "test": str(test_path),
    }
    (out_dir / "delhi_train_test_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
