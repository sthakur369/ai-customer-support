"""Persistent ChromaDB collection helpers."""

import chromadb
from config.settings import CHROMA_DIR, COLLECTION_NAME


def get_client():
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection():
    client = get_client()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"[SUCCESS] ChromaDB collection ready: {COLLECTION_NAME}")
    return collection


def rebuild_collection():
    """Explicitly recreate the collection to remove stale chunks/metadata."""
    client = get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"[INFO] Deleted old collection: {COLLECTION_NAME}")
    except Exception as exc:
        # Chroma raises when collection does not exist; create below.
        if "does not exist" not in str(exc).lower() and "not found" not in str(exc).lower():
            raise
    return get_collection()


def upsert_chunks(collection, chunks: list[dict], embeddings: list[list[float]]):
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk and embedding counts do not match.")

    ids, texts, metadatas = [], [], []
    for chunk in chunks:
        metadata = chunk["metadata"]
        identity = "|".join([
            str(metadata.get("document_id", metadata.get("source", "unknown"))),
            str(metadata.get("page", 0)),
            str(metadata.get("section", "General")),
            chunk["text"],
        ])
        ids.append("chunk_" + __import__("hashlib").sha256(identity.encode("utf-8")).hexdigest())
        texts.append(chunk["text"])
        metadatas.append(metadata)

    collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)
    print(f"[SUCCESS] Stored/updated {len(chunks)} chunks in ChromaDB.")
