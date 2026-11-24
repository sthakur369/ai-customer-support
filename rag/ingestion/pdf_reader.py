"""Read PDFs and attach authoritative document metadata from the manifest."""

import json
import re
from pathlib import Path

import pymupdf4llm

MANIFEST_NAME = "documents_manifest.json"


def _load_manifest(pdf_dir: Path) -> dict:
    path = pdf_dir / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("documents", {})
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read document manifest: {path}") from exc


def _header_metadata(text: str) -> dict:
    """Fallback extraction for PDFs whose manifest entry is absent."""
    patterns = {
        "document_id": r"Document\s*ID\s*[:|]\s*(KB-[A-Z0-9-]+)",
        "version": r"Version\s*[:|]\s*([0-9]+(?:\.[0-9]+)*)",
        "status": r"Status\s*[:|]\s*(CURRENT|SUPERSEDED|HISTORICAL|DRAFT)",
        "effective_date": r"Effective(?:\s+Date)?\s*[:|]\s*(\d{4}-\d{2}-\d{2})",
        "owner": r"Owner\s*[:|]\s*([^|\n]+)",
    }
    found = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found[key] = match.group(1).strip()
    if "status" in found:
        found["status"] = found["status"].lower()
    return found


def read_pdfs(pdf_dir: Path) -> list[dict]:
    """Return page-level text with stable, normalized metadata."""
    pdf_dir = Path(pdf_dir)
    manifest = _load_manifest(pdf_dir)
    by_filename = {item.get("file"): item for item in manifest.values() if item.get("file")}
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    print(f"[INFO] Found {len(pdf_files)} PDF files.")

    documents = []
    for pdf_file in pdf_files:
        print(f"[INFO] Reading: {pdf_file.name}")
        pages = pymupdf4llm.to_markdown(str(pdf_file), page_chunks=True)
        spec = by_filename.get(pdf_file.name, {})
        for page_number, page in enumerate(pages, start=1):
            text = (page.get("text") or "").strip()
            if not text:
                continue

            # Manifest is the source of truth; text parsing is the fallback.
            metadata = {
                key: value for key, value in spec.items()
                if key in {
                    "document_id", "title", "language", "version", "status",
                    "owner", "effective_date", "effective_to", "policy_family",
                    "supersedes", "superseded_by", "translation_of",
                } and value is not None
            }
            for key, value in _header_metadata(text).items():
                metadata.setdefault(key, value)

            metadata.update({
                "source": pdf_file.name,
                "page": page_number,
            })
            metadata["status"] = str(metadata.get("status", "current")).strip().lower()
            metadata["document_id"] = metadata.get(
                "document_id", pdf_file.stem.split("_")[0]
            )
            documents.append({"text": text, "metadata": metadata})

    print(f"[SUCCESS] Extracted {len(documents)} pages from {len(pdf_files)} PDFs.")
    missing = sorted(set(item.get("file") for item in manifest.values()) -
                     {path.name for path in pdf_files})
    if missing:
        print(f"[WARNING] Manifest references {len(missing)} PDF(s) not present in this folder.")
    return documents
