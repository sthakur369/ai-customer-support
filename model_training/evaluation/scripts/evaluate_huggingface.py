"""
Load data and fine-tune google/muril-base-cased on train.csv and validation.csv.

Reads:
    model_training/data/model_ready_data/ml/train/train.csv
    model_training/data/model_ready_data/ml/validation/validation.csv

Writes:
    model_training/models/model_files/huggingface/best_multitask_model.pt
    model_training/models/model_files/huggingface/model_metadata.json

Run from model_training/:
    python models/scripts/huggingface_finetune.py
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import f1_score
from sklearn.utils.class_weight import compute_class_weight
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup


# --------------------------------------------------
# 1. Project Paths and Settings
# --------------------------------------------------

# Script location: model_training/models/scripts/huggingface_finetune.py
MODEL_TRAINING_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = MODEL_TRAINING_DIR / "data" / "model_ready_data" / "ml"

TRAIN_FILE = DATA_DIR / "train" / "train.csv"
VAL_FILE = DATA_DIR / "validation" / "validation.csv"

MODEL_OUTPUT_DIR = MODEL_TRAINING_DIR / "models" / "model_files" / "huggingface"
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BEST_MODEL_PATH = MODEL_OUTPUT_DIR / "best_multitask_model.pt"
MODEL_META_PATH = MODEL_OUTPUT_DIR / "model_metadata.json"

MODEL_NAME = "google/muril-base-cased"
BATCH_SIZE = 16
MAX_LENGTH = 160
EPOCHS = 10
LEARNING_RATE = 3e-5
SEED = 42

INTENT_LABELS = [
    "order_status", "refund_request", "return_request", "damaged_item",
    "missing_item", "payment_issue", "cancellation", "delivery_delay",
    "product_information", "account_issue", "complaint", "other",
]
PRIORITY_LABELS = ["low", "medium", "high", "urgent"]

INTENT_TO_ID = {label: i for i, label in enumerate(INTENT_LABELS)}
ID_TO_INTENT = {i: label for i, label in enumerate(INTENT_LABELS)}

PRIORITY_TO_ID = {label: i for i, label in enumerate(PRIORITY_LABELS)}
ID_TO_PRIORITY = {i: label for i, label in enumerate(PRIORITY_LABELS)}

LOCAL_FILES_ONLY = True

# --------------------------------------------------
# 2. Data Loading & PyTorch Dataset
# --------------------------------------------------

def load_csv(path):
    """Read CSV and standardize text and label formatting."""
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    df = pd.read_csv(path)
    for col in ["language", "intent", "priority"]:
        df[col] = df[col].astype(str).str.strip().str.lower()
    df["customer_query"] = df["customer_query"].fillna("").astype(str).str.strip()
    df["escalation_risk"] = df["escalation_risk"].astype(int)
    return df


class SupportDataset(Dataset):
    """Converts text queries and labels into token IDs for PyTorch."""

    def __init__(self, df, tokenizer):
        # Prefix query with language tag so MuRIL knows English vs Hindi vs Hinglish
        self.texts = [
            f"[{lang}] {text}"
            for lang, text in zip(df["language"], df["customer_query"])
        ]
        self.intents = df["intent"].map(INTENT_TO_ID).tolist()
        self.priorities = df["priority"].map(PRIORITY_TO_ID).tolist()
        self.escalations = df["escalation_risk"].tolist()
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        encoded = self.tokenizer(
            self.texts[idx],
            truncation=True,
            max_length=MAX_LENGTH,
            padding="max_length",
            return_tensors="pt",
        )
        return {
            "input_ids": encoded["input_ids"].squeeze(0),
            "attention_mask": encoded["attention_mask"].squeeze(0),
            "intent": torch.tensor(self.intents[idx], dtype=torch.long),
            "priority": torch.tensor(self.priorities[idx], dtype=torch.long),
            "escalation": torch.tensor(self.escalations[idx], dtype=torch.long),
        }


# --------------------------------------------------
# 3. Multi-Task Model Architecture
# --------------------------------------------------

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
        self.encoder = AutoModel.from_pretrained(model_name, local_files_only = LOCAL_FILES_ONLY)
        hidden_size = self.encoder.config.hidden_size

        self.intent_head = TaskHead(hidden_size, num_intents)
        self.priority_head = TaskHead(hidden_size, num_priorities)
        self.escalation_head = TaskHead(hidden_size, 2)

    def forward(self, input_ids, attention_mask):
        outputs = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        # Use the [CLS] token vector as the summary representation of the query
        cls_vector = outputs.last_hidden_state[:, 0, :]

        return (
            self.intent_head(cls_vector),
            self.priority_head(cls_vector),
            self.escalation_head(cls_vector),
        )


# --------------------------------------------------
# 4. Training & Validation Functions
# --------------------------------------------------

def get_balanced_weights(labels, num_classes, device):
    """Give higher weight to rare classes (like 'urgent') without destabilizing training."""
    weights = compute_class_weight(
        class_weight="balanced",
        classes=np.arange(num_classes),
        y=np.array(labels),
    )
    weights = np.sqrt(weights)  # Smooth extreme weight so 'urgent' trains stably
    return torch.tensor(weights, dtype=torch.float32, device=device)


@torch.no_grad()
def evaluate_validation(model, val_loader, val_df, device):
    """Check Macro-F1 scores on validation data after each epoch."""
    model.eval()
    intent_preds, priority_preds, esc_preds = [], [], []

    for batch in val_loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)

        i_logits, p_logits, e_logits = model(input_ids, attention_mask)
        intent_preds.extend([ID_TO_INTENT[i.item()] for i in i_logits.argmax(dim=-1)])
        priority_preds.extend([ID_TO_PRIORITY[i.item()] for i in p_logits.argmax(dim=-1)])
        esc_preds.extend(e_logits.argmax(dim=-1).cpu().tolist())

    intent_f1 = f1_score(val_df["intent"], intent_preds, average="macro", zero_division=0)
    priority_f1 = f1_score(val_df["priority"], priority_preds, average="macro", zero_division=0)
    esc_f1 = f1_score(val_df["escalation_risk"], esc_preds, average="macro", zero_division=0)
    return intent_f1, priority_f1, esc_f1


def main():
    torch.manual_seed(SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device_name = "GPU" if device.type == "cuda" else "CPU"
    print(f"\n========== TRAINING MURIL MODEL ({device_name}) ==========")

    # Step 1: Load train and validation CSVs
    train_df = load_csv(TRAIN_FILE)
    val_df = load_csv(VAL_FILE)
    print(f"Loaded {len(train_df)} train rows and {len(val_df)} validation rows.")

    # Step 2: Load tokenizer and pretrained MuRIL model
    load_start = time.perf_counter()
    
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only = LOCAL_FILES_ONLY)
    model = MultiTaskClassifier(MODEL_NAME, len(INTENT_LABELS), len(PRIORITY_LABELS)).to(device)
    print(f"Loaded pretrained model '{MODEL_NAME}' in {time.perf_counter() - load_start:.2f}s")

    train_loader = DataLoader(SupportDataset(train_df, tokenizer), batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(SupportDataset(val_df, tokenizer), batch_size=BATCH_SIZE)

    # Step 3: Set up loss functions, optimizer, and learning rate scheduler
    intent_loss_fn = nn.CrossEntropyLoss()
    priority_loss_fn = nn.CrossEntropyLoss(
        weight=get_balanced_weights(train_df["priority"].map(PRIORITY_TO_ID), len(PRIORITY_LABELS), device)
    )
    esc_loss_fn = nn.CrossEntropyLoss(
        weight=get_balanced_weights(train_df["escalation_risk"], 2, device)
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    total_steps = len(train_loader) * EPOCHS
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(total_steps * 0.1), num_training_steps=total_steps
    )

    # Step 4: Train for EPOCHS and save the best checkpoint
    best_avg_f1 = 0.0
    start_time = time.perf_counter()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0

        for batch in train_loader:
            optimizer.zero_grad()
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)

            i_logits, p_logits, e_logits = model(input_ids, attention_mask)

            # Combine losses from all 3 tasks (1.5x weight helps 12-class intent learn faster)
            loss = (
                1.5 * intent_loss_fn(i_logits, batch["intent"].to(device))
                + priority_loss_fn(p_logits, batch["priority"].to(device))
                + esc_loss_fn(e_logits, batch["escalation"].to(device))
            )

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            total_loss += loss.item()

        # Evaluate on validation set at the end of each epoch
        i_f1, p_f1, e_f1 = evaluate_validation(model, val_loader, val_df, device)
        avg_f1 = (i_f1 + p_f1 + e_f1) / 3.0

        print(
            f"Epoch {epoch:02d}/{EPOCHS} | Loss: {total_loss / len(train_loader):.4f} | "
            f"Val F1 -> Intent: {i_f1*100:.1f}%, Priority: {p_f1*100:.1f}%, Escalation: {e_f1*100:.1f}%"
        )

        if avg_f1 > best_avg_f1:
            best_avg_f1 = avg_f1
            torch.save(model.state_dict(), BEST_MODEL_PATH)
            print("  -> Saved new best model checkpoint.")

    # Step 5: Save metadata so the evaluation script knows the exact labels and settings
    metadata = {
        "model_name": MODEL_NAME,
        "max_length": MAX_LENGTH,
        "epochs": EPOCHS,
        "intent_labels": INTENT_LABELS,
        "priority_labels": PRIORITY_LABELS,
    }
    MODEL_META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n========== TRAINING COMPLETE ==========")
    print(f"Training time:  {time.perf_counter() - start_time:.1f} seconds")
    print(f"Best model:     {BEST_MODEL_PATH}")
    print(f"Metadata file:  {MODEL_META_PATH}")


if __name__ == "__main__":
    main()