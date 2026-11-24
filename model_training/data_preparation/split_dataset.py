"""
Split customer-support data into train, validation, and test sets.

- Keeps identical (normalized) customer queries in the same split.
- Stratifies by language + intent as closely as possible.
- Uses a fixed seed for reproducible results.
- Does not modify the original CSV.
"""

from pathlib import Path

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
RANDOM_STATE = 42

# This script and interactions.csv are in the same folder.
DATA_DIR = Path(__file__).resolve().parent
INPUT_FILE = DATA_DIR / "interactions.csv"

TRAIN_FILE = DATA_DIR / "train.csv"
VALIDATION_FILE = DATA_DIR / "validation.csv"
TEST_FILE = DATA_DIR / "test.csv"

REQUIRED_COLUMNS = {
    "customer_query",
    "language",
    "intent",
    "priority",
    "escalation_risk",
}


def main():
    print("\n========== DATA SPLITTING ==========\n")

    # 1. Load and validate the dataset.
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE)

    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    if df.empty:
        raise ValueError("The input dataset is empty.")

    if df["customer_query"].isna().any():
        raise ValueError("customer_query contains missing values. Fix these before splitting.")

    print(f"Loaded dataset: {len(df):,} rows")
    print(f"Input file: {INPUT_FILE}")

    # 2. Create groups from normalized query text.
    #    Repeated/identical queries will stay together in one split.
    query_groups = (
        df["customer_query"]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )

    if query_groups.eq("").any():
        raise ValueError("customer_query contains blank messages.")

    # Stratify on language + intent so both are represented consistently.
    stratify_labels = (
        df["language"].astype(str) + "__" + df["intent"].astype(str)
    )

    # 3. Create the test set: approximately 20% (1 of 5 folds).
    outer_splitter = StratifiedGroupKFold(
        n_splits=5,
        shuffle=True,
        random_state=RANDOM_STATE,
    )

    train_val_indices, test_indices = next(
        outer_splitter.split(df, stratify_labels, groups=query_groups)
    )

    train_val_df = df.iloc[train_val_indices].copy()
    test_df = df.iloc[test_indices].copy()

    # 4. Split the remaining 80% into training and validation.
    #    One of 8 folds from the remaining data is approximately 10%
    #    of the full dataset, leaving approximately 70% for training.
    inner_groups = query_groups.iloc[train_val_indices]
    inner_labels = stratify_labels.iloc[train_val_indices]

    inner_splitter = StratifiedGroupKFold(
        n_splits=8,
        shuffle=True,
        random_state=RANDOM_STATE,
    )

    train_relative_indices, validation_relative_indices = next(
        inner_splitter.split(
            train_val_df,
            inner_labels,
            groups=inner_groups,
        )
    )

    train_df = train_val_df.iloc[train_relative_indices].copy()
    validation_df = train_val_df.iloc[validation_relative_indices].copy()

    # 5. Basic checks before saving.
    if len(test_df) < 500:
        raise ValueError(
            f"Test set has only {len(test_df)} rows; the assignment requires at least 500."
        )

    if len(train_df) + len(validation_df) + len(test_df) != len(df):
        raise ValueError("Split row counts do not add up to the original dataset.")

    # 6. Save the splits. Original row order is retained within each split.
    train_df.to_csv(TRAIN_FILE, index=False)
    validation_df.to_csv(VALIDATION_FILE, index=False)
    test_df.to_csv(TEST_FILE, index=False)

    # 7. Verify that no normalized query appears in multiple splits.
    train_groups = set(query_groups.iloc[train_df.index])
    validation_groups = set(query_groups.iloc[validation_df.index])
    test_groups = set(query_groups.iloc[test_df.index])

    assert train_groups.isdisjoint(validation_groups)
    assert train_groups.isdisjoint(test_groups)
    assert validation_groups.isdisjoint(test_groups)

    # 8. Print split sizes and target distributions for inspection.
    print("\nSplit sizes:")
    for name, split_df in [
        ("Training", train_df),
        ("Validation", validation_df),
        ("Testing", test_df),
    ]:
        percentage = len(split_df) / len(df) * 100
        print(f"  {name:12} {len(split_df):4,} rows ({percentage:5.1f}%)")

    print("\nIntent distribution (% within each split):")
    for name, split_df in [
        ("Training", train_df),
        ("Validation", validation_df),
        ("Testing", test_df),
    ]:
        print(f"\n{name}:")
        print((split_df["intent"].value_counts(normalize=True) * 100).round(1).to_string())

    print("\nLanguage distribution (% within each split):")
    for name, split_df in [
        ("Training", train_df),
        ("Validation", validation_df),
        ("Testing", test_df),
    ]:
        print(f"\n{name}:")
        print((split_df["language"].value_counts(normalize=True) * 100).round(1).to_string())

    print("\nPriority distribution (% within each split):")
    for name, split_df in [
        ("Training", train_df),
        ("Validation", validation_df),
        ("Testing", test_df),
    ]:
        print(f"\n{name}:")
        print((split_df["priority"].value_counts(normalize=True) * 100).round(1).to_string())

    print("\nEscalation-risk distribution (% within each split):")
    for name, split_df in [
        ("Training", train_df),
        ("Validation", validation_df),
        ("Testing", test_df),
    ]:
        print(f"\n{name}:")
        print((split_df["escalation_risk"].value_counts(normalize=True) * 100).round(1).to_string())

    print("\nDuplicate-query leakage check: PASSED")
    print("No normalized customer query appears in more than one split.")

    print("\nSaved files:")
    print(f"  Training:   {TRAIN_FILE}")
    print(f"  Validation: {VALIDATION_FILE}")
    print(f"  Testing:    {TEST_FILE}")

    print("\nDone. The original interactions.csv was not changed.")
    print("====================================\n")


if __name__ == "__main__":
    main()
