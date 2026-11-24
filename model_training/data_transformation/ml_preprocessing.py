"""
Prepare split datasets for the traditional ML pipeline.

Input CSVs:
    model_training/data/model_ready_data/ml/train/train.csv
    model_training/data/model_ready_data/ml/validation/validation.csv
    model_training/data/model_ready_data/ml/test/test.csv

Output files are saved beside each input CSV:
    X.csv  -> numerical input features (TF-IDF + one-hot language)
    y.csv  -> encoded prediction targets

The original split CSVs are not modified.
TF-IDF is fitted on training text only, then reused for validation and test.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


# ---------------------------------------------------------
# Paths and fixed target-label mappings
# ---------------------------------------------------------
# Script location: model_training/data_preparation/data_transformation/
BASE_DIR = Path(__file__).resolve().parents[1]
SPLIT_DIR = BASE_DIR / "data" / "model_ready_data" / "ml"

SPLITS = ("train", "validation", "test")

REQUIRED_COLUMNS = {
    "customer_query",
    "language",
    "intent",
    "priority",
    "escalation_risk",
}

INTENT_LABELS = [
    "order_status", "refund_request", "return_request", "damaged_item",
    "missing_item", "payment_issue", "cancellation", "delivery_delay",
    "product_information", "account_issue", "complaint", "other",
]
PRIORITY_LABELS = ["low", "medium", "high", "urgent"]

INTENT_MAPPING = {label: number for number, label in enumerate(INTENT_LABELS)}
PRIORITY_MAPPING = {label: number for number, label in enumerate(PRIORITY_LABELS)}
VALID_LANGUAGES = {"english", "hindi", "hinglish"}


def load_split(split_name):
    """Load and validate the split CSV from its own folder."""
    split_folder = SPLIT_DIR / split_name
    input_file = split_folder / f"{split_name}.csv"

    if not input_file.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_file}\n"
            f"Expected {split_name}.csv inside {split_folder}"
        )

    df = pd.read_csv(input_file)

    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"{input_file.name} is missing columns: {sorted(missing_columns)}"
        )

    if df.empty:
        raise ValueError(f"{input_file} is empty.")

    # Normalize labels and clean whitespace before encoding.
    for column in ["language", "intent", "priority"]:
        df[column] = df[column].astype("string").str.strip().str.lower()

    df["customer_query"] = df["customer_query"].fillna("").astype(str).str.strip()

    if df["customer_query"].eq("").any():
        raise ValueError(f"{input_file.name} contains blank customer queries.")

    if df[["language", "intent", "priority", "escalation_risk"]].isna().any().any():
        raise ValueError(f"{input_file.name} contains missing labels.")

    unknown_intents = sorted(set(df["intent"]) - set(INTENT_MAPPING))
    if unknown_intents:
        raise ValueError(f"Unknown intent labels: {unknown_intents}")

    unknown_priorities = sorted(set(df["priority"]) - set(PRIORITY_MAPPING))
    if unknown_priorities:
        raise ValueError(f"Unknown priority labels: {unknown_priorities}")

    unknown_languages = sorted(set(df["language"]) - VALID_LANGUAGES)
    if unknown_languages:
        raise ValueError(f"Unknown language labels: {unknown_languages}")

    risk = pd.to_numeric(df["escalation_risk"], errors="coerce")
    if risk.isna().any() or not risk.isin([0, 1]).all():
        raise ValueError("escalation_risk must contain only 0 or 1.")
    df["escalation_risk"] = risk.astype(int)

    print(f"Loaded {split_name:10}: {len(df):,} rows from {input_file}")
    return df


def main():
    print("\n========== ML DATA PREPROCESSING ==========\n")

    # 1. Load the three split CSV files.
    data = {split: load_split(split) for split in SPLITS}
    train_df = data["train"]

    # 2. Fit TF-IDF on training queries only.
    # min_df=2 drops rare typos; max_features=1500 keeps X.csv compact.
    tfidf = TfidfVectorizer(
    lowercase=True,
    ngram_range=(1, 2),
    min_df=2,
    max_features=1500,
    sublinear_tf=True,
    dtype=np.float32,
    token_pattern=r"(?<![\w\u0900-\u097F])[\w\u0900-\u097F]{2,}(?![\w\u0900-\u097F])",
)

    train_text_matrix = tfidf.fit_transform(train_df["customer_query"])

    # 3. Learn language categories from training data only.
    language_categories = sorted(train_df["language"].unique().tolist())
    if not language_categories:
        raise ValueError("No language categories found in training data.")

    text_feature_names = [
        f"tfidf_{word}" for word in tfidf.get_feature_names_out()
    ]
    language_feature_names = [
        f"language_{language}" for language in language_categories
    ]

    # 4. Transform each split using the same fitted TF-IDF vocabulary.
    for split in SPLITS:
        df = data[split]

        if split == "train":
            text_matrix = train_text_matrix
        else:
            text_matrix = tfidf.transform(df["customer_query"])

        # One-hot encode language and keep identical columns/order in every split.
        language_matrix = pd.get_dummies(df["language"], dtype=int)
        language_matrix = language_matrix.reindex(
            columns=language_categories, fill_value=0
        )
        language_matrix.columns = language_feature_names

        # X contains only model inputs: TF-IDF features and language indicators.
        text_features = pd.DataFrame(
            text_matrix.toarray(),
            columns=text_feature_names,
            index=df.index,
        )
        X = pd.concat([text_features, language_matrix], axis=1)

        # y contains prediction targets, kept separate from X.
        y = pd.DataFrame(
            {
                "intent": df["intent"].map(INTENT_MAPPING).astype(int),
                "priority": df["priority"].map(PRIORITY_MAPPING).astype(int),
                "escalation_risk": df["escalation_risk"].astype(int),
            },
            index=df.index,
        )

        # Save beside the source split CSV; write exact zeros as "0" to keep CSV small.
        output_folder = SPLIT_DIR / split
        x_file = output_folder / "X.csv"
        y_file = output_folder / "y.csv"

        X_export = X.round(6).astype(object)
        X_export[X == 0] = 0
        X_export.to_csv(x_file, index=False, encoding="utf-8-sig")
        y.to_csv(y_file, index=False)

        size_mb = x_file.stat().st_size / (1024 * 1024)
        print(
            f"Saved {split:10}: X = {X.shape[0]:,} rows x {X.shape[1]:,} features ({size_mb:.2f} MB) | "
            f"y = {y.shape[0]:,} rows x {y.shape[1]} targets"
        )

    # 5. Save readable settings/mappings for reference and future consistency.
    config = {
        "tfidf": {
            "lowercase": True,
            "ngram_range": [1, 2],
            "min_df": 2,
            "max_features": 1500,
            "sublinear_tf": True,
            "vocabulary": {
                word: int(index) for word, index in tfidf.vocabulary_.items()
            },
            "idf": [float(value) for value in tfidf.idf_],
        },
        "language_categories": language_categories,
        "intent_mapping": INTENT_MAPPING,
        "priority_mapping": PRIORITY_MAPPING,
        "input_feature_columns": text_feature_names + language_feature_names,
        "target_columns": ["intent", "priority", "escalation_risk"],
    }

    config_file = SPLIT_DIR / "preprocessing_config.json"
    with config_file.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)

    print("\nChecks:")
    print(f"  TF-IDF vocabulary size: {len(tfidf.vocabulary_):,}")
    print(f"  Language features: {', '.join(language_categories)}")
    print("  X and y saved separately: YES")
    print("  TF-IDF fitted on training data only: YES")
    print("  Validation/test use training TF-IDF vocabulary: YES")

    print(f"\nOutput folder: {SPLIT_DIR}")
    print("Done. Original split CSV files were not modified.")
    print("===========================================\n")


if __name__ == "__main__":
    main()