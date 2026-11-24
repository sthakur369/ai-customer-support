"""Deterministic fast-path classification for greetings and pleasantries."""
from __future__ import annotations

import re
import unicodedata

_SMALL_TALK_PATTERNS = (
    r"(?:hi|hello|hey|yo|hiya)(?:\s+(?:there|everyone|team|yo))*",
    r"(?:hi|hello|hey|yo|hiya)(?:\s+(?:there|yo))?\s+(?:how are you|kese ho|kaise ho|kya haal(?: hai)?)",
    r"(?:good\s+)?(?:morning|afternoon|evening|night)",
    r"(?:how\s+are\s+you|how\s+r\s+you|how\s+you\s+doing)",
    r"(?:howdy|what'?s\s+up|whats\s+up|sup)",
    r"(?:namaste|namaskar|pranam)",
    r"(?:kese|kaise|kaisa|kaisi)\s+ho",
    r"kya\s+haal(?:\s+hai)?",
    r"(?:main|mai)\s+theek\s+hoon",
    r"(?:thanks(?:\s+so\s+much)?|thank\s+you(?:\s+so\s+much)?|thx|ty)",
)


def is_small_talk(message: str) -> bool:
    """Only classify a complete short greeting/pleasantry, never a mixed request."""
    text = unicodedata.normalize("NFKC", str(message or "")).casefold().strip()
    text = re.sub(r"[!?.,;:~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > 80:
        return False
    return any(re.fullmatch(pattern, text) for pattern in _SMALL_TALK_PATTERNS)


def small_talk_response(question: str) -> dict:
    lowered = str(question or "").casefold()
    if any(word in lowered for word in ("kese ho", "kaise ho", "kya haal", "namaste", "namaskar")):
        message = "Main badhiya hoon, shukriya! Aapko kis cheez mein help chahiye?"
    elif any(word in lowered for word in ("thanks", "thank you", "thx", "ty")):
        message = "You're welcome! What else can I help you with?"
    else:
        message = "Hi! I'm doing well, thanks. How can I help you today?"
    return {
        "status": "ANSWERED", "decision": "RESPOND", "message": message,
        "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
        "human_intervention_required": False, "human_intervention_reason": None,
        "stage_latencies_seconds": {
            "ml": 0.0, "security_and_intervention": 0.0, "knowledge_routing": 0.0,
            "rag_retrieval_and_reranking": 0.0, "tool_calling": 0.0, "final_response": 0.0,
        },
        "total_latency_seconds": 0.0,
        "technical_diagnostics": {"pipeline_bypassed": "greeting_or_pleasantry"},
    }
