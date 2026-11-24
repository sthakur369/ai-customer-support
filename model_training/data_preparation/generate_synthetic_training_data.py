"""Generate synthetic, labelled customer-support interactions.

Outputs:
  data/interactions.jsonl and data/interactions.csv

Install dependencies:
  pip install -r requirements.txt

PowerShell:
  $env:OPENAI_API_KEY = "your_api_key"
  $env:OPENAI_MODEL = "your-api-model-id"
  python generate_training_data.py --count 50
  python generate_training_data.py --count 3000
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from openai import OpenAI

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

INTENTS = {
    "order_status": "Customer asks where an existing order is or asks for its status.",
    "refund_request": "Customer asks for money back or asks about a refund.",
    "return_request": "Customer wants to return or exchange an item.",
    "damaged_item": "Customer says an item arrived damaged, broken, defective, or unusable.",
    "missing_item": "Customer says an item or part is missing from the package.",
    "payment_issue": "Customer reports a failed, pending, duplicated, or otherwise problematic payment.",
    "cancellation": "Customer wants to cancel an order or asks why cancellation failed.",
    "delivery_delay": "Customer reports that delivery is later than promised.",
    "product_information": "Customer asks about product features, size, compatibility, or availability.",
    "account_issue": "Customer has trouble logging in or accessing/updating an account.",
    "complaint": "Customer primarily complains about poor service or repeated support failures.",
    "other": "A genuine support request that does not fit the categories above.",
}

PRIORITIES = {
    "low": "General information or a non-urgent request with little immediate impact.",
    "medium": "A normal support issue that needs action but is not time-critical.",
    "high": "Significant customer impact, repeated failure, or a time-sensitive issue.",
    "urgent": "Severe immediate impact, safety concern, or serious financial/customer harm.",
}

LANGUAGES = ("english", "hindi", "hinglish")
CSV_COLUMNS = ["customer_query", "language", "intent", "priority", "escalation_risk"]

# Synthetic-data design target, not an estimate of real-world escalation rates.
ESCALATION_RATE = 0.18

# Scenarios stay within the assigned intent. They do not introduce a second issue.
ESCALATION_SCENARIOS_BY_INTENT = {
    "order_status": [
        "The customer has contacted support several times because tracking for this same order has not updated, and still cannot get a clear status.",
        "The promised status updates for this order have repeatedly failed; the customer needs a clear answer today after several unsuccessful contacts.",
    ],
    "refund_request": [
        "The refund for this same purchase has missed several promised dates despite repeated contacts; the customer says they will file a formal consumer complaint.",
        "The customer has followed up multiple times about this same refund and has received contradictory promises; they are demanding senior intervention.",
    ],
    "return_request": [
        "The customer has repeatedly tried to arrange the return of this same item, but the return process keeps failing despite multiple support contacts.",
        "Several return pickup attempts for this item have failed; the customer now demands a senior agent to resolve the return.",
    ],
    "damaged_item": [
        "The item arrived damaged and shows a serious safety concern such as overheating or smoke; the customer needs immediate human assistance.",
        "The customer has repeatedly reported that this same item arrived defective, but replacement or resolution attempts have failed.",
    ],
    "missing_item": [
        "The same item or component was missing from the package, and several support contacts have failed to resolve the missing-item complaint.",
        "The customer has repeatedly provided details about the missing item but support keeps closing the same case without a solution.",
    ],
    "payment_issue": [
        "The customer was charged twice for the same purchase; multiple earlier contacts failed to resolve the duplicate charge.",
        "A payment problem has remained unresolved after repeated support contacts, causing significant financial difficulty for the customer.",
    ],
    "cancellation": [
        "The customer has repeatedly requested cancellation of this same order, but the cancellation still has not been processed.",
        "Several cancellation requests for the same order have failed and the customer is now demanding senior intervention.",
    ],
    "delivery_delay": [
        "The same order has missed several promised delivery dates despite repeated contacts, and the customer needs it urgently.",
        "The customer has contacted support multiple times about this same delayed delivery but has received no reliable update.",
    ],
    "product_information": [
        "The customer has received conflicting answers several times about the same product's safety or compatibility and needs a qualified specialist to clarify it.",
        "Repeated attempts to get accurate specifications for this same product have failed, and the customer needs a definitive answer before purchasing.",
    ],
    "account_issue": [
        "The customer has repeatedly tried to recover access to the same account, but the recovery process keeps failing despite several support contacts.",
        "The customer remains locked out of the same account after multiple unsuccessful support attempts and requests senior technical help.",
    ],
    "complaint": [
        "The customer has raised the same service complaint several times, but each case was closed without resolving it.",
        "The customer says repeated attempts to resolve this same complaint have failed and now requests formal escalation.",
    ],
    "other": [
        "The customer's request about the supplied topic_hint has remained unresolved after several contacts; keep the message focused on that one request.",
        "The customer has repeatedly tried to resolve the same supplied topic_hint request, but support has not provided a workable answer.",
    ],
}

ROUTINE_SCENARIOS = [
    "A first-time, routine request with no previous failed support contact.",
    "A calm information request with no urgency, threat, safety issue, or demand for a supervisor.",
    "A normal service question that can be handled by the standard support team.",
    "A first report of a problem; the customer is asking what the next step is.",
    "A polite follow-up that does not mention repeated failures or demand escalation.",
]

OTHER_TOPICS = [
    "downloading a GST invoice",
    "changing delivery address or phone number",
    "applying a promo code or loyalty points",
    "registering product warranty",
    "reporting a minor app user-interface bug",
    "asking about bulk or corporate orders",
]

SYSTEM_PROMPT = """
You create realistic synthetic customer-support messages for a fictional Indian
e-commerce company. These examples will train classifiers, so label quality
and linguistic variety matter more than fancy writing.

Generate natural customer messages in:
- Indian English.
- Hindi written in Devanagari script.
- Roman-script Hinglish with genuine Hindi-English code-mixing.

Messages should vary in length and tone: brief, detailed, polite, confused,
impatient, frustrated, and calm. Include occasional believable spelling
mistakes, missing punctuation, abbreviations, and grammar errors, but do not
make every message contain errors. Avoid templates, repeated openings, shallow
paraphrases, and repeated wording. Do not generate an agent reply.

INTENT CONSISTENCY:
- Each message must represent ONLY its assigned intent. Never add a secondary
  issue just to make a message urgent or dramatic.
- Keep the customer's main problem clearly within the supplied intent definition.
- If a topic_hint is provided, use it as the subject of the "other" request.
- Do not mention unrelated products, payments, refunds, deliveries, or account
  problems unless they are part of the assigned intent.

PRIORITY AND ESCALATION:
- Choose priority using the supplied definitions. Escalation risk is separate
  from priority; a high-priority message is not automatically an escalation.
- A genuine escalation signal includes repeated unresolved contact, serious
  financial harm, a safety concern, a credible legal/regulatory threat, or
  clear need for senior intervention after failed support.
- If escalation_target is 1, communicate the supplied escalation scenario
  naturally and set escalation_risk to 1.
- If escalation_target is 0, keep it a routine case and set escalation_risk
  to 0. Ordinary frustration alone is not escalation.
- For escalation_risk 1, vary how escalation is expressed. Do not rely only on
  words such as "supervisor", "manager", or "consumer forum".
- Do not create an escalation by adding a second unrelated issue.
- Set priority independently according to the actual impact described.

Use the assigned language:
- english: natural Indian English.
- hindi: natural Hindi in Devanagari script.
- hinglish: natural Hindi-English code-mixing written mainly in Roman script.

Do not invent real personal information, payment credentials, OTPs, addresses,
order IDs, or claims about real companies.

Return valid JSON only, with this exact top-level shape:
{"records":[{"customer_query":"...","language":"english|hindi|hinglish","intent":"...","priority":"low|medium|high|urgent","escalation_risk":0}]}
Do not include markdown, explanations, or extra keys.
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"))
    parser.add_argument("--output", type=Path, default=Path("data/interactions.jsonl"))
    parser.add_argument("--csv-output", type=Path, default=Path("data/interactions.csv"))
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def allocate_counts(count: int, weights: dict[str, float]) -> dict[str, int]:
    exact = {key: count * weight for key, weight in weights.items()}
    allocated = {key: int(value) for key, value in exact.items()}
    remainder = count - sum(allocated.values())
    order = sorted(weights, key=lambda key: exact[key] - allocated[key], reverse=True)
    for key in order[:remainder]:
        allocated[key] += 1
    return allocated


def make_language_schedule(count: int, rng: random.Random) -> list[str]:
    """Target 50% English, 15% Hindi, 35% Hinglish; Hindi/Hinglish >=30%."""
    counts = allocate_counts(count, {"english": 0.50, "hindi": 0.15, "hinglish": 0.35})
    minimum_non_english = (3 * count + 9) // 10
    non_english = counts["hindi"] + counts["hinglish"]
    if non_english < minimum_non_english:
        shift = minimum_non_english - non_english
        counts["english"] -= shift
        counts["hinglish"] += shift
    schedule = [language for language, number in counts.items() for _ in range(number)]
    rng.shuffle(schedule)
    return schedule


def make_escalation_schedule(count: int, rng: random.Random) -> list[int]:
    """Schedule approximately 18% positive escalation examples."""
    positive_count = int(count * ESCALATION_RATE + 0.5)
    if count >= 3:
        positive_count = max(1, positive_count)
    schedule = [1] * min(positive_count, count) + [0] * (count - min(positive_count, count))
    rng.shuffle(schedule)
    return schedule


def make_batch_plan(
    start_index: int,
    batch_size: int,
    rng: random.Random,
    language_schedule: list[str],
    escalation_schedule: list[int],
) -> list[dict[str, Any]]:
    intent_names = list(INTENTS)
    variations = [
        "short and direct", "polite and detailed", "confused and asking what to do",
        "frustrated but not abusive", "a follow-up after waiting",
        "casual everyday wording", "contains a few natural spelling or grammar mistakes",
        "explains events in chronological order", "asks a specific practical question",
        "very brief with limited context",
    ]
    plan = []
    for i in range(batch_size):
        absolute_index = start_index + i
        intent = intent_names[absolute_index % len(intent_names)]
        language = language_schedule[absolute_index]
        escalation_target = escalation_schedule[absolute_index]
        topic_hint = rng.choice(OTHER_TOPICS) if intent == "other" else None

        if escalation_target:
            scenario = rng.choice(ESCALATION_SCENARIOS_BY_INTENT[intent])
        else:
            scenario = rng.choice(ROUTINE_SCENARIOS)

        plan.append({
            "record_number": absolute_index + 1,
            "intent": intent,
            "intent_definition": INTENTS[intent],
            "language": language,
            "priority_definitions": PRIORITIES,
            "escalation_target": escalation_target,
            "scenario": scenario,
            "topic_hint": topic_hint,
            "variation": rng.choice(variations),
        })
    return plan


def call_model(client: OpenAI, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=(
            "Return the requested JSON object. Follow this payload exactly:\n"
            + json.dumps(payload, ensure_ascii=False)
        ),
        text={"format": {"type": "json_object"}},
    )
    output_text = response.output_text
    if not output_text:
        raise ValueError("The API returned an empty response body.")
    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        raise ValueError("The API response JSON must be an object.")
    return parsed


def validate_batch(records: Any, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != len(plan):
        actual = len(records) if isinstance(records, list) else "a non-list"
        raise ValueError(f"Model returned {actual} records; expected {len(plan)}.")

    validated = []
    for index, (item, spec) in enumerate(zip(records, plan), start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Record {index} is not a JSON object.")
        query = item.get("customer_query")
        if not isinstance(query, str) or len(query.strip()) < 8:
            raise ValueError(f"Record {index}: customer_query is missing or too short.")
        if len(query.strip()) > 1200:
            raise ValueError(f"Record {index}: customer_query is too long (maximum 1200 characters).")
        if item.get("intent") != spec["intent"]:
            raise ValueError(f"Record {index}: model changed the assigned intent.")
        if item.get("language") != spec["language"]:
            raise ValueError(f"Record {index}: model changed the assigned language.")
        if item.get("priority") not in PRIORITIES:
            raise ValueError(f"Record {index}: invalid priority label {item.get('priority')!r}.")
        risk = item.get("escalation_risk")
        if type(risk) not in (int, bool) or int(risk) not in (0, 1):
            raise ValueError(f"Record {index}: escalation_risk must be 0 or 1.")
        if int(risk) != spec["escalation_target"]:
            raise ValueError(
                f"Record {index}: escalation_risk={risk} does not match "
                f"scheduled target {spec['escalation_target']}."
            )
        validated.append({
            "customer_query": query.strip(),
            "language": spec["language"],
            "intent": spec["intent"],
            "priority": item["priority"],
            "escalation_risk": int(risk),
        })
    return validated


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


def load_existing_records(
    path: Path,
    count: int,
    language_schedule: list[str],
    escalation_schedule: list[int],
) -> list[dict[str, Any]]:
    """Load and validate resumable JSONL data before making any API calls."""
    records: list[dict[str, Any]] = []
    intent_names = list(INTENTS)
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}, line {line_number}: {exc}") from exc
            if not isinstance(item, dict) or set(item) != set(CSV_COLUMNS):
                raise ValueError(f"Unexpected schema in {path}, line {line_number}.")
            if len(records) >= count:
                raise ValueError(f"{path} contains more than the requested {count} rows.")
            index = len(records)
            if item["intent"] != intent_names[index % len(intent_names)]:
                raise ValueError(
                    f"Intent sequence mismatch at row {index + 1}. Keep the same --seed "
                    "and use the original generated dataset when resuming."
                )
            if item["language"] not in LANGUAGES:
                raise ValueError(f"Invalid language label in {path}, line {line_number}.")
            if item["priority"] not in PRIORITIES or not isinstance(item["customer_query"], str):
                raise ValueError(f"Invalid labels or query in {path}, line {line_number}.")
            if type(item["escalation_risk"]) not in (int, bool) or int(item["escalation_risk"]) not in (0, 1):
                raise ValueError(f"Invalid escalation_risk in {path}, line {line_number}.")
            item["escalation_risk"] = int(item["escalation_risk"])
            records.append(item)
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(records: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def print_distribution(title: str, records: list[dict[str, Any]], field: str) -> None:
    counts = Counter(record[field] for record in records)
    print(title)
    for label in sorted(counts):
        number = counts[label]
        print(f"  {label}: {number} ({number / len(records) * 100:.1f}%)")


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1.")
    if not 1 <= args.batch_size <= 20:
        raise SystemExit("--batch-size must be between 1 and 20.")
    if args.retries < 1:
        raise SystemExit("--retries must be at least 1.")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY before running this script.")
    if not args.model:
        raise SystemExit("Set OPENAI_MODEL to an API model ID available to your account.")
    if args.output.resolve() == args.csv_output.resolve():
        raise SystemExit("JSONL and CSV output paths must be different.")

    rng = random.Random(args.seed)
    language_schedule = make_language_schedule(args.count, rng)
    escalation_schedule = make_escalation_schedule(args.count, rng)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    output_paths = [args.output, args.csv_output]
    temporary_paths = [path.with_name(path.name + ".partial") for path in output_paths]

    # Check both files and resume from whichever contains the most valid rows.
    # This avoids preferring an older .partial file over a newer final JSONL.
    candidates: list[tuple[int, Path, list[dict[str, Any]]]] = []
    for candidate_path in (temporary_paths[0], args.output):
        if candidate_path.exists():
            try:
                candidate_records = load_existing_records(
                    candidate_path, args.count, language_schedule, escalation_schedule
                )
                candidates.append((len(candidate_records), candidate_path, candidate_records))
            except Exception as exc:
                print(f"Could not resume from {candidate_path}: {exc}")

    if candidates:
        # Prefer the final output on ties; otherwise use the file with more rows.
        candidates.sort(key=lambda item: (item[0], item[1] == args.output), reverse=True)
        _, resume_path, all_records = candidates[0]
        print(f"Resuming from {len(all_records)} existing rows in {resume_path}.")
    else:
        all_records = []
        if temporary_paths[0].exists() or args.output.exists():
            raise SystemExit("No existing JSONL file passed resume validation; no files were changed.")

    client = OpenAI()

    try:
        # Rebuild the partial JSONL from the validated source, then append new batches.
        with temporary_paths[0].open("w", encoding="utf-8") as output_file:
            for record in all_records:
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            output_file.flush()

            for start in range(len(all_records), args.count, args.batch_size):
                current_size = min(args.batch_size, args.count - start)
                last_error: Exception | None = None
                accepted_batch: list[dict[str, Any]] | None = None

                for attempt in range(1, args.retries + 1):
                    plan = make_batch_plan(
                        start, current_size, rng, language_schedule, escalation_schedule
                    )
                    payload = {
                        "task": "Generate customer-support examples and return them as JSON.",
                        "required_record_count": current_size,
                        "intent_definitions": INTENTS,
                        "priority_definitions": PRIORITIES,
                        "assigned_scenarios": plan,
                        "retry_instruction": (
                            "Fresh attempt: use different wording from earlier attempts "
                            "and follow every assigned intent, topic_hint and escalation_target."
                            if attempt > 1 else ""
                        ),
                        "rules": [
                            "Return one JSON object with a records array, exactly one record per scenario, in order.",
                            "Preserve each scenario's exact assigned intent and language.",
                            "Represent only the assigned intent; do not introduce a secondary issue.",
                            "Use topic_hint when provided for intent other.",
                            "For escalation_target 1, communicate the supplied same-intent scenario and set escalation_risk to 1.",
                            "For escalation_target 0, keep the same-intent request routine and set escalation_risk to 0.",
                            "Choose priority independently using actual customer impact.",
                            "Vary wording where practical; do not reject otherwise valid records for repetition.",
                            "Return JSON only, without markdown or explanations.",
                        ],
                    }
                    try:
                        result = call_model(client, args.model, payload)
                        candidate = validate_batch(result.get("records"), plan)
                        accepted_batch = candidate
                        break
                    except Exception as exc:
                        last_error = exc
                        status_code = getattr(exc, "status_code", None)
                        if status_code in (400, 401, 403, 404):
                            raise RuntimeError(
                                f"Non-retryable API error (HTTP {status_code}): {exc}"
                            ) from exc
                        if attempt < args.retries:
                            wait_seconds = min(2 ** (attempt - 1), 15)
                            print(
                                f"Batch {start // args.batch_size + 1}: attempt "
                                f"{attempt}/{args.retries} failed: {exc}. "
                                f"Retrying in {wait_seconds}s..."
                            )
                            time.sleep(wait_seconds)

                if accepted_batch is None:
                    raise RuntimeError(
                        f"Batch starting at row {start + 1} failed after {args.retries} "
                        f"attempts. Earlier accepted rows remain in {temporary_paths[0]}."
                    ) from last_error

                for record in accepted_batch:
                    output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                output_file.flush()
                all_records.extend(accepted_batch)
                print(f"Generated {len(all_records)}/{args.count}")

        write_csv(all_records, temporary_paths[1])
        for temporary, final in zip(temporary_paths, output_paths):
            temporary.replace(final)

    except Exception:
        print(
            "\nGeneration did not complete. Your previous final JSONL is preserved. "
            f"Progress is saved in {temporary_paths[0]} and will be resumed next run."
        )
        raise

    print("\nDataset generation finished.")
    print(f"Rows: {len(all_records)}")
    print_distribution("Language distribution:", all_records, "language")
    non_english = sum(r["language"] in ("hindi", "hinglish") for r in all_records)
    print(f"Hindi + Hinglish: {non_english / len(all_records) * 100:.1f}%")
    print_distribution("Intent distribution:", all_records, "intent")
    print_distribution("Priority distribution:", all_records, "priority")
    print_distribution("Escalation-risk distribution:", all_records, "escalation_risk")
    normalized_queries = [normalize_query(r["customer_query"]) for r in all_records]
    unique_count = len(set(normalized_queries))
    print(f"Unique messages: {unique_count}/{len(all_records)}")
    print(f"Repeated rows (informational only): {len(all_records) - unique_count}")

    if non_english / len(all_records) < 0.30:
        raise SystemExit("Language requirement not met: Hindi/Hinglish must be >=30%.")

    print(f"\nJSONL: {args.output.resolve()}")
    print(f"CSV:   {args.csv_output.resolve()}")


if __name__ == "__main__":
    main()
