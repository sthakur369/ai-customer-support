"""Deterministic evidence normalization helpers (no model/network dependencies)."""
from __future__ import annotations

from typing import Any

def _database_evidence(customer_context: dict | None) -> list[dict]:
    """Create a compact, deterministic evidence record from verified DB context."""
    if not isinstance(customer_context, dict):
        return []
    evidence = []
    customer = customer_context.get("customer") or {}
    if customer:
        evidence.append({
            "source_type": "database", "record_type": "customer",
            "customer_id": customer.get("customer_id"),
            "account_status": customer.get("account_status"),
        })
    orders = []
    if isinstance(customer_context.get("selected_order"), dict):
        orders = [customer_context["selected_order"]]
    elif isinstance(customer_context.get("orders"), list):
        orders = [o for o in customer_context["orders"] if isinstance(o, dict)]
    for order in orders:
        payment = order.get("payment") or {}
        evidence.append({
            "source_type": "database", "record_type": "order",
            "order_id": order.get("order_id"),
            "order_date": order.get("order_date"),
            "order_status": order.get("order_status"),
            "total_amount": order.get("total_amount"),
            "currency": order.get("currency"),
            "items": order.get("items", []),
            "shipment_status": order.get("shipment_status"),
            "estimated_delivery": order.get("estimated_delivery"),
            "delivered_at": order.get("delivered_at"),
            "payment_status": payment.get("payment_status"),
            "payment_amount": payment.get("amount"),
            "refunds": order.get("refunds", []),
        })
    for ticket in customer_context.get("active_tickets", []):
        if isinstance(ticket, dict):
            evidence.append({
                "source_type": "database", "record_type": "active_ticket",
                "ticket_id": ticket.get("ticket_id"),
                "category": ticket.get("category"),
                "priority": ticket.get("priority"),
                "ticket_status": ticket.get("ticket_status"),
                "subject": ticket.get("subject"),
            })
    return evidence


def _payment_consistency_warnings(customer_context: dict | None) -> list[dict]:
    """Flag clearly conflicting payment/order states; never silently smooth them over."""
    if not isinstance(customer_context, dict):
        return []
    orders = ([customer_context["selected_order"]]
              if isinstance(customer_context.get("selected_order"), dict)
              else customer_context.get("orders", []))
    warnings = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        payment = order.get("payment") or {}
        payment_status = str(payment.get("payment_status", "")).lower()
        order_status = str(order.get("order_status", "")).lower()
        shipment_status = str(order.get("shipment_status", "")).lower()
        progressed_order = order_status in {"confirmed", "processing", "shipped", "delivered"}
        progressed_shipment = shipment_status in {"dispatched", "in_transit", "out_for_delivery", "delivered", "delayed"}
        if payment_status in {"failed", "declined", "pending"} and (progressed_order or progressed_shipment):
            warnings.append({
                "order_id": order.get("order_id"),
                "payment_status": payment_status,
                "order_status": order_status,
                "shipment_status": shipment_status,
                "warning": "Payment status conflicts with an order/shipment state that indicates progress. Do not assure the customer that delivery is proceeding; explain the conflicting records and request verification.",
            })
    return warnings



def canonicalize_citations(model_citations: Any, retrieved_chunks: list[dict]) -> list[dict]:
    valid = {}
    for chunk in retrieved_chunks:
        metadata = chunk.get("metadata") or {}
        key = (metadata.get("document_id"), metadata.get("source"),
               metadata.get("page"), metadata.get("section"))
        valid[key] = {key_name: metadata.get(key_name) for key_name in (
            "document_id", "source", "version", "status", "page", "section", "effective_date"
        )}
    canonical = []
    for citation in model_citations if isinstance(model_citations, list) else []:
        if not isinstance(citation, dict):
            continue
        key = (citation.get("document_id"), citation.get("source"),
               citation.get("page"), citation.get("section"))
        if key in valid and valid[key] not in canonical:
            canonical.append(valid[key])
    return canonical


def build_rag_evidence(retrieval: dict) -> list[dict]:
    output = []
    for item in retrieval.get("evidence", []):
        if isinstance(item, dict):
            output.append({key: item.get(key) for key in (
                "document_id", "source", "version", "status", "page", "section",
                "effective_date", "rerank_score", "excerpt"
            )})
    return output


def build_readable_evidence(intervention: dict, database_evidence: list[dict],
                            rag_evidence: list[dict], citations: list[dict]) -> list[str]:
    output = []
    for item in intervention.get("evidence", []):
        if isinstance(item, str) and item.strip() and item.strip() not in output:
            output.append(item.strip())
    for item in database_evidence:
        if item.get("record_type") == "order":
            output.append("Database order record: " + ", ".join(
                f"{key}={item[key]}" for key in (
                    "order_id", "order_status", "shipment_status", "estimated_delivery",
                    "delivered_at", "payment_status"
                ) if item.get(key) is not None
            ))
        elif item.get("record_type") == "active_ticket":
            output.append(f"Database active ticket: {item.get('ticket_id')} ({item.get('ticket_status')})")
    cited_keys = {
        (c.get("document_id"), c.get("source"), c.get("page"), c.get("section"))
        for c in citations if isinstance(c, dict)
    }
    for item in rag_evidence:
        key = (item.get("document_id"), item.get("source"), item.get("page"), item.get("section"))
        if key in cited_keys and item.get("excerpt"):
            output.append(f"Knowledge base {item.get('document_id')} ({item.get('section') or 'source section'}): {item['excerpt']}")
    return output
