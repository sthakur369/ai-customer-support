"""Central configuration for the customer support application."""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Active ML model family. Available: traditional_ml, huggingface.
ACTIVE_ML_MODEL = os.getenv("ML_MODEL", "traditional_ml").strip().lower()
ML_MODEL_DIR = PROJECT_ROOT / "model_training" / "models" / "model_files" / "ml"
ML_PREPROCESSING_CONFIG = PROJECT_ROOT / "model_training" / "data" / "model_ready_data" / "ml" / "preprocessing_config.json"
ML_INTERVENTION_CONFIDENCE_THRESHOLD = float(os.getenv("ML_INTERVENTION_CONFIDENCE_THRESHOLD", "0.55"))

# Hugging Face model settings & Google Drive download configuration
HF_MODEL_DIR = PROJECT_ROOT / "model_training" / "models" / "model_files" / "huggingface"
HF_MODEL_CHECKPOINT_PATH = HF_MODEL_DIR / "best_multitask_model.pt"
HF_MODEL_METADATA_PATH = HF_MODEL_DIR / "model_metadata.json"
HF_MODEL_GDRIVE_FILE_ID = os.getenv("HF_MODEL_GDRIVE_FILE_ID", "1YENy2EWd03IfDqnxroC87OSFawpZ2mzC").strip()
HF_MODEL_GDRIVE_URL = os.getenv(
    "HF_MODEL_GDRIVE_URL",
    "https://drive.google.com/file/d/1YENy2EWd03IfDqnxroC87OSFawpZ2mzC/view?usp=sharing",
).strip()

# LLM provider/model settings.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1").strip()
REFUND_APPROVAL_THRESHOLD = float(os.getenv("REFUND_APPROVAL_THRESHOLD", "5000"))

# RAG settings.
RAG_ENABLED = os.getenv("RAG_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
RAG_DIR = PROJECT_ROOT / "rag"
PDF_DIR = RAG_DIR / "data" / "generated_files"
CHROMA_DIR = RAG_DIR / "data" / "chroma_db"
MANIFEST_PATH = PDF_DIR / "documents_manifest.json"
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "support_knowledge_base")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
VECTOR_TOP_K = int(os.getenv("VECTOR_TOP_K", "10"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "5"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
MODEL_OFFLINE = os.getenv("MODEL_OFFLINE", "1").strip().lower() not in {"0", "false", "no"}
if MODEL_OFFLINE:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Security and response limits.
MAX_QUERY_LENGTH = int(os.getenv("MAX_QUERY_LENGTH", "4000"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "14000"))

