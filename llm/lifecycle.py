"""LLM decision stages and final customer response composition."""
import uuid
import unicodedata
from datetime import datetime, timezone
from config.settings import ML_INTERVENTION_CONFIDENCE_THRESHOLD
from llm.client import ask_json
from llm.tool_calling import run_support_tool_calls
from llm.security import inspect_input, redact_for_admin
from rag.service import load_document_catalog
from llm.evidence import (
    _database_evidence, _payment_consistency_warnings, canonicalize_citations,
    build_rag_evidence, build_readable_evidence,
)


def ml_intervention_signal(ml_result: dict) -> dict:
    """Flag a possible intervention; this signal never escalates by itself."""
    predictions = ml_result.get("predictions", {})
    priority = predictions.get("priority", {})
    escalation = predictions.get("escalation_risk", {})
    threshold = ML_INTERVENTION_CONFIDENCE_THRESHOLD
    priority_label = str(priority.get("label", "")).strip().lower()
    escalation_label = str(escalation.get("label", "")).strip().lower()
    priority_high = priority_label in {"high", "urgent", "critical"}
    escalation_high = escalation_label in {"1", "true", "high", "yes"}
    confidence_ok = (
        float(priority.get("confidence", 0.0)) >= threshold
        and float(escalation.get("confidence", 0.0)) >= threshold
    )
    return {
        "potential_human_intervention": bool(priority_high and escalation_high and confidence_ok),
        "reason": "High priority and high escalation risk with sufficient confidence"
        if priority_high and escalation_high and confidence_ok else None,
        "confidence_threshold": threshold,
        "priority_high": priority_high,
        "escalation_risk_high": escalation_high,
        "confidence_sufficient": confidence_ok,
    }


def security_assessment(
    question: str,
    ml_result: dict,
    customer_context: dict | None = None,
) -> tuple[dict, dict, float]:
    """Run security checks and intervention assessment using verified account context."""

    local = inspect_input(question)

    injection, injection_latency = ask_json("security", {
        "customer_message": question,
        "local_security_flags": local["flags"],
    })

    security_blocked = bool(
        local["blocked"] or injection.get("prompt_injection_suspected", False)
    )

    security = {
        "blocked": security_blocked,
        "flags": sorted(set(
            local["flags"] + (
                ["possible_prompt_injection"]
                if injection.get("prompt_injection_suspected", False)
                else []
            )
        )),
        "evidence": local["evidence"] + (
            injection.get("evidence", [])
            if isinstance(injection.get("evidence", []), list)
            else []
        ),
        "reason": injection.get("reason") if security_blocked else None,
        "latency_seconds": injection_latency,
    }

    if security_blocked:
        intervention = {
            "decision": "REFUSE",
            "human_intervention_required": False,
            "reason": security.get("reason") or "The message failed security checks.",
            "security_flags": security["flags"],
            "evidence": security["evidence"],
            "queue": None,
            "latency_seconds": injection_latency,
        }
        return intervention, security, injection_latency

    ml_signal = ml_intervention_signal(ml_result)

    # Pass only relevant, application-verified order fields.
    # Never let customer text determine this context.
    selected_order = (
        customer_context.get("selected_order")
        if isinstance(customer_context, dict)
        else None
    )

    verified_order_context = None

    if selected_order:
        payment = selected_order.get("payment") or {}

        verified_order_context = {
            "order_id": selected_order.get("order_id"),
            "order_status": selected_order.get("order_status"),
            "shipment_status": selected_order.get("shipment_status"),
            "estimated_delivery": selected_order.get("estimated_delivery"),
            "payment_status": payment.get("payment_status"),
            "items": [
                item.get("product_name")
                for item in selected_order.get("items", [])
            ],
        }

    result, intervention_latency = ask_json("intervention", {
        "customer_message": question,
        "ml_assessment": ml_result.get("predictions", {}),
        "ml_intervention_signal": ml_signal,
        "security_assessment": security,
        "verified_order_context": verified_order_context,
        "order_already_selected": verified_order_context is not None,
    })

    decision = str(result.get("decision", "ESCALATE")).upper()

    if decision not in {"CONTINUE", "ESCALATE", "REFUSE", "CLARIFY"}:
        decision = "ESCALATE"

    reason = result.get("reason")

    # Deterministic safeguard: do not ask for an order ID when the
    # authenticated session already contains a verified selected order.
    if decision == "CLARIFY" and verified_order_context:
        clarification_reason = str(reason or "").casefold()

        order_detail_phrases = (
            "order details",
            "order id",
            "order number",
            "which order",
            "select an order",
            "provide your order",
        )

        if any(phrase in clarification_reason for phrase in order_detail_phrases):
            decision = "CONTINUE"
            reason = (
                "The selected order is already verified in the customer's session."
            )

    intervention = {
        "decision": decision,
        "human_intervention_required": decision == "ESCALATE",
        "reason": reason,
        "ml_intervention_signal": ml_signal,
        "security_flags": security["flags"],
        "evidence": (
            result.get("evidence", [])
            if isinstance(result.get("evidence", []), list)
            else []
        ),
        "queue": result.get("queue"),
        "latency_seconds": round(
            injection_latency + intervention_latency, 4
        ),
    }

    return (
        intervention,
        security,
        round(injection_latency + intervention_latency, 4),
    )


def route_to_rag(question: str, ml_result: dict) -> tuple[dict, float]:
    catalog = load_document_catalog()
    result, latency = ask_json("rag_router", {
        "customer_question": unicodedata.normalize("NFC", question),
        "ml_classification": ml_result.get("predictions", {}),
        "available_documents": catalog,
    })
    ids = {item["document_id"] for item in catalog}
    selected = result.get("relevant_document_ids", [])
    selected = [item for item in selected if item in ids] if isinstance(selected, list) else []
    return {
        "rag_required": bool(result.get("rag_required", True)),
        "relevant_document_ids": selected,
        "search_query": str(result.get("search_query") or question).strip()[:1000],
        "reason": result.get("reason", "No reason supplied."),
        "document_catalog_count": len(catalog),
        "latency_seconds": latency,
    }, latency



def enforce_retrieved_policy_escalation(question: str, intervention: dict, retrieval: dict) -> dict:
    """Enforce the KB-020 repeated-unresolved-failure handoff rule when both
    the customer message and a retrieved policy chunk explicitly support it.
    This is deliberately narrow; general dissatisfaction alone is not enough.
    """
    if intervention.get("human_intervention_required") or intervention.get("decision") != "CONTINUE":
        return intervention

    message = unicodedata.normalize("NFC", question).casefold()
    repeated = any(term in message for term in (
        "repeated complaints", "repeatedly complained", "complained multiple times",
        "complained several times", "multiple complaints", "again and again",
        "many times", "several times", "multiple times", "itni baar",
        "baar baar", "bar bar", "kai baar", "complaint kar chuka",
        "complaint kar chuki", "बार-बार", "बार बार", "कई बार", "इतनी बार",
        "अनेक बार", "कई शिकायत",
    ))
    unresolved = any(term in message for term in (
        "still unresolved", "not resolved", "not fixed", "not solved",
        "still not", "problem remains", "hasn't been resolved", "has not been resolved",
        "solve nahi", "solved nahi", "resolve nahi", "theek nahi", "ठीक नहीं",
        "solve karni nahi aati", "solve nahi kar", "not able to solve", "cannot solve",
        "can't solve", "unable to resolve", "nahi kar pa", "नहीं कर पा",
        "समाधान नहीं", "हल नहीं", "काम नहीं", "काम ठीक से नहीं", "नहीं हुआ",
    ))
    if not (repeated and unresolved):
        return intervention

    policy_chunks = retrieval.get("chunks", []) if isinstance(retrieval, dict) else []
    supporting_chunk = next((chunk for chunk in policy_chunks
        if "repeated unresolved failures" in str(chunk.get("text", "")).casefold()
        and "escalate" in str(chunk.get("text", "")).casefold()), None)
    if not supporting_chunk:
        return intervention

    metadata = supporting_chunk.get("metadata") or {}
    evidence = list(intervention.get("evidence", []))
    evidence.append("Customer explicitly reports repeated attempts/complaints and that the issue remains unresolved.")
    evidence.append(
        f"{metadata.get('document_id', 'Knowledge base')} ({metadata.get('section', 'policy section')}): "
        "the retrieved policy states that repeated unresolved failures should be escalated."
    )
    return {
        **intervention,
        "decision": "ESCALATE",
        "human_intervention_required": True,
        "reason": "The customer reports repeated unresolved complaints, and the retrieved policy requires these cases to be escalated for human review.",
        "queue": intervention.get("queue") or "Customer Experience",
        "evidence": evidence,
        "policy_escalation_rule": "KB-020 repeated unresolved failures",
    }



def compose_final_response(question: str, ml: dict, intervention: dict, routing: dict,
                           retrieval: dict, customer_context: dict | None = None) -> tuple[dict, float]:
    db_evidence = _database_evidence(customer_context)
    consistency_warnings = _payment_consistency_warnings(customer_context)

    # Function calling is limited to customer-specific order lookups. It is
    # skipped for greetings/general policy questions to avoid needless LLM calls.
    tool_results, tool_latency = [], 0.0
    customer_id = (customer_context or {}).get("customer", {}).get("customer_id")
    question_lower = question.casefold()
    tool_triggers = (
        "order", "payment", "refund", "shipment", "delivery", "tracking",
        "track", "parcel", "package", "ORD-",
    )
    if customer_id and any(term in question_lower for term in tool_triggers):
        try:
            tool_results, tool_latency = run_support_tool_calls(question, int(customer_id), customer_context)
        except Exception as exc:
            # Existing verified DB context remains available; tool-call failure
            # must never turn into fabricated data or crash the support flow.
            tool_results = [{
                "tool": "tool_calling",
                "result": {"ok": False, "error": f"Tool service unavailable ({type(exc).__name__})."},
            }]

    result, latency = ask_json("final_response", {
        "customer_message": unicodedata.normalize("NFC", question),
        "ml_classification": ml,
        "intervention_assessment": intervention,
        "rag_routing": routing,
        "retrieved_evidence": retrieval.get("chunks", []),
        "database_evidence": db_evidence,
        "data_consistency_warnings": consistency_warnings,
        # Customer context is application-verified and scoped to the login session.
        "customer_and_order_context": customer_context,
        "tool_call_results": tool_results,
    })
    if not isinstance(result, dict):
        result = {}
    allowed = {"ANSWERED", "NEEDS_CLARIFICATION", "CANNOT_ANSWER"}
    if result.get("status") not in allowed:
        result["status"] = "CANNOT_ANSWER"
    result["citations"] = canonicalize_citations(result.get("citations"), retrieval.get("chunks", []))
    result["tool_diagnostics"] = {"calls": tool_results, "latency_seconds": tool_latency}
    rag_evidence = build_rag_evidence(retrieval)

    # Intervention stage owns the handoff decision.
    result["human_intervention_required"] = bool(intervention.get("human_intervention_required", False))
    result["human_intervention_reason"] = intervention.get("reason")
    result["decision"] = "RESPOND" if result.get("status") == "ANSWERED" else "CLARIFY"
    message = str(result.get("message") or "").strip()
    if not result["human_intervention_required"]:
        import re
        claims_handoff = re.search(
            r"\b(?:i have|we have|has been|was) (?:already )?(?:escalated|forwarded|handed over)\b|"
            r"\b(?:sent|forwarded) to (?:our|the) (?:human|support|specialist|review) team\b|"
            r"\b(?:a human|our team|a specialist) will review\b",
            message, flags=re.IGNORECASE,
        )
        if claims_handoff:
            result["message"] = (
                "I can help you with this. Please share the relevant order or case reference "
                "and a brief description of what remains unresolved."
            )

    # A contradictory payment/order state is a data-quality issue. Override any
    # overconfident delivery assurance with a transparent, database-grounded reply.
    if consistency_warnings:
        warning = consistency_warnings[0]
        result["status"] = "CANNOT_ANSWER"
        result["decision"] = "CLARIFY"
        result["message"] = (
            f"I found conflicting records for order {warning['order_id']}: the payment is marked "
            f"{warning['payment_status']}, while the order is marked {warning['order_status']} "
            f"and the shipment is marked {warning['shipment_status']}. I can't reliably confirm "
            "delivery progress from these records. Please let our support team verify the payment "
            "and shipment status before relying on the delivery estimate."
        )

    # Keep database facts and retrieved policy evidence separately traceable.
    result["evidence"] = build_readable_evidence(
        intervention, db_evidence, rag_evidence, result["citations"]
    )
    result["database_evidence"] = db_evidence
    result["rag_evidence"] = rag_evidence
    result["data_consistency_warnings"] = consistency_warnings
    result["tool_calls"] = tool_results
    result["tool_call_latency_seconds"] = tool_latency
    result["latency_seconds"] = round(latency + tool_latency, 4)
    return result, round(latency + tool_latency, 4)


def build_admin_packet(question: str, ml: dict, intervention: dict, security: dict,
                       routing: dict | None, retrieval: dict | None, reason: str) -> dict:
    return {
        "case_id": f"CASE-{uuid.uuid4().hex[:10].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_status": "PENDING_HUMAN_REVIEW",
        "reason": reason,
        "queue": intervention.get("queue") or "Customer Support",
        "customer_message_redacted": redact_for_admin(question),
        "ml_assessment": ml,
        "intervention_assessment": intervention,
        "security_assessment": security,
        "knowledge_routing": routing,
        "policy_evidence": (retrieval or {}).get("evidence", []),
        "required_admin_actions": ["Review the evidence and conversation", "Decide the next support action", "Record the outcome"],
    }
