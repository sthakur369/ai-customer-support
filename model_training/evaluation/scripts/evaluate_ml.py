"""
Evaluate the saved TF-IDF + Logistic Regression models.

Measures overall, language-wise and class-wise performance, plus inference latency.
This script evaluates existing models only; it does not retrain or modify them.
"""

import pickle
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)


# --------------------------------------------------
# 1. Paths and settings
# --------------------------------------------------

# This script is in model_training/evaluation/scripts/.
MODEL_TRAINING_DIR = Path(__file__).resolve().parents[2]

TEST_DIR = MODEL_TRAINING_DIR / "data" / "model_ready_data" / "ml" / "test"
MODEL_DIR = MODEL_TRAINING_DIR / "models" / "model_files" / "ml"
OUTPUT_DIR = MODEL_TRAINING_DIR / "evaluation" / "results" / "ml"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REPORT_FILE = OUTPUT_DIR / "evaluation.txt"

MODELS = {
    "Intent": {"file": "intent_model.pkl", "target": "intent"},
    "Priority": {"file": "priority_model.pkl", "target": "priority"},
    "Escalation Risk": {
        "file": "escalation_model.pkl",
        "target": "escalation_risk",
    },
}

LANGUAGES = ["english", "hindi", "hinglish"]


# --------------------------------------------------
# 2. Helpers
# --------------------------------------------------

def load_test_data():
    """Load the existing transformed features, labels and original test rows."""

    print("\n[1/3] Loading test data...")

    x_path = TEST_DIR / "X.csv"
    y_path = TEST_DIR / "y.csv"
    original_path = TEST_DIR / "test.csv"

    for path in (x_path, y_path, original_path):
        if not path.exists():
            raise FileNotFoundError(f"Required file not found: {path}")

    X_test = pd.read_csv(x_path)
    y_test = pd.read_csv(y_path)
    original = pd.read_csv(original_path)

    # Remove index columns sometimes added during CSV export.
    X_test = X_test.loc[:, ~X_test.columns.str.startswith("Unnamed:")]
    y_test = y_test.loc[:, ~y_test.columns.str.startswith("Unnamed:")]

    if not (len(X_test) == len(y_test) == len(original)):
        raise ValueError("X.csv, y.csv and test.csv have different row counts.")

    required = {"language", "intent", "priority", "escalation_risk"}
    missing = required - set(original.columns)
    if missing:
        raise ValueError(f"Missing columns in test.csv: {sorted(missing)}")

    languages = original["language"].astype(str).str.strip().str.lower()
    if not languages.isin(LANGUAGES).all():
        raise ValueError("test.csv contains missing or unsupported languages.")

    print(f"Loaded {len(X_test)} test records.")
    return X_test, y_test, original, languages.reset_index(drop=True)


def readable_label_mapping(encoded_labels, original_labels, target):
    """Map encoded labels back to the original readable dataset labels."""

    pairs = pd.DataFrame({
        "encoded": pd.Series(encoded_labels).reset_index(drop=True),
        "readable": pd.Series(original_labels).reset_index(drop=True),
    }).drop_duplicates()

    if pairs.isna().any().any():
        raise ValueError(f"Missing labels found for {target}.")

    if pairs.groupby("encoded")["readable"].nunique().gt(1).any():
        raise ValueError(f"An encoded {target} label maps to multiple labels.")

    if pairs.groupby("readable")["encoded"].nunique().gt(1).any():
        raise ValueError(f"A readable {target} label maps to multiple encoded labels.")

    return pairs.set_index("encoded")["readable"].to_dict()


def top_confusions(actual, predicted, limit=3):
    """Return the most common actual-to-predicted mistakes."""

    errors = pd.DataFrame({"actual": actual, "predicted": predicted})
    errors = errors[errors["actual"] != errors["predicted"]]

    if errors.empty:
        return []

    counts = (
        errors.groupby(["actual", "predicted"])
        .size()
        .sort_values(ascending=False)
        .head(limit)
    )
    return [
        f"{actual} -> {predicted}: {count}"
        for (actual, predicted), count in counts.items()
    ]


def class_metric_lines(y_true, y_pred, label_names):
    """Build readable precision, recall, F1 and support for every class."""

    labels = sorted(set(y_true) | set(y_pred), key=str)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )

    lines = []
    for label, p, r, score, count in zip(
        labels, precision, recall, f1, support
    ):
        readable = label_names.get(label, str(label))
        lines.append(
            f"  {readable}: P {p * 100:.1f}% | R {r * 100:.1f}% | "
            f"F1 {score * 100:.1f}% | Support {int(count)}"
        )
    return lines


# --------------------------------------------------
# 3. Evaluate models and measure latency
# --------------------------------------------------

def evaluate_models(X_test, y_test, original, languages):
    report = [
        "ML MODEL EVALUATION",
        "=" * 62,
        f"Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"Test records: {len(X_test)}",
        "",
        "OVERALL PERFORMANCE",
        "-" * 62,
    ]

    print("\n[2/3] Loading models and evaluating predictions...")

    total_load_seconds = 0.0
    total_inference_seconds = 0.0
    results = {}

    for model_name, config in MODELS.items():
        target = config["target"]
        model_path = MODEL_DIR / config["file"]

        if target not in y_test.columns:
            raise ValueError(f"Target '{target}' is missing from y.csv.")

        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        # Model loading time is reported separately from inference.
        load_start = time.perf_counter()
        with open(model_path, "rb") as model_file:
            model = pickle.load(model_file)
        load_seconds = time.perf_counter() - load_start
        total_load_seconds += load_seconds

        y_true = y_test[target].reset_index(drop=True)

        # Time only prediction on the already-prepared test features.
        inference_start = time.perf_counter()
        y_pred = pd.Series(model.predict(X_test))
        inference_seconds = time.perf_counter() - inference_start
        total_inference_seconds += inference_seconds

        accuracy = accuracy_score(y_true, y_pred)
        macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)

        label_names = readable_label_mapping(
            y_true, original[target], target
        )
        actual_readable = y_true.map(label_names).astype(str)
        predicted_readable = y_pred.map(label_names).astype(str)

        results[target] = {
            "y_true": y_true,
            "y_pred": y_pred,
            "actual_readable": actual_readable,
            "predicted_readable": predicted_readable,
            "label_names": label_names,
        }

        report.extend([
            f"{model_name}: Accuracy {accuracy * 100:.2f}% | "
            f"Macro-F1 {macro_f1 * 100:.2f}%",
        ])
        print(
            f"{model_name}: Accuracy {accuracy * 100:.2f}% | "
            f"Macro-F1 {macro_f1 * 100:.2f}%"
        )

        # Per-language Macro-F1.
        report.append("  Language Macro-F1:")
        for language in LANGUAGES:
            mask = languages == language
            lang_f1 = f1_score(
                y_true[mask],
                y_pred[mask],
                average="macro",
                zero_division=0,
            )
            report.append(f"    {language.title()}: {lang_f1 * 100:.2f}%")

        # Class-wise precision, recall, F1 and support.
        report.append("  Class-wise:")
        report.extend(class_metric_lines(y_true, y_pred, label_names))

    # All three classifiers predict the same 600 records.
    average_latency_ms = (
        total_inference_seconds / len(X_test) * 1000
        if len(X_test) else 0.0
    )
    throughput = (
        len(X_test) / total_inference_seconds
        if total_inference_seconds > 0 else 0.0
    )

    report.extend([
        "",
        "INFERENCE LATENCY",
        "-" * 62,
        f"Total Model Loading Time (3 models): {total_load_seconds:.3f} seconds",
        f"Total Inference Time (3 predictions per record): "
        f"{total_inference_seconds:.3f} seconds",
        f"Average Latency Per Record (all 3 tasks): {average_latency_ms:.3f} ms",
        f"Throughput: {throughput:.2f} records/second",
        "Device: CPU",
        "Note: X.csv contains preprocessed TF-IDF features. This timing covers "
        "the three model predict() calls; TF-IDF transformation is not included.",
        "",
        "ERROR ANALYSIS",
        "-" * 62,
    ])

    for target, result in results.items():
        actual = result["actual_readable"]
        predicted = result["predicted_readable"]
        incorrect = int((actual != predicted).sum())

        report.append(f"{target.replace('_', ' ').title()}:")
        report.append(f"  Incorrect Predictions: {incorrect} / {len(X_test)}")
        confusions = top_confusions(actual, predicted)
        report.append("  Top Confusions:")
        if confusions:
            report.extend(f"    - {item}" for item in confusions)
        else:
            report.append("    None")

        if target == "escalation_risk":
            actual_binary = pd.to_numeric(actual, errors="coerce")
            predicted_binary = pd.to_numeric(predicted, errors="coerce")
            false_positives = int(
                ((actual_binary == 0) & (predicted_binary == 1)).sum()
            )
            false_negatives = int(
                ((actual_binary == 1) & (predicted_binary == 0)).sum()
            )
            report.append(f"  False Positives: {false_positives}")
            report.append(f"  False Negatives: {false_negatives}")

    report.extend([
        "",
        "Note: Test data was used only for final evaluation, not training.",
        "",
        "=" * 62,
        "END OF REPORT",
    ])

    return "\n".join(report), total_load_seconds, total_inference_seconds


def main():
    print("\n========== ML MODEL EVALUATION ==========")

    X_test, y_test, original, languages = load_test_data()
    report, load_time, inference_time = evaluate_models(
        X_test, y_test, original, languages
    )

    print("\n[3/3] Saving evaluation report...")
    REPORT_FILE.write_text(report, encoding="utf-8")

    print("\nEvaluation completed.")
    print(f"Model loading time: {load_time:.3f} seconds")
    print(f"Total inference time: {inference_time:.3f} seconds")
    print(f"Report saved: {REPORT_FILE}")


if __name__ == "__main__":
    main()
