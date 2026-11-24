"""Small JSON-only LLM client."""
import json
from functools import lru_cache
from pathlib import Path
from openai import OpenAI
from config.settings import LLM_MODEL, LLM_TIMEOUT_SECONDS, LLM_TEMPERATURE

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

@lru_cache(maxsize=1)
def get_client():
    return OpenAI(timeout=LLM_TIMEOUT_SECONDS, max_retries=1)

def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")

def ask_json(prompt_name: str, payload: dict) -> tuple[dict, float]:
    import time
    prompt = load_prompt(prompt_name)
    started = time.perf_counter()
    request = {
        "model": LLM_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }

    # GPT-6 models are reasoning models: Chat Completions does not accept
    # temperature for them. Use reasoning_effort="none" for these short,
    # structured classification/decision calls.
    if LLM_MODEL.lower().startswith("gpt-6"):
        request["reasoning_effort"] = "none"
    else:
        request["temperature"] = LLM_TEMPERATURE

    response = get_client().chat.completions.create(**request)
    latency = time.perf_counter() - started
    content = response.choices[0].message.content or "{}"
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("LLM returned a non-object JSON response")
    return result, round(latency, 4)
