"""Metadata-aware vector retrieval."""

from config.settings import VECTOR_TOP_K

HISTORY_TERMS = (
    "historical", "history", "previous policy", "old policy",
    "superseded", "prior version", "version 1", "before ",
)


def search_vectors(
    collection,
    query_embedding: list[float],
    top_k: int = VECTOR_TOP_K,
    include_historical: bool = False,
    document_ids: list[str] | None = None,
) -> list[dict]:
    """Default to current documents; include historical only when requested."""
    query_args = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    filters = []
    if not include_historical:
        filters.append({"status": {"$eq": "current"}})
    if document_ids:
        filters.append({"document_id": {"$in": document_ids}})
    if len(filters) == 1:
        query_args["where"] = filters[0]
    elif filters:
        query_args["where"] = {"$and": filters}

    results = collection.query(**query_args)
    documents = []
    if not results.get("documents") or not results["documents"][0]:
        print("[INFO] No matching chunks found.")
        return documents

    for text, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        metadata = metadata or {}
        # Defensive filter for older records whose metadata is incomplete.
        if not include_historical and metadata.get("status", "").lower() != "current":
            continue
        documents.append({"text": text, "metadata": metadata, "distance": distance})

    print(f"[SUCCESS] Retrieved {len(documents)} current chunks.")
    return documents


def asks_for_history(question: str) -> bool:
    normalized = question.lower()
    return any(term in normalized for term in HISTORY_TERMS)
