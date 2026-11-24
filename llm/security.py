"""Input safety checks. Database protection must still use parameterized SQL."""
import re

SQL_INJECTION_PATTERNS = [
    r"(?i)\bunion\s+(all\s+)?select\b",
    r"(?i)\b(or|and)\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?",
    r"(?i);\s*(drop|alter|truncate|delete|update|insert)\s+",
    r"(?i)\b(drop|truncate)\s+table\b",
    r"(?i)\b(exec|execute)\s*\(",
    r"(?i)--\s*(comment|$)",
]
PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore (all )?(previous|prior|system) instructions",
    r"(?i)(reveal|show|print|repeat|dump|expose) (the )?(system|developer) prompt",
    r"(?i)(reveal|show|print|dump|expose) (the )?(secrets|api keys?|credentials|environment variables)",
    r"(?i)you are now (the )?(system|developer|admin)",
    r"(?i)(override|bypass|disable) (all )?(rules|instructions|policies|safety)",
    r"(?i)(enter|enable|activate) (developer|admin|debug|unrestricted) mode",
    r"(?i)(access|dump|exfiltrate) (all )?(customer|user) (data|records)",
]

def inspect_input(text: str) -> dict:
    hits = []
    evidence = []
    for pattern in SQL_INJECTION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            hits.append("possible_sql_injection")
            evidence.append(match.group(0)[:160])
            break
    for pattern in PROMPT_INJECTION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            hits.append("possible_prompt_injection")
            evidence.append(match.group(0)[:160])
            break
    return {
        "blocked": bool(hits),
        "flags": sorted(set(hits)),
        "evidence": evidence,
    }

def redact_for_admin(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    text = re.sub(r"\b(?:\+?\d[\d\s-]{8,}\d)\b", "[REDACTED_PHONE]", text)
    return text
