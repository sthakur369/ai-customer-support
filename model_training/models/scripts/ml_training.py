"""
Train three Logistic Regression models using the prepared ML CSV files.

Reads only train and validation X.csv/y.csv.
The test split is deliberately left untouched for final evaluation.
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score


# Script location: model_training/models/ml_training.py
BASE_DIR = Path(__file__).resolve().parents[1]  # model_training/
DATA_DIR = BASE_DIR / "data" / "model_ready_data" / "ml"
MODEL_DIR = BASE_DIR / "models" / "model_files"
EVALUATION_DIR = BASE_DIR / "evaluation" / "results" / "ml"

RANDOM_STATE = 42
MAX_ITERATIONS = 2000

# These numeric mappings must match ml_preprocessing.py.
TASKS = {
    "intent": {
        "labels": list(range(12)),
        "names": [
            "order_status", "refund_request", "return_request", "damaged_item",
            "missing_item", "payment_issue", "cancellation", "delivery_delay",
            "product_information", "account_issue", "complaint", "other",
        ],
        "model_file": "intent_model.pkl",
    },
    "priority": {
        "labels": [0, 1, 2, 3],
        "names": ["low", "medium", "high", "urgent"],
        "model_file": "priority_model.pkl",
    },
    "escalation_risk": {
        "labels": [0, 1],
        "names": ["normal (0)", "escalation risk (1)"],
        "model_file": "escalation_model.pkl",
    },
}


def load_split(split_name, expected_columns=None):
    """Load X and y for one split and validate them."""
    folder = DATA_DIR / split_name
    x_path = folder / "X.csv"
    y_path = folder / "y.csv"

    if not x_path.exists() or not y_path.exists():
        raise FileNotFoundError(
            f"Missing X.csv or y.csv in {folder}. "
            "Run ml_preprocessing.py first."
        )

    X = pd.read_csv(x_path)
    y = pd.read_csv(y_path)

    if X.empty or y.empty:
        raise ValueError(f"{split_name}: X.csv or y.csv is empty.")
    if len(X) != len(y):
        raise ValueError(f"{split_name}: X and y row counts do not match.")

    if expected_columns is not None and list(X.columns) != expected_columns:
        raise ValueError(f"{split_name}: feature columns/order differ from training.")

    X = X.apply(pd.to_numeric, errors="coerce")
    if X.isna().any().any():
        raise ValueError(f"{split_name}: X.csv contains missing/non-numeric values.")
    if not np.isfinite(X.to_numpy(dtype=np.float64)).all():
        raise ValueError(f"{split_name}: X.csv contains infinite values.")

    required_targets = list(TASKS)
    missing = set(required_targets) - set(y.columns)
    if missing:
        raise ValueError(f"{split_name}: y.csv is missing {sorted(missing)}.")

    for target, settings in TASKS.items():
        values = pd.to_numeric(y[target], errors="coerce")
        if values.isna().any():
            raise ValueError(f"{split_name}: target '{target}' has invalid values.")
        y[target] = values.astype(int)

        unexpected = set(y[target].unique()) - set(settings["labels"])
        if unexpected:
            raise ValueError(
                f"{split_name}: unexpected values for '{target}': {sorted(unexpected)}"
            )

    print(f"Loaded {split_name:10}: X {X.shape}, y {y.shape}")
    return X, y


def evaluate_model(task, settings, y_true, y_pred, train_true, train_pred):
    """Save class-wise report and confusion matrix; return summary metrics."""
    labels = settings["labels"]
    names = settings["names"]

    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=names,
        output_dict=True,
        zero_division=0,
    )
    pd.DataFrame(report).transpose().to_csv(
        EVALUATION_DIR / f"{task}_classification_report.csv"
    )

    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    pd.DataFrame(
        matrix,
        index=[f"actual_{name}" for name in names],
        columns=[f"predicted_{name}" for name in names],
    ).to_csv(EVALUATION_DIR / f"{task}_confusion_matrix.csv")

    return {
        "training_accuracy": float(accuracy_score(train_true, train_pred)),
        "training_macro_f1": float(
            f1_score(train_true, train_pred, labels=labels, average="macro", zero_division=0)
        ),
        "validation_accuracy": float(accuracy_score(y_true, y_pred)),
        "validation_macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
    }, report


def main():
    print("\n========== ML MODEL TRAINING ==========\n")

    # Load training and validation only. Never load test data during tuning.
    X_train, y_train = load_split("train")
    X_validation, y_validation = load_split(
        "validation", expected_columns=list(X_train.columns)
    )

    if not X_train.index.equals(y_train.index):
        raise ValueError("Training X/y row alignment check failed.")
    if not X_validation.index.equals(y_validation.index):
        raise ValueError("Validation X/y row alignment check failed.")

    print(f"Training features:   {X_train.shape[0]:,} rows x {X_train.shape[1]:,} columns")
    print(f"Validation features: {X_validation.shape[0]:,} rows x {X_validation.shape[1]:,} columns")
    print("Test data:           NOT loaded (reserved for final evaluation)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)

    all_metrics = {}

    # Train one independent classifier for each prediction target.
    for task, settings in TASKS.items():
        print(f"\n--- Training {task} model ---")

        model = LogisticRegression(
            solver="lbfgs",
            max_iter=MAX_ITERATIONS,
            random_state=RANDOM_STATE,
            class_weight="balanced",  # First run: unweighted baseline.
        )
        model.fit(X_train, y_train[task])

        train_predictions = model.predict(X_train)
        validation_predictions = model.predict(X_validation)

        metrics, report = evaluate_model(
            task,
            settings,
            y_validation[task],
            validation_predictions,
            y_train[task],
            train_predictions,
        )
        all_metrics[task] = metrics

        # Save the trained scikit-learn model as a pickle file.
        model_path = MODEL_DIR / settings["model_file"]
        with model_path.open("wb") as file:
            pickle.dump(model, file)

        print(f"Training accuracy:   {metrics['training_accuracy']:.4f}")
        print(f"Training Macro-F1:   {metrics['training_macro_f1']:.4f}")
        print(f"Validation accuracy: {metrics['validation_accuracy']:.4f}")
        print(f"Validation Macro-F1: {metrics['validation_macro_f1']:.4f}")
        print("Validation per-class recall:")
        for class_name in settings["names"]:
            if class_name in report:
                print(f"  {class_name:24} {report[class_name]['recall']:.3f}")
        print(f"Saved model: {model_path}")

    # Save one readable summary of validation metrics.
    metrics_path = EVALUATION_DIR / "validation_metrics.json"
    with metrics_path.open("w", encoding="utf-8") as file:
        json.dump(all_metrics, file, indent=2)

    print("\n========== TRAINING COMPLETE ==========")
    print(f"Models:     {MODEL_DIR}")
    print(f"Evaluation: {EVALUATION_DIR}")
    print("Test data was not used.")
    print("=======================================\n")


if __name__ == "__main__":
    main()
