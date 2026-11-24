"""Deterministic order selection and ambiguity handling for customer sessions."""
from __future__ import annotations

import re
from typing import Any

_ORDER_ID_RE = re.compile(r"\bORD-[A-Z0-9-]+\b", re.IGNORECASE)
_ORDER_OVERVIEW_TERMS = (
    "my orders", "all my orders", "list my orders", "show my orders",
    "what are my orders", "which orders", "list orders",
)
_ORDER_TERMS = (
    "my order", "this order", "the order", "order status", "where is my order",
    "track my", "tracking", "shipment", "delivery", "delivered", "not arrived",
    "parcel", "package", "shipping status", "refund for", "refund my",
    "refund status", "request a refund", "get a refund", "return my",
    "return this", "cancel my", "cancel this", "payment for", "payment failed",
    "order id", "order number",
)


def _order_label(order: dict[str, Any]) -> str:
    names = ", ".join(
        str(item.get("product_name", "item"))
        for item in order.get("items", []) if isinstance(item, dict)
    ) or "item(s)"
    return f"{order.get('order_id')} ({names}; status: {order.get('order_status', 'not available')})"


def resolve_order_context(question: str, ml_result: dict, context: dict) -> tuple[dict | None, dict | None]:
    """Return a narrowed context, or a deterministic clarification response.

    Returns (context, response). Exactly one of the values is non-None.
    Customer/order ownership has already been enforced by database queries.
    """
    selected = context.get("selected_order")
    mentioned_ids = [value.upper() for value in _ORDER_ID_RE.findall(question or "")]

    if selected:
        selected_id = str(selected.get("order_id", "")).upper()
        if mentioned_ids and any(value != selected_id for value in mentioned_ids):
            return None, {
                "status": "NEEDS_CLARIFICATION", "decision": "CLARIFY",
                "message": (f"This session is set to {selected_id}. I can only verify that order in this session. "
                            "Please start a new session with the other order ID if you want help with a different order."),
                "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
                "human_intervention_required": False, "human_intervention_reason": None,
            }
        return context, None

    orders = context.get("orders", [])
    orders = [item for item in orders if isinstance(item, dict)]
    if not orders:
        text = (question or "").casefold()
        if any(term in text for term in _ORDER_TERMS):
            return None, {
                "status": "CANNOT_ANSWER", "decision": "CLARIFY",
                "message": "I couldn't find any orders linked to your account. Please check that you're logged in with the correct customer ID.",
                "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
                "human_intervention_required": False, "human_intervention_reason": None,
            }
        return context, None

    by_id = {str(order.get("order_id", "")).upper(): order for order in orders}
    if mentioned_ids:
        # If multiple IDs are mentioned, require one unambiguous order reference.
        unique_ids = list(dict.fromkeys(mentioned_ids))
        if len(unique_ids) > 1:
            return None, {
                "status": "NEEDS_CLARIFICATION", "decision": "CLARIFY",
                "message": "I found more than one order ID in your message. Which single order would you like me to check?",
                "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
                "human_intervention_required": False, "human_intervention_reason": None,
            }
        order = by_id.get(unique_ids[0])
        if order is None:
            return None, {
                "status": "NEEDS_CLARIFICATION", "decision": "CLARIFY",
                "message": "I can't find that order in your account. Please check the order ID and try again.",
                "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
                "human_intervention_required": False, "human_intervention_reason": None,
            }
        narrowed = {k: v for k, v in context.items() if k != "orders"}
        narrowed["selected_order"] = order
        return narrowed, None

    # An explicit request to list all orders is not ambiguous: provide the list.
    text = (question or "").casefold()
    if any(term in text for term in _ORDER_OVERVIEW_TERMS):
        return context, None

    # Do not let a low-confidence or incorrect ML label trigger a clarification.
    # Order ambiguity is based on the customer's actual wording.
    order_specific = any(term in text for term in _ORDER_TERMS)
    if not order_specific:
        # Avoid giving the LLM every order when the question is unrelated.
        narrowed = {k: v for k, v in context.items() if k != "orders"}
        return narrowed, None

    if len(orders) == 1:
        narrowed = {k: v for k, v in context.items() if k != "orders"}
        narrowed["selected_order"] = orders[0]
        return narrowed, None

    choices = "\n".join(f"- {_order_label(order)}" for order in orders)
    return None, {
        "status": "NEEDS_CLARIFICATION", "decision": "CLARIFY",
        "message": f"You have {len(orders)} orders. Which one are you asking about?\n{choices}\nPlease reply with the order ID.",
        "citations": [], "evidence": [], "database_evidence": [], "rag_evidence": [],
        "human_intervention_required": False, "human_intervention_reason": None,
    }
