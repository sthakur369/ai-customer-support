"""RAG retrieval and reranking only; answer generation lives in the LLM layer."""
import time
from functools import lru_cache

from config.settings import (
    MANIFEST_PATH, RAG_ENABLED, VECTOR_TOP_K, MAX_CONTEXT_CHARS,
)

@lru_cache(maxsize=1)
def load_document_catalog() -> list[dict]:
    import json
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    catalog = []
    for doc_id, item in data.get("documents", {}).items():
        brief = item.get("brief", "")
        catalog.append({
            "document_id": doc_id,
            "title": item.get("title", "Untitled"),
            "description": " ".join(brief.split())[:240],
            "status": item.get("status", "unknown"),
        })
    return catalog

@lru_cache(maxsize=1)
def load_rag_runtime():
    if not RAG_ENABLED:
        return None
    from rag.embeddings.embedder import load_embedding_model
    from rag.data_preparation.vector_db.chroma_store import get_collection
    from rag.reranker.reranker import load_reranker
    embedding_model = load_embedding_model()
    reranker = load_reranker()
    collection = get_collection()
    return embedding_model, reranker, collection

def retrieve_and_rerank(question: str, relevant_ids: list[str] | None = None,
                        search_query: str | None = None) -> tuple[dict, float]:
    started = time.perf_counter()
    if not RAG_ENABLED:
        return {"status": "DISABLED", "chunks": [], "evidence": []}, round(time.perf_counter()-started, 4)
    if relevant_ids is not None and not relevant_ids:
        print("[INFO] Router selected no document IDs; skipping unrestricted vector search.")
        return {"status": "NO_RELEVANT_DOCUMENTS", "chunks": [], "evidence": []}, round(time.perf_counter()-started, 4)
    from rag.embeddings.embedder import embed_query
    from rag.retrieval.retriever import search_vectors, asks_for_history
    from rag.reranker.reranker import rerank_documents
    embedding_model, reranker, collection = load_rag_runtime()
    if collection.count() == 0:
        return {"status": "KNOWLEDGE_BASE_EMPTY", "chunks": [], "evidence": []}, round(time.perf_counter()-started, 4)
    # Router supplies an English semantic query for Hindi/Hinglish input.
    # Reranking still uses the original customer wording.
    embedding = embed_query(embedding_model, search_query or question)
    candidates = search_vectors(
        collection, embedding, VECTOR_TOP_K,
        include_historical=asks_for_history(question),
        document_ids=relevant_ids or None,
    )
    ranked = rerank_documents(reranker, search_query or question, candidates)
    chunks, evidence, used = [], [], 0
    print(
        f"[INFO] Retrieval window: vector top-k={VECTOR_TOP_K}; "
        f"reranker top-k={len(ranked)}; context budget={MAX_CONTEXT_CHARS} characters."
    )
    for doc in ranked:
        metadata = doc.get("metadata") or {}
        text = str(doc.get("text", ""))
        if used + len(text) > MAX_CONTEXT_CHARS:
            continue
        used += len(text)
        chunks.append({"text": text, "metadata": metadata, "rerank_score": round(float(doc.get("rerank_score", 0)), 4)})
        evidence.append({
            "document_id": metadata.get("document_id"),
            "source": metadata.get("source"),
            "version": metadata.get("version"),
            "status": metadata.get("status"),
            "page": metadata.get("page"),
            "section": metadata.get("section"),
            "effective_date": metadata.get("effective_date"),
            "rerank_score": round(float(doc.get("rerank_score", 0)), 4),
            "excerpt": " ".join(text.split())[:500],
        })
    print(f"[SUCCESS] Passing {len(chunks)} reranked chunks to the answer stage ({used}/{MAX_CONTEXT_CHARS} context characters).")
    return {"status": "SUCCESS" if chunks else "NO_RESULTS", "chunks": chunks, "evidence": evidence}, round(time.perf_counter()-started, 4)
