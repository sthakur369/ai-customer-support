"""Generate embeddings with one cached, optionally offline model instance."""

from functools import lru_cache
from sentence_transformers import SentenceTransformer
from config.settings import EMBEDDING_MODEL, MODEL_OFFLINE


@lru_cache(maxsize=1)
def load_embedding_model():
    print(f"[INFO] Loading embedding model once: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=MODEL_OFFLINE)
    print("[SUCCESS] Embedding model loaded and cached.")
    return model


def embed_documents(model, chunks: list[dict]) -> list[list[float]]:
    texts = [chunk["text"] for chunk in chunks]
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
    print(f"[SUCCESS] Generated embeddings for {len(texts)} chunks.")
    return embeddings.tolist()


def embed_query(model, query: str) -> list[float]:
    return model.encode(query, convert_to_numpy=True).tolist()
