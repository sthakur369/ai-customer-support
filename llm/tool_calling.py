"""Customer-scoped support tools. No arbitrary SQL or external payment execution."""
from __future__ import annotations

import hashlib
import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from config.settings import LLM_MODEL, REFUND_APPROVAL_THRESHOLD
from database.db import DB_PATH, get_order_details, get_recent_customer_orders
from llm.client import get_client, load_prompt


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required or [], "additionalProperties": False},
        "strict": True,
    }}


TOOLS = [
    _tool("list_recent_orders", "List up to five recent orders for the authenticated customer.", {}),
    _tool("get_order_status", "Get the verified status and total for one order owned by the authenticated customer.",
          {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("get_payment_status", "Get payment status and amount for one owned order. Never return transaction references.",
          {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("get_shipment_status", "Get carrier, shipment status and estimate for one owned order.",
          {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("check_refund_eligibility", "Check deterministic technical refund eligibility for one owned order. Company policy must still come from retrieved policy evidence.",
          {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("create_refund_request", "Create an idempotent refund request only when the customer explicitly asks to submit one. This does not move money or process a refund.",
          {"order_id": {"type": "string"}, "reason": {"type": "string"}}, ["order_id", "reason"]),
]


def _get_owned_order(customer_id: int, arguments: dict) -> tuple[str, dict | None]:
    order_id = str(arguments.get("order_id", "")).strip().upper()
    if not re.fullmatch(r"ORD-[A-Z0-9-]{1,55}", order_id):
        return order_id, None
    return order_id, get_order_details(customer_id, order_id)


def _refund_eligibility(order: dict | None) -> dict:
    if not order:
        return {"eligible": False, "reason": "That order was not found for this customer."}
    payment = order.get("payment") or {}
    if payment.get("payment_status") not in {"paid", "partially_refunded"}:
        return {"eligible": False, "reason": "The payment is not in a refundable paid state."}
    existing = order.get("refunds") or []
    active = next((r for r in existing if r.get("refund_status") in {"requested", "under_review", "approved", "processed"}), None)
    if active:
        return {"eligible": False, "reason": "A refund request or completed refund already exists for this order.",
                "existing_status": active.get("refund_status")}
    if float(payment.get("amount") or 0) <= 0:
        return {"eligible": False, "reason": "No refundable payment amount is recorded."}
    return {"eligible": True, "amount": float(payment.get("amount")), "currency": order.get("currency", "INR"),
            "note": "Technical data checks passed. Company policy and final approval still apply."}


def _existing_refund_request(customer_id: int, order_id: str) -> dict | None:
    """Return the existing result for a retry before checking current eligibility."""
    idem = hashlib.sha256(f"refund-request:{customer_id}:{order_id}".encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT refund_id,refund_status,amount FROM refunds WHERE idempotency_key=?", (idem,)
        ).fetchone()
        if not row:
            return None
        return {"ok": True, "created": False, "refund_id": row["refund_id"],
                "status": row["refund_status"], "amount": row["amount"],
                "message": "The same refund request already exists; no duplicate was created."}
    finally:
        conn.close()


def _create_refund_request(customer_id: int, order_id: str, reason: str) -> dict:
    """Insert one request with ownership checks and a database-enforced idempotency key."""
    reason = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", reason).strip()[:300]
    if not reason:
        return {"ok": False, "error": "A short refund reason is required."}
    idem = hashlib.sha256(f"refund-request:{customer_id}:{order_id}".encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT refund_id,refund_status,amount FROM refunds WHERE idempotency_key=?", (idem,)).fetchone()
        if existing:
            conn.commit()
            return {"ok": True, "created": False, "refund_id": existing["refund_id"],
                    "status": existing["refund_status"], "amount": existing["amount"],
                    "message": "The same refund request already exists; no duplicate was created."}
        row = conn.execute(
            """SELECT o.order_id,o.customer_id,p.payment_id,p.payment_status,p.amount
               FROM orders o JOIN payments p ON p.order_id=o.order_id
               WHERE o.order_id=? AND o.customer_id=?""", (order_id, customer_id)
        ).fetchone()
        if not row:
            conn.rollback()
            return {"ok": False, "error": "That order was not found for this customer."}
        if row["payment_status"] not in {"paid", "partially_refunded"} or float(row["amount"] or 0) <= 0:
            conn.rollback()
            return {"ok": False, "error": "This order does not have a refundable paid amount."}
        old = conn.execute(
            "SELECT refund_id,refund_status FROM refunds WHERE order_id=? AND refund_status IN ('requested','under_review','approved','processed') ORDER BY requested_at DESC LIMIT 1",
            (order_id,)
        ).fetchone()
        if old:
            conn.rollback()
            return {"ok": False, "error": "A refund request or completed refund already exists for this order.",
                    "existing_status": old["refund_status"]}
        amount = float(row["amount"])
        requires_approval = amount > REFUND_APPROVAL_THRESHOLD
        status = "under_review" if requires_approval else "requested"
        refund_id = "RFD-" + uuid.uuid4().hex[:12].upper()
        conn.execute(
            """INSERT INTO refunds(refund_id,order_id,payment_id,refund_status,amount,reason,requested_at,processed_at,idempotency_key)
               VALUES(?,?,?,?,?,?,?,NULL,?)""",
            (refund_id, order_id, row["payment_id"], status, amount, reason,
             datetime.now(timezone.utc).isoformat(), idem)
        )
        conn.commit()
        return {"ok": True, "created": True, "refund_id": refund_id, "status": status,
                "amount": amount, "approval_required": requires_approval,
                "message": "Refund request recorded. No money has been transferred or refunded."}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _explicit_refund_intent(question: str) -> bool:
    """Require clear positive consent; reject negated/cancelled refund requests."""
    text = re.sub(r"\s+", " ", str(question).casefold()).strip()
    negative = re.search(
        r"\b(?:don't|dont|do not|not|never|cancel|stop|no longer)\b.{0,55}\b(?:want|need|request|submit|initiate|process|refund|money back)\b|"
        r"\b(?:don't|dont|do not|never)\b.{0,30}\b(?:give|send)\b.{0,20}\brefund\b",
        text,
    )
    if negative:
        return False
    positive_patterns = (
        r"\b(?:please )?(?:request|submit|initiate|start) (?:a )?refund\b",
        r"\b(?:i want|i need|i would like) (?:to )?(?:(?:request|submit|initiate) )?(?:a )?refund\b",
        r"\b(?:please )?get (?:me )?(?:a )?refund\b",
        r"\brefund (?:please|for me)\b",
    )
    return any(re.search(pattern, text) for pattern in positive_patterns)


def _execute(name: str, arguments: dict, customer_id: int, question: str) -> dict:
    # Authenticated identity is injected by the server, never accepted from model arguments.
    allowed_names = {item["function"]["name"] for item in TOOLS}
    if name not in allowed_names:
        return {"ok": False, "error": "Tool is not permitted."}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "Tool arguments must be an object."}
    if name == "list_recent_orders":
        if arguments:
            return {"ok": False, "error": "This tool does not accept arguments."}
        orders = get_recent_customer_orders(customer_id, 5)
        return {"ok": True, "orders": [
            {"order_id": o.get("order_id"), "order_status": o.get("order_status"),
             "total_amount": o.get("total_amount"), "currency": o.get("currency")}
            for o in orders
        ]}
    allowed_arguments = {
        "get_order_status": {"order_id"},
        "get_payment_status": {"order_id"},
        "get_shipment_status": {"order_id"},
        "check_refund_eligibility": {"order_id"},
        "create_refund_request": {"order_id", "reason"},
    }
    if set(arguments) - allowed_arguments.get(name, set()):
        return {"ok": False, "error": "Unexpected tool arguments were rejected."}
    order_id, order = _get_owned_order(customer_id, arguments)
    if order is None:
        return {"ok": False, "error": "That order was not found for this customer or the order ID is invalid."}
    if name == "get_order_status":
        return {"ok": True, "order_id": order_id, "order_status": order.get("order_status"),
                "order_date": order.get("order_date"), "total_amount": order.get("total_amount"),
                "currency": order.get("currency")}
    if name == "get_payment_status":
        payment = order.get("payment") or {}
        return {"ok": True, "order_id": order_id, "payment_status": payment.get("payment_status"),
                "amount": payment.get("amount"), "currency": order.get("currency")}
    if name == "get_shipment_status":
        return {"ok": True, "order_id": order_id, "shipment_status": order.get("shipment_status"),
                "carrier": order.get("carrier"), "estimated_delivery": order.get("estimated_delivery"),
                "delivered_at": order.get("delivered_at")}
    if name == "check_refund_eligibility":
        return {"ok": True, "order_id": order_id, **_refund_eligibility(order)}
    if name == "create_refund_request":
        if not _explicit_refund_intent(question):
            return {"ok": False, "confirmation_required": True,
                    "error": "The customer has not clearly asked to submit a refund request. Ask for explicit confirmation first."}
        previous = _existing_refund_request(customer_id, order_id)
        if previous:
            return previous
        eligibility = _refund_eligibility(order)
        if not eligibility.get("eligible"):
            return {"ok": False, **eligibility}
        return _create_refund_request(customer_id, order_id, str(arguments.get("reason", "")))
    return {"ok": False, "error": "Tool is not permitted."}


def run_support_tool_calls(question: str, customer_id: int, customer_context: dict | None = None) -> tuple[list[dict], float]:
    """Use bounded allowlisted tools only after ML/security/RAG orchestration."""
    started = time.perf_counter()
    if not customer_id:
        return [], 0.0
    prompt = load_prompt("tool_selector")
    selected = (customer_context or {}).get("selected_order") or {}
    order_summaries = [
        {"order_id": o.get("order_id"), "order_status": o.get("order_status")}
        for o in (customer_context or {}).get("orders", [])[:5]
    ]
    user_payload = {
        "customer_question": question,
        "verified_selected_order": {
            "order_id": selected.get("order_id"),
            "order_status": selected.get("order_status"),
            "shipment_status": selected.get("shipment_status"),
            "payment_status": (selected.get("payment") or {}).get("payment_status"),
        } if selected else None,
        "verified_customer_order_ids": order_summaries,
        "available_tool_names": [item["function"]["name"] for item in TOOLS],
    }
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}]
    client = get_client()
    results = []
    total_calls = 0
    for _ in range(3):
        request = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        if LLM_MODEL.lower().startswith("gpt-6"):
            request["reasoning_effort"] = "none"
        response = client.chat.completions.create(**request)
        message = response.choices[0].message
        if not message.tool_calls:
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            if total_calls >= 3:
                break
            total_calls += 1
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object.")
                result = _execute(call.function.name, args, customer_id, question)
            except Exception as exc:
                result = {"ok": False, "error": f"Tool execution failed: {type(exc).__name__}."}
            results.append({"tool": call.function.name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
        if total_calls >= 3:
            break
    return results, round(time.perf_counter() - started, 4)
