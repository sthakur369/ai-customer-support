"""Read-only access helpers for the SQLite customer_support_database.

Pass an existing connection to reuse it for a CLI session. If omitted, helpers
open and close a short-lived connection, which is suitable for request-scoped use.
"""

from __future__ import annotations

import sqlite3
import re
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).resolve().parent / "customer_support_database.db"

# SQLite authorizer actions permitted for read-only application queries.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", -1),
}


def _read_only_authorizer(action: int, arg1: str | None, arg2: str | None,
                          database_name: str | None, trigger_name: str | None) -> int:
    """Allow SELECT operations only; deny writes, PRAGMA, ATTACH and DDL."""
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY

    # Do not expose SQLite's internal schema tables through the generic query API.
    if action == sqlite3.SQLITE_READ and arg1 and arg1.startswith("sqlite_"):
        return sqlite3.SQLITE_DENY

    return sqlite3.SQLITE_OK


def start_db() -> sqlite3.Connection:
    """Open and return a read-only connection. Caller must pass it to stop_db()."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. Create it once with: python -m database.seed"
        )

    # mode=ro prevents writes at the SQLite file-open level.
    database_uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row

    # Additional protections: query_only and an authorizer that permits SELECT only.
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.set_authorizer(_read_only_authorizer)
    connection.execute("SELECT 1").fetchone()
    return connection


def check_db(connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Check database availability and return a small health result."""
    own_connection = connection is None
    conn = connection
    try:
        if conn is None:
            conn = start_db()
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "database": DB_PATH.name, "message": "Database is reachable."}
    except (sqlite3.Error, OSError) as exc:
        return {"ok": False, "database": DB_PATH.name, "error": str(exc)}
    finally:
        if own_connection and conn is not None:
            stop_db(conn)


def stop_db(connection: sqlite3.Connection) -> None:
    """Close a connection previously returned by start_db()."""
    connection.close()


def execute_query(
    sql: str,
    params: Iterable[Any] = (),
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Execute one read-only SQL query and return rows as dictionaries.

    Always pass values separately using ? placeholders, never build SQL by
    interpolating user input. This function is for trusted application code;
    never pass raw customer/LLM-generated SQL to it.
    """
    if not isinstance(sql, str) or not sql.strip():
        return {"ok": False, "error": "SQL query cannot be empty.", "columns": [], "rows": [], "row_count": 0}

    statement = sql.lstrip()
    if not (statement[:6].upper() == "SELECT" or statement[:4].upper() == "WITH"):
        return {"ok": False, "error": "Only SELECT queries are allowed.", "columns": [], "rows": [], "row_count": 0}

    own_connection = connection is None
    conn = connection
    try:
        if conn is None:
            conn = start_db()

        cursor = conn.execute(sql, tuple(params))
        rows = [dict(row) for row in cursor.fetchall()]
        columns = [description[0] for description in (cursor.description or [])]
        return {"ok": True, "columns": columns, "rows": rows, "row_count": len(rows)}
    except (sqlite3.Error, OSError, TypeError) as exc:
        return {"ok": False, "error": str(exc), "columns": [], "rows": [], "row_count": 0}
    finally:
        if own_connection and conn is not None:
            stop_db(conn)


def validate_login(
    customer_id_input: str,
    order_id_input: str = "",
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Validate customer ID and optional order ownership using the active connection."""
    raw_customer_id = str(customer_id_input).strip()
    raw_order_id = str(order_id_input).strip()

    if not raw_customer_id:
        return {"ok": False, "message": "Customer ID is required."}
    if not raw_customer_id.isdigit():
        return {"ok": False, "message": "Customer ID must contain digits only."}
    if len(raw_customer_id) > 10:
        return {"ok": False, "message": "Customer ID is too long."}
    if len(raw_order_id) > 64 or (raw_order_id and not re.fullmatch(r"[A-Za-z0-9-]+", raw_order_id)):
        return {"ok": False, "message": "Order ID format is invalid."}
    raw_order_id = raw_order_id.upper()

    customer_id = int(raw_customer_id)
    customer_result = execute_query(
        """SELECT customer_id, first_name, last_name, account_status
           FROM customers WHERE customer_id = ?""",
        (customer_id,), connection,
    )
    if not customer_result["ok"]:
        return {"ok": False, "message": "Unable to validate customer details."}
    if not customer_result["rows"]:
        return {"ok": False, "message": "Customer ID was not found. Please try again."}

    customer = customer_result["rows"][0]
    if customer["account_status"] != "active":
        return {"ok": False, "message": "This customer account is not active. Please contact support."}

    if raw_order_id:
        order_result = execute_query(
            """SELECT order_id FROM orders
               WHERE customer_id = ? AND order_id = ?""",
            (customer_id, raw_order_id), connection,
        )
        if not order_result["ok"]:
            return {"ok": False, "message": "Unable to validate the order. Please try again."}
        if not order_result["rows"]:
            # Same response for nonexistent and another customer's order:
            # do not reveal whether another customer owns the supplied order ID.
            return {"ok": False, "message": "That order ID was not found for this customer."}

    return {
        "ok": True,
        "customer_id": customer_id,
        "order_id": raw_order_id or None,
        "customer": customer,
        "message": "Login successful.",
    }


def get_customer(customer_id: int, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Return minimal customer context for an authenticated customer."""
    result = execute_query(
        """SELECT customer_id, first_name, last_name, account_status
           FROM customers WHERE customer_id = ?""",
        (customer_id,), connection,
    )
    return result["rows"][0] if result["ok"] and result["rows"] else None


def _get_order_context(customer_id: int, order_id: str,
                       connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Return only customer-support-relevant fields for one owned order."""
    order_result = execute_query(
        """SELECT o.order_id, o.order_date, o.order_status, o.total_amount, o.currency,
                  s.carrier, s.shipment_status, s.estimated_delivery, s.delivered_at
           FROM orders AS o
           LEFT JOIN shipments AS s ON s.order_id = o.order_id
           WHERE o.customer_id = ? AND o.order_id = ?""",
        (customer_id, order_id), connection,
    )
    if not order_result["ok"] or not order_result["rows"]:
        return None
    order = order_result["rows"][0]

    items = execute_query(
        """SELECT p.product_name, oi.quantity
           FROM order_items AS oi
           JOIN products AS p ON p.product_id = oi.product_id
           JOIN orders AS o ON o.order_id = oi.order_id
           WHERE o.customer_id = ? AND oi.order_id = ?""",
        (customer_id, order_id), connection,
    )
    payment = execute_query(
        """SELECT payment_method, payment_status, amount
           FROM payments
           WHERE order_id = ?
             AND order_id IN (SELECT order_id FROM orders WHERE customer_id = ?)""",
        (order_id, customer_id), connection,
    )
    refunds = execute_query(
        """SELECT refund_status, amount, reason
           FROM refunds
           WHERE order_id = ?
             AND order_id IN (SELECT order_id FROM orders WHERE customer_id = ?)
           ORDER BY requested_at DESC""",
        (order_id, customer_id), connection,
    )

    order["items"] = items["rows"] if items["ok"] else []
    order["payment"] = payment["rows"][0] if payment["ok"] and payment["rows"] else None
    order["refunds"] = refunds["rows"] if refunds["ok"] else []
    return order


def get_customer_orders(customer_id: int,
                        connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Return support-relevant summaries for all orders owned by this customer."""
    result = execute_query(
        """SELECT order_id FROM orders
           WHERE customer_id = ? ORDER BY order_date DESC""",
        (customer_id,), connection,
    )
    if not result["ok"]:
        return []
    orders = []
    for row in result["rows"]:
        order = _get_order_context(customer_id, row["order_id"], connection)
        if order is not None:
            orders.append(order)
    return orders


def get_recent_customer_orders(customer_id: int, limit: int = 5,
                               connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Return at most `limit` recent orders belonging to the authenticated customer."""
    safe_limit = max(1, min(int(limit), 20))
    result = execute_query(
        """SELECT order_id FROM orders
           WHERE customer_id = ? ORDER BY order_date DESC LIMIT ?""",
        (customer_id, safe_limit), connection,
    )
    if not result["ok"]:
        return []
    orders = []
    for row in result["rows"]:
        order = _get_order_context(customer_id, row["order_id"], connection)
        if order is not None:
            orders.append(order)
    return orders


def get_order_details(customer_id: int, order_id: str,
                      connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Return support-relevant details only if the order belongs to customer_id."""
    return _get_order_context(customer_id, order_id, connection)


def get_customer_context(customer_id: int, order_id: str | None = None,
                         connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Build compact, JSON-serializable context for the final LLM call.

    The customer ID must come from the validated login session. Every query
    includes that ID as an ownership constraint.
    """
    customer = get_customer(customer_id, connection)
    if customer is None:
        return None

    context: dict[str, Any] = {"customer": customer}
    if order_id:
        order = get_order_details(customer_id, order_id, connection)
        if order is None:
            return None
        context["selected_order"] = order
    else:
        context["orders"] = get_customer_orders(customer_id, connection)

    # Include only active tickets relevant to the selected order. A customer's
    # other open tickets remain visible in ticket history, but must not leak into
    # the AI context for an unrelated order.
    if order_id:
        ticket_sql = """SELECT ticket_id, order_id, category, priority, ticket_status, subject
                        FROM tickets
                        WHERE customer_id = ? AND order_id = ?
                          AND ticket_status IN ('open', 'pending_human_review', 'in_progress')
                        ORDER BY created_at DESC LIMIT 5"""
        ticket_params = (customer_id, order_id)
    else:
        ticket_sql = """SELECT ticket_id, order_id, category, priority, ticket_status, subject
                        FROM tickets
                        WHERE customer_id = ?
                          AND ticket_status IN ('open', 'pending_human_review', 'in_progress')
                        ORDER BY created_at DESC LIMIT 5"""
        ticket_params = (customer_id,)

    tickets = execute_query(ticket_sql, ticket_params, connection)
    context["active_tickets"] = tickets["rows"] if tickets["ok"] else []
    return context


if __name__ == "__main__":
    print("[DATABASE] Health:", check_db())
    print("[DATABASE] Customers:", execute_query(
        "SELECT customer_id, first_name, last_name FROM customers ORDER BY customer_id"
    ))
