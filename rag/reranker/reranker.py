"""Rerank retrieved documents with one cached CrossEncoder instance."""

from functools import lru_cache
from sentence_transformers import CrossEncoder
from config.settings import RERANKER_MODEL, RERANK_TOP_K, MODEL_OFFLINE


@lru_cache(maxsize=1)
def load_reranker():
    print(f"[INFO] Loading reranker once: {RERANKER_MODEL}")
    # Transformers offline environment variables are set in config.settings.
    model = CrossEncoder(
        RERANKER_MODEL,
        model_kwargs={"local_files_only": MODEL_OFFLINE},
    )
    print("[SUCCESS] Reranker loaded and cached.")
    return model


def rerank_documents(model, query: str, documents: list[dict]) -> list[dict]:
    if not documents:
        print("[INFO] No documents to rerank.")
        return []
    pairs = [(query, doc["text"]) for doc in documents]
    scores = model.predict(pairs)
    for document, score in zip(documents, scores):
        document["rerank_score"] = float(score)
    documents.sort(key=lambda doc: doc["rerank_score"], reverse=True)
    results = documents[:RERANK_TOP_K]
    print(
        f"[SUCCESS] Reranked {len(documents)} candidates; "
        f"selected top {len(results)} (RERANK_TOP_K={RERANK_TOP_K})."
    )
    return results
