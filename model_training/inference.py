
"""Runtime inference using the configured traditional ML or Hugging Face model."""

import json
import pickle
import re
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.feature_extraction.text import TfidfVectorizer
from transformers import AutoModel, AutoTokenizer

from config.settings import (
    ACTIVE_ML_MODEL,
    HF_MODEL_CHECKPOINT_PATH,
    HF_MODEL_DIR,
    HF_MODEL_METADATA_PATH,
    ML_MODEL_DIR,
    ML_PREPROCESSING_CONFIG,
    PROJECT_ROOT,
)


# --------------------------------------------------
# 1. Hugging Face Model Architecture
# Must match the training architecture exactly.
# --------------------------------------------------

class TaskHead(nn.Module):
    """Classification head for one prediction task."""

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
    """Shared MuRIL encoder with intent, priority and escalation heads."""

    def __init__(self, model_name, num_intents, num_priorities):
        super().__init__()

        self.encoder = AutoModel.from_pretrained(
            model_name,
            local_files_only=True,
        )

        hidden_size = self.encoder.config.hidden_size

        self.intent_head = TaskHead(hidden_size, num_intents)
        self.priority_head = TaskHead(hidden_size, num_priorities)
        self.escalation_head = TaskHead(hidden_size, 2)

    def forward(self, input_ids, attention_mask):
        outputs = self.encoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
        )

        cls_vector = outputs.last_hidden_state[:, 0, :]

        return (
            self.intent_head(cls_vector),
            self.priority_head(cls_vector),
            self.escalation_head(cls_vector),
        )


# --------------------------------------------------
# 2. Traditional ML Model Loading
# --------------------------------------------------

@lru_cache(maxsize=1)
def _artifacts():
    """Load traditional ML models and preprocessing configuration once."""

    print("[INFO] Loading traditional ML models...")

    config = json.loads(
        Path(ML_PREPROCESSING_CONFIG).read_text(encoding="utf-8")
    )

    models = {}

    model_files = {
        "intent": "intent_model.pkl",
        "priority": "priority_model.pkl",
        "escalation_risk": "escalation_model.pkl",
    }

    for task, filename in model_files.items():
        path = Path(ML_MODEL_DIR) / filename

        if not path.exists():
            raise FileNotFoundError(f"ML model not found: {path}")

        with path.open("rb") as file:
            models[task] = pickle.load(file)

    tfidf_cfg = config["tfidf"]

    vectorizer = TfidfVectorizer(
        lowercase=tfidf_cfg["lowercase"],
        ngram_range=tuple(tfidf_cfg["ngram_range"]),
        min_df=tfidf_cfg["min_df"],
        max_features=tfidf_cfg["max_features"],
        sublinear_tf=tfidf_cfg["sublinear_tf"],
        vocabulary=tfidf_cfg["vocabulary"],
        dtype=np.float32,
        token_pattern=(
            r"(?<![\w\u0900-\u097F])"
            r"[\w\u0900-\u097F]{2,}"
            r"(?![\w\u0900-\u097F])"
        ),
    )

    # Initialize sklearn, then restore the IDF values from training.
    vectorizer.fit(["customer support initialization"])
    vectorizer._tfidf.idf_ = np.asarray(
        tfidf_cfg["idf"], dtype=np.float64
    )

    print("[SUCCESS] Traditional ML models loaded.")

    return config, models, vectorizer


# --------------------------------------------------
# 3. Hugging Face Model Loading
# --------------------------------------------------

@lru_cache(maxsize=1)
def _hf_artifacts():
    """Load the fine-tuned MuRIL model and tokenizer once."""

    metadata_path = HF_MODEL_METADATA_PATH
    checkpoint_path = HF_MODEL_CHECKPOINT_PATH

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Hugging Face metadata not found: {metadata_path}"
        )

    if not checkpoint_path.exists():
        from model_training.model_downloader import ensure_hf_model_ready
        ensure_hf_model_ready()

    if not checkpoint_path.exists():
        raise FileNotFoundError(
            f"Hugging Face checkpoint not found: {checkpoint_path}"
        )

    print("[INFO] Loading Hugging Face model...")

    metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    print(f"[INFO] Device: {device}")
    print(f"[INFO] Base model: {metadata['model_name']}")

    # Load the same tokenizer used during training.
    tokenizer = AutoTokenizer.from_pretrained(
        metadata["model_name"],
        local_files_only=True,
    )

    # Recreate the exact multitask architecture.
    model = MultiTaskClassifier(
        metadata["model_name"],
        len(metadata["intent_labels"]),
        len(metadata["priority_labels"]),
    )

    # Load fine-tuned weights.
    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
    )

    model.load_state_dict(checkpoint)
    model.to(device)
    model.eval()

    print("[SUCCESS] Hugging Face model loaded.")
    print(
        "[INFO] Prediction tasks: intent, priority, escalation risk"
    )

    return metadata, tokenizer, model, device


# --------------------------------------------------
# 4. Language Detection
# --------------------------------------------------

def detect_language(text: str) -> str:
    """Detect English, Hindi or Hinglish input."""

    if re.search(r"[\u0900-\u097F]", text):
        return "hindi"

    hinglish_markers = {
        "hai", "hain", "mera", "meri", "mujhe",
        "nahi", "karna", "please", "order", "ka", "ki",
    }

    words = set(re.findall(r"[a-z]+", text.lower()))

    return (
        "hinglish"
        if len(words & hinglish_markers) >= 2
        else "english"
    )


# --------------------------------------------------
# 5. Traditional ML Prediction
# --------------------------------------------------

def _predict_traditional_ml(query: str, language: str):
    """Generate predictions using the three traditional ML models."""

    config, models, vectorizer = _artifacts()

    text_features = vectorizer.transform([query]).toarray()

    language_categories = config["language_categories"]

    language_features = np.asarray([
        [int(language == item) for item in language_categories]
    ])

    feature_values = np.hstack([
        text_features,
        language_features,
    ])

    feature_frame = pd.DataFrame(
        feature_values,
        columns=config["input_feature_columns"],
    )

    labels = {
        "intent": {
            v: k for k, v in config["intent_mapping"].items()
        },
        "priority": {
            v: k for k, v in config["priority_mapping"].items()
        },
        "escalation_risk": {0: 0, 1: 1},
    }

    predictions = {}

    for task, model in models.items():
        prediction = int(model.predict(feature_frame)[0])

        probabilities = model.predict_proba(feature_frame)[0]
        confidence = float(np.max(probabilities))

        predictions[task] = {
            "label": labels[task][prediction],
            "confidence": round(confidence, 4),
        }

    return predictions


# --------------------------------------------------
# 6. Hugging Face Prediction
# --------------------------------------------------

def _predict_huggingface(query: str):
    """Generate predictions using the fine-tuned MuRIL model."""

    metadata, tokenizer, model, device = _hf_artifacts()

    # Use the original query, exactly as during training.
    encoded = tokenizer(
        query,
        truncation=True,
        max_length=metadata["max_length"],
        padding="max_length",
        return_tensors="pt",
    )

    encoded = {
        key: value.to(device)
        for key, value in encoded.items()
    }

    with torch.inference_mode():
        intent_logits, priority_logits, escalation_logits = model(
            encoded["input_ids"],
            encoded["attention_mask"],
        )

        intent_probs = torch.softmax(intent_logits, dim=-1)[0]
        priority_probs = torch.softmax(priority_logits, dim=-1)[0]
        escalation_probs = torch.softmax(escalation_logits, dim=-1)[0]

    intent_conf, intent_idx = intent_probs.max(dim=-1)
    priority_conf, priority_idx = priority_probs.max(dim=-1)
    escalation_conf, escalation_idx = escalation_probs.max(dim=-1)

    return {
        "intent": {
            "label": metadata["intent_labels"][intent_idx.item()],
            "confidence": round(intent_conf.item(), 4),
        },
        "priority": {
            "label": metadata["priority_labels"][priority_idx.item()],
            "confidence": round(priority_conf.item(), 4),
        },
        "escalation_risk": {
            "label": escalation_idx.item(),
            "confidence": round(escalation_conf.item(), 4),
        },
    }


# --------------------------------------------------
# 7. Main Prediction Function
# --------------------------------------------------

def predict_query(query: str) -> tuple[dict, float]:
    """
    Run inference using the model selected in settings/.env.

    Both model types return the same prediction structure.
    The rest of the application does not need to know
    which model is being used.
    """

    started = time.perf_counter()

    language = detect_language(query)

    if ACTIVE_ML_MODEL == "traditional_ml":
        print("[INFO] Running inference: Traditional ML")
        predictions = _predict_traditional_ml(query, language)

    elif ACTIVE_ML_MODEL == "huggingface":
        print("[INFO] Running inference: Hugging Face")
        predictions = _predict_huggingface(query)

    else:
        raise ValueError(
            f"Unsupported ACTIVE_ML_MODEL: {ACTIVE_ML_MODEL!r}. "
            "Choose 'traditional_ml' or 'huggingface'."
        )

    latency = round(time.perf_counter() - started, 4)

    output = {
        "language": language,
        "model_id": ACTIVE_ML_MODEL,
        "predictions": predictions,
        "latency_seconds": latency,
    }

    print(
        f"[SUCCESS] {ACTIVE_ML_MODEL} predictions completed "
        f"in {latency:.4f}s"
    )

    return output, latency
