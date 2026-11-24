"""Generate grounded answers and deterministic, metadata-rich citations."""

import json
from functools import lru_cache
from dotenv import load_dotenv
from openai import OpenAI
from config.settings import OPENAI_MODEL, PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def _client():
    return OpenAI()


def _citation_for(doc: dict) -> dict:
    metadata = doc.get("metadata", {})
    citation = {
        "document_id": metadata.get("document_id", "Unknown"),
        "source": metadata.get("source", "Unknown"),
        "version": metadata.get("version", "Unknown"),
        "status": metadata.get("status", "Unknown"),
        "page": metadata.get("page", "Unknown"),
        "section": metadata.get("section", "General"),
        "effective_date": metadata.get("effective_date", "Unknown"),
    }
    return citation


def generate_answer(query: str, documents: list[dict]) -> dict:
    if not documents:
        return {
            "status": "CANNOT_ANSWER",
            "answer": "I couldn't find enough information in the knowledge base to answer.",
            "citations": [],
        }

    citations = []
    context_parts = []
    for index, doc in enumerate(documents, start=1):
        citation = _citation_for(doc)
        citation_id = f"C{index}"
        citations.append({"citation_id": citation_id, **citation})
        context_parts.append(
            f"[{citation_id}] Document ID: {citation['document_id']} | "
            f"Source: {citation['source']} | Version: {citation['version']} | "
            f"Status: {citation['status']} | Page: {citation['page']} | "
            f"Section: {citation['section']} | Effective: {citation['effective_date']}\n"
            f"Content: {doc['text']}"
        )

    prompt = f"""Answer the customer question using only the supplied evidence.

Rules:
- Never invent policy details or rely on outside knowledge.
- Prefer CURRENT documents. If the supplied evidence conflicts or is insufficient, say so.
- Cite evidence using only the citation IDs shown, such as C1 or C2.
- Return valid JSON with keys: status, answer, citations.
- status must be ANSWERED or CANNOT_ANSWER.
- citations must be an array of citation IDs (for example ["C1"]).

Evidence:
{chr(10).join(context_parts)}

Customer question: {query}
"""

    print(f"[INFO] Generating answer with {OPENAI_MODEL}...")
    for attempt in range(2):
        try:
            response = _client().chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            if not all(key in result for key in ("status", "answer", "citations")):
                raise ValueError("Missing required JSON keys")
            allowed = {item["citation_id"]: item for item in citations}
            cited_ids = result["citations"]
            if not isinstance(cited_ids, list):
                raise ValueError("citations must be an array")
            # Only return citation metadata that came from retrieved source records.
            result["citations"] = [
                allowed[cid] for cid in cited_ids
                if isinstance(cid, str) and cid in allowed
            ]
            if result["status"] == "ANSWERED" and not result["citations"]:
                result["status"] = "CANNOT_ANSWER"
                result["answer"] = "I couldn't verify the answer against a cited source."
            print("[SUCCESS] Answer generated.")
            return result
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            print(f"[WARNING] Invalid response (attempt {attempt + 1}/2): {error}")

    return {
        "status": "CANNOT_ANSWER",
        "answer": "I couldn't generate a reliable answer. Please try again.",
        "citations": [],
    }
