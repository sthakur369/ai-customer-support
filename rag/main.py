"""RAG maintenance CLI. Use the repository-root api.py to start the web application."""
import argparse
import time

from config.settings import PDF_DIR
from rag.ingestion.pdf_reader import read_pdfs
from rag.chunking.chunker import chunk_documents
from rag.embeddings.embedder import load_embedding_model, embed_documents
from rag.data_preparation.vector_db.chroma_store import get_collection, rebuild_collection, upsert_chunks


def ingest_documents(rebuild: bool = False) -> dict:
    started = time.perf_counter()
    print("[RAG] Reading policy PDFs...")
    documents = read_pdfs(PDF_DIR)
    if not documents:
        raise RuntimeError(f"No policy PDFs found in {PDF_DIR}. Restore the PDF files before ingestion.")
    chunks = chunk_documents(documents)
    model = load_embedding_model()
    embeddings = embed_documents(model, chunks)
    collection = rebuild_collection() if rebuild else get_collection()
    upsert_chunks(collection, chunks, embeddings)
    result = {
        "status": "INGESTED", "documents": len(documents), "chunks": len(chunks),
        "latency_seconds": round(time.perf_counter() - started, 4),
    }
    print(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG knowledge-base maintenance")
    parser.add_argument("--ingest", action="store_true", help="Ingest policy PDFs into ChromaDB")
    parser.add_argument("--rebuild", action="store_true", help="Recreate the ChromaDB collection before ingestion")
    args = parser.parse_args()
    if args.rebuild and not args.ingest:
        parser.error("--rebuild requires --ingest")
    if not args.ingest:
        parser.print_help()
        return
    ingest_documents(rebuild=args.rebuild)

if __name__ == "__main__":
    main()
