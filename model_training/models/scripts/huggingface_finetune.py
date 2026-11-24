"""
Load the fine-tuned MuRIL model and evaluate it on held-out test.csv.

Reads:
    model_training/models/model_files/huggingface/best_multitask_model.pt
    model_training/models/model_files/huggingface/model_metadata.json
    model_training/data/model_ready_data/ml/test/test.csv

Writes:
    model_training/evaluation/results/huggingface/test_predictions.csv
    model_training/evaluation/results/huggingface/evaluation.txt

Run from model_training/:
    python evaluation/scripts/evaluate_huggingface.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer


# --------------------------------------------------
# 1. Project Paths and Settings
# --------------------------------------------------

# Script location: model_training/evaluation/scripts/evaluate_huggingface.py
MODEL_TRAINING_DIR = Path(__file__).resolve().parents[2]

TEST_FILE = MODEL_TRAINING_DIR / "data" / "model_ready_data" / "ml" / "test" / "test.csv"

MODEL_DIR = MODEL_TRAINING_DIR / "models" / "model_files" / "huggingface"
BEST_MODEL_PATH = MODEL_DIR / "best_multitask_model.pt"
MODEL_META_PATH = MODEL_DIR / "model_metadata.json"

RESULTS_DIR = MODEL_TRAINING_DIR / "evaluation" / "results" / "huggingface"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PREDICTIONS_FILE = RESULTS_DIR / "test_predictions.csv"
REPORT_FILE = RESULTS_DIR / "evaluation.txt"

BATCH_SIZE = 16
LANGUAGES = ["english", "hindi", "hinglish"]


# --------------------------------------------------
# 2. Dataset & Model Architecture (Must match training)
# --------------------------------------------------

class TestDataset(Dataset):
    """Tokenizes test queries for prediction."""

    def __init__(self, texts, tokenizer, max_length):
        self.texts = texts
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        encoded = self.tokenizer(
            self.texts[idx],
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        return {
            "input_ids": encoded["input_ids"].squeeze(0),
            "attention_mask": encoded["attention_mask"].squeeze(0),
        }


class TaskHead(nn.Module):
    """Small neural network head for one classification task."""

    def __init__(self, hidden_size, num_classes):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(hidden_size, 256),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(256, num_classes),
        )

    def forward(self, x):
        return self.layers(x)


class MultiTaskClassifier(nn.Module):
    """Shared MuRIL encoder with 3 independent classification heads."""

    def __init__(self, model_name, num_intents, num_priorities):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(model_name)
        hidden_size = self.encoder.config.hidden_size

        self.intent_head = TaskHead(hidden_size, num_intents)
        self.priority_head = TaskHead(hidden_size, num_priorities)
        self.escalation_head = TaskHead(hidden_size, 2)

    def forward(self, input_ids, attention_mask):
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls_vector = outputs.last_hidden_state[:, 0, :]

        return (
            self.intent_head(cls_vector),
            self.priority_head(cls_vector),
            self.escalation_head(cls_vector),
        )


# --------------------------------------------------
# 3. Prediction & Report Helpers
# --------------------------------------------------

@torch.no_grad()
def run_predictions(model, loader, id_to_intent, id_to_priority, device):
    """Predict labels and confidence scores for all test queries."""
    model.eval()
    results = {
        "intent": ([], []),
        "priority": ([], []),
        "escalation_risk": ([], []),
    }

    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)

        i_logits, p_logits, e_logits = model(input_ids, attention_mask)

        i_probs = torch.softmax(i_logits, dim=-1)
        p_probs = torch.softmax(p_logits, dim=-1)
        e_probs = torch.softmax(e_logits, dim=-1)

        i_conf, i_idx = i_probs.max(dim=-1)
        p_conf, p_idx = p_probs.max(dim=-1)
        e_conf, e_idx = e_probs.max(dim=-1)

        results["intent"][0].extend([id_to_intent[i.item()] for i in i_idx])
        results["intent"][1].extend(i_conf.cpu().tolist())

        results["priority"][0].extend([id_to_priority[i.item()] for i in p_idx])
        results["priority"][1].extend(p_conf.cpu().tolist())

        results["escalation_risk"][0].extend(e_idx.cpu().tolist())
        results["escalation_risk"][1].extend(e_conf.cpu().tolist())

    return results


def build_report(df, predictions, meta, load_sec, infer_sec, device_name):
    """Build a clean text report of accuracy, F1, latency, and top mistakes."""
    lines = [
        "HUGGING FACE MODEL EVALUATION",
        "=" * 60,
        f"Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"Model: {meta['model_name']} ({meta['epochs']} epochs)",
        f"Test records: {len(df)}",
        "",
        "OVERALL PERFORMANCE",
        "-" * 60,
    ]

    for target in ["intent", "priority", "escalation_risk"]:
        actual = df[target]
        pred = pd.Series(predictions[target])

        acc = accuracy_score(actual, pred) * 100
        macro_f1 = f1_score(actual, pred, average="macro", zero_division=0) * 100
        lines.append(f"{target.replace('_', ' ').title()}: Accuracy {acc:.2f}% | Macro-F1 {macro_f1:.2f}%")

        # Language breakdown
        lines.append("  Language Macro-F1:")
        for lang in LANGUAGES:
            mask = df["language"] == lang
            lang_f1 = f1_score(actual[mask], pred[mask], average="macro", zero_division=0) * 100
            lines.append(f"    {lang.title()}: {lang_f1:.2f}%")

        # Per-class metrics
        labels = sorted(set(actual) | set(pred), key=str)
        prec, rec, f1, sup = precision_recall_fscore_support(actual, pred, labels=labels, zero_division=0)
        lines.append("  Class-wise:")
        for lbl, p, r, s, count in zip(labels, prec, rec, f1, sup):
            lines.append(f"    {lbl}: P {p*100:.1f}% | R {r*100:.1f}% | F1 {s*100:.1f}% | Support {int(count)}")

    avg_ms = (infer_sec / len(df)) * 1000
    lines.extend([
        "",
        "INFERENCE LATENCY",
        "-" * 60,
        f"Model Loading Time: {load_sec:.2f} seconds",
        f"Total Inference Time: {infer_sec:.2f} seconds ({avg_ms:.2f} ms/record)",
        f"Device: {device_name}",
        "",
        "TOP MISTAKES",
        "-" * 60,
    ])

    for target in ["intent", "priority", "escalation_risk"]:
        actual = df[target].astype(str)
        pred = pd.Series(predictions[target]).astype(str)
        mistakes = pd.DataFrame({"actual": actual, "pred": pred})
        mistakes = mistakes[mistakes["actual"] != mistakes["pred"]]

        lines.append(f"{target.replace('_', ' ').title()}: {len(mistakes)} / {len(df)} wrong")
        top3 = mistakes.groupby(["actual", "pred"]).size().sort_values(ascending=False).head(3)
        for (a, p), count in top3.items():
            lines.append(f"  - {a} -> {p}: {count}")

    lines.extend(["", "=" * 60, "END OF REPORT"])
    return "\n".join(lines)


# --------------------------------------------------
# 4. Main Evaluation Flow
# --------------------------------------------------

def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device_name = "GPU" if device.type == "cuda" else "CPU"
    print(f"\n========== EVALUATING MODEL ({device_name}) ==========")

    if not TEST_FILE.exists():
        raise FileNotFoundError(f"Test dataset not found: {TEST_FILE}")
    if not BEST_MODEL_PATH.exists():
        raise FileNotFoundError(f"Trained model not found: {BEST_MODEL_PATH}")
    if not MODEL_META_PATH.exists():
        raise FileNotFoundError(f"Model metadata not found: {MODEL_META_PATH}")

    # Step 1: Load metadata and test CSV
    meta = json.loads(MODEL_META_PATH.read_text(encoding="utf-8"))
    id_to_intent = {i: label for i, label in enumerate(meta["intent_labels"])}
    id_to_priority = {i: label for i, label in enumerate(meta["priority_labels"])}

    df = pd.read_csv(TEST_FILE)
    for col in ["language", "intent", "priority"]:
        df[col] = df[col].astype(str).str.strip().str.lower()
    df["customer_query"] = df["customer_query"].fillna("").astype(str).str.strip()
    df["escalation_risk"] = df["escalation_risk"].astype(int)
    print(f"Loaded {len(df)} test records.")

    # Step 2: Load tokenizer and fine-tuned model weights
    load_start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(meta["model_name"])
    model = MultiTaskClassifier(
        meta["model_name"], len(meta["intent_labels"]), len(meta["priority_labels"])
    )
    model.load_state_dict(torch.load(BEST_MODEL_PATH, map_location=device))
    model.to(device)
    load_sec = time.perf_counter() - load_start
    print(f"Fine-tuned model loaded in {load_sec:.2f} seconds.")

    # Step 3: Run predictions on test set
    texts = [f"[{lang}] {q}" for lang, q in zip(df["language"], df["customer_query"])]
    test_loader = DataLoader(TestDataset(texts, tokenizer, meta["max_length"]), batch_size=BATCH_SIZE)

    infer_start = time.perf_counter()
    outputs = run_predictions(model, test_loader, id_to_intent, id_to_priority, device)
    infer_sec = time.perf_counter() - infer_start

    # Step 4: Save predictions CSV and evaluation report TXT
    predictions = {}
    results_df = df.copy()
    for target in ["intent", "priority", "escalation_risk"]:
        preds, scores = outputs[target]
        predictions[target] = preds
        results_df[f"{target}_predicted"] = preds
        results_df[f"{target}_score"] = scores

    results_df.to_csv(PREDICTIONS_FILE, index=False, encoding="utf-8-sig")

    report = build_report(df, predictions, meta, load_sec, infer_sec, device_name)
    REPORT_FILE.write_text(report, encoding="utf-8")

    print("\n========== EVALUATION COMPLETE ==========")
    print(f"Predictions saved to: {PREDICTIONS_FILE}")
    print(f"Report saved to:      {REPORT_FILE}\n")
    print(report)


if __name__ == "__main__":
    main()