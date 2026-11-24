"""
Simple EDA and feature preparation for customer-support interactions.

Run from the project root:
    python model_training/data_preparation/eda_feature_engineering.py

Optional custom paths:
    python model_training/data_preparation/eda_feature_engineering.py --input "path\\to\\interactions.csv"
    python model_training/data_preparation/eda_feature_engineering.py --output "path\\to\\model_data.csv"

Input default:
    model_training/data_preparation/interactions.csv

Single output dataset:
    model_training/data_preparation/interactions_encoded.csv

The script prints EDA results in the terminal. It creates only ONE output file:
the processed dataset for later model training.

The original CSV is not modified. Repeated queries are kept.
No train/test split, text vectorization, scaling or resampling is performed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


EXPECTED_COLUMNS = [
    "customer_query",
    "language",
    "intent",
    "priority",
    "escalation_risk",
]

TARGET_COLUMNS = ["intent", "priority", "escalation_risk"]
RELATIONSHIP_COLUMNS = ["language", "intent", "priority", "escalation_risk"]


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Run simple EDA and prepare one processed dataset."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / "interactions.csv",
        help="Input CSV (default: interactions.csv beside this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "interactions_encoded.csv",
        help="Single processed output CSV (default: interactions_encoded.csv beside this script).",
    )
    return parser.parse_args()


def print_distribution(df: pd.DataFrame, column: str) -> None:
    """Print counts and percentages for one column."""
    counts = df[column].fillna("<MISSING>").astype(str).value_counts(dropna=False)
    result = pd.DataFrame({
        "count": counts,
        "percentage": (counts / max(len(df), 1) * 100).round(2),
    })
    result.index.name = column

    print(f"\n{column} distribution:")
    print(result.to_string())


def check_relationship(df: pd.DataFrame, first: str, second: str) -> None:
    """Print counts and row percentages for a pair of categorical columns."""
    first_values = df[first].fillna("<MISSING>")
    second_values = df[second].fillna("<MISSING>")

    counts = pd.crosstab(first_values, second_values, dropna=False)
    percentages = (
        pd.crosstab(
            first_values,
            second_values,
            normalize="index",
            dropna=False,
        )
        .mul(100)
        .round(1)
    )

    print(f"\n{first} vs {second}")
    print("Counts:")
    print(counts.to_string())
    print("Row percentages:")
    print(percentages.to_string())


def print_class_distribution(df: pd.DataFrame, column: str) -> None:
    """Print class distribution and largest-to-smallest class ratio."""
    counts = df[column].value_counts(dropna=False)
    nonzero = counts[counts > 0]
    ratio = float(nonzero.max() / nonzero.min()) if len(nonzero) > 1 else 1.0

    result = pd.DataFrame({
        "class": counts.index.astype(str),
        "count": counts.values,
        "percentage": (counts.values / max(len(df), 1) * 100).round(2),
    })

    print(f"\n{column}:")
    print(result.to_string(index=False))
    print(f"Largest/smallest class ratio: {ratio:.2f}:1")


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()

    if not input_path.is_file():
        print(f"ERROR: Input CSV not found:\n{input_path}")
        print("Put interactions.csv beside this script or pass --input with its path.")
        return 1

    if input_path == output_path:
        print("ERROR: Input and output paths must be different.")
        return 1

    try:
        df = pd.read_csv(input_path)
    except Exception as exc:
        print(f"ERROR: Could not read input CSV: {exc}")
        return 1

    missing_columns = [column for column in EXPECTED_COLUMNS if column not in df.columns]
    if missing_columns:
        print(f"ERROR: Required columns are missing: {missing_columns}")
        return 1

    print("\n========== 1. DATASET OVERVIEW ==========")
    print(f"Input: {input_path}")
    print(f"Rows: {len(df):,}")
    print(f"Columns: {list(df.columns)}")

    print("\n========== 2. COLUMN DISTRIBUTIONS ==========")
    for column in EXPECTED_COLUMNS:
        if column == "customer_query":
            print(f"\nUnique customer queries: {df[column].nunique(dropna=True):,}")
            print("Sample messages:")
            for query in df[column].dropna().head(5):
                print(f"  - {query}")
        else:
            print_distribution(df, column)

    print("\n========== 3. COLUMN-TO-COLUMN RELATIONSHIPS ==========")
    for index, first in enumerate(RELATIONSHIP_COLUMNS):
        for second in RELATIONSHIP_COLUMNS[index + 1:]:
            check_relationship(df, first, second)

    print("\n========== 4. DATA QUALITY ==========")
    missing = df[EXPECTED_COLUMNS].isna().sum()
    blank_queries = int(
        df["customer_query"].fillna("").astype(str).str.strip().eq("").sum()
    )
    exact_duplicates = int(df.duplicated(subset=EXPECTED_COLUMNS).sum())
    repeated_queries = int(
        df["customer_query"].fillna("").astype(str).duplicated().sum()
    )

    print("Missing values:")
    print(missing.to_string())
    print(f"Blank customer queries: {blank_queries}")
    print(f"Exact duplicate rows: {exact_duplicates}")
    print(f"Repeated query texts: {repeated_queries} (kept; not removed)")

    print("\n========== 5. TARGET CLASS DISTRIBUTIONS ==========")
    for target in TARGET_COLUMNS:
        print_class_distribution(df, target)

    # Feature preparation: one-hot encode the language input column.
    # Keep customer_query unchanged and keep target columns as labels.
    print("\n========== 6. FEATURE PREPARATION ==========")
    processed_df = df.copy()

    language_dummies = pd.get_dummies(
        processed_df["language"],
        prefix="language",
        dtype=int,
    )
    processed_df = pd.concat([processed_df, language_dummies], axis=1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    processed_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"Added columns: {list(language_dummies.columns)}")
    print(f"\nONE processed dataset saved to:\n{output_path}")

    print("\nNotes:")
    print("- Original input CSV was not modified.")
    print("- Repeated queries were kept.")
    print("- Target columns were not encoded as input features.")
    print("- No train/test split, TF-IDF, scaling or SMOTETomek was applied.")
    print("- EDA results were printed only; no separate report files were created.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
