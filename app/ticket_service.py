"""Persistent one-row-per-ticket support conversations.

Conversation messages and workflow state are JSON columns. Writes use a short
BEGIN IMMEDIATE transaction and a version counter to prevent lost updates.
The existing read-only customer database API remains unchanged.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.db import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def initialize_support_schema() -> None:
    """Create additive support-conversation storage; never resets existing data."""
    conn = _connect()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS support_conversations (
            conversation_id TEXT PRIMARY KEY,
            ticket_number TEXT NOT NULL UNIQUE,
            customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
            order_id TEXT,
            ticket_type TEXT NOT NULL DEFAULT 'temporary'
                CHECK (ticket_type IN ('temporary', 'official')),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'awaiting_customer', 'under_review', 'resolved', 'closed')),
            conversation_json TEXT NOT NULL DEFAULT '[]'
                CHECK (json_valid(conversation_json)),
            state_json TEXT NOT NULL DEFAULT '{}'
                CHECK (json_valid(state_json)),
            created_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            closed_at TEXT,
            closure_reason TEXT,
            resolution_notes TEXT,
            human_intervention_required INTEGER NOT NULL DEFAULT 0
                CHECK (human_intervention_required IN (0, 1)),
            official_ticket_id TEXT,
            version INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_support_conversations_customer_status
            ON support_conversations(customer_id, status, last_activity_at);
        CREATE INDEX IF NOT EXISTS idx_support_conversations_inactive
            ON support_conversations(status, ticket_type, last_activity_at);
        """)
        # Additive link from the existing official ticket table to this JSON chat.
        ticket_columns = {
            item["name"] for item in conn.execute("PRAGMA table_info(tickets)").fetchall()
        }
        if "support_conversation_id" not in ticket_columns:
            conn.execute(
                "ALTER TABLE tickets ADD COLUMN support_conversation_id TEXT "
                "REFERENCES support_conversations(conversation_id)"
            )
        # Staff triage fields also live on temporary conversations, before an
        # official legacy ticket has been created. Additive migration only.
        conversation_columns = {
            item["name"] for item in conn.execute("PRAGMA table_info(support_conversations)").fetchall()
        }
        for column, declaration in (("category", "TEXT"), ("priority", "TEXT"), ("assigned_team", "TEXT")):
            if column not in conversation_columns:
                conn.execute(f"ALTER TABLE support_conversations ADD COLUMN {column} {declaration}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_support_conversation "
            "ON tickets(support_conversation_id)"
        )
        # Schema migration marker, useful for diagnosis.
        conn.execute("CREATE TABLE IF NOT EXISTS support_schema_meta (version INTEGER NOT NULL)")
        if conn.execute("SELECT COUNT(*) FROM support_schema_meta").fetchone()[0] == 0:
            conn.execute("INSERT INTO support_schema_meta(version) VALUES (1)")
    finally:
        conn.close()


def create_conversation(customer_id: int, order_id: str | None = None) -> dict[str, Any]:
    """Create one temporary support ticket per customer/order pair."""
    now = utc_now()
    conversation_id = str(uuid.uuid4())
    ticket_number = f"TMP-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """SELECT conversation_id, ticket_number, status FROM support_conversations
               WHERE customer_id = ? AND order_id IS ? AND status IN ('open', 'awaiting_customer', 'under_review')
               ORDER BY created_at DESC LIMIT 1""", (customer_id, order_id)
        ).fetchone()
        if existing:
            conn.commit()
            return {"ok": False, "existing": dict(existing),
                    "message": "This customer already has an active support conversation."}
        conn.execute(
            """INSERT INTO support_conversations
               (conversation_id, ticket_number, customer_id, order_id, ticket_type,
                status, conversation_json, state_json, created_at, last_activity_at)
               VALUES (?, ?, ?, ?, 'temporary', 'open', '[]', '{}', ?, ?)""",
            (conversation_id, ticket_number, customer_id, order_id, now, now),
        )
        conn.commit()
        return {"ok": True, "conversation_id": conversation_id,
                "ticket_number": ticket_number, "status": "open"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_active_conversation(customer_id: int, order_id: str | None = None) -> dict[str, Any] | None:
    conn = _connect()
    try:
        if order_id is None:
            row = conn.execute(
                """SELECT conversation_id FROM support_conversations
                   WHERE customer_id = ? AND status IN ('open', 'awaiting_customer', 'under_review')
                   ORDER BY created_at DESC LIMIT 1""", (customer_id,)
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT conversation_id FROM support_conversations
                   WHERE customer_id = ? AND order_id = ? AND status IN ('open', 'awaiting_customer', 'under_review')
                   ORDER BY created_at DESC LIMIT 1""", (customer_id, order_id)
            ).fetchone()
        return get_conversation(row["conversation_id"], customer_id) if row else None
    finally:
        conn.close()


def get_conversation(conversation_id: str, customer_id: int | None = None) -> dict[str, Any] | None:
    conn = _connect()
    try:
        if customer_id is None:
            row = conn.execute(
                "SELECT * FROM support_conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM support_conversations
                   WHERE conversation_id = ? AND customer_id = ?""",
                (conversation_id, customer_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["conversation"] = json.loads(result.pop("conversation_json"))
        result["state"] = json.loads(result.pop("state_json"))
        return result
    finally:
        conn.close()


def _mutate(conversation_id: str, mutator) -> dict[str, Any]:
    """Serialize a read-modify-write of JSON and metadata in one SQLite transaction."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM support_conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return {"ok": False, "error": "Conversation not found."}
        current = dict(row)
        current["conversation"] = json.loads(current.pop("conversation_json"))
        current["state"] = json.loads(current.pop("state_json"))
        changes = mutator(current)
        if changes is None:
            conn.rollback()
            return {"ok": False, "error": "Conversation is not active."}
        conversation_json = json.dumps(current["conversation"], ensure_ascii=False, separators=(",", ":"))
        state_json = json.dumps(current["state"], ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            """UPDATE support_conversations SET
               conversation_json = ?, state_json = ?, status = ?, order_id = ?,
               ticket_type = ?, last_activity_at = ?, closed_at = ?, closure_reason = ?,
               resolution_notes = ?, human_intervention_required = ?,
               official_ticket_id = ?, ticket_number = ?, version = version + 1
               WHERE conversation_id = ? AND version = ?""",
            (conversation_json, state_json, current["status"], current["order_id"],
             current["ticket_type"], current["last_activity_at"], current["closed_at"],
             current["closure_reason"], current["resolution_notes"],
             current["human_intervention_required"], current["official_ticket_id"],
             current["ticket_number"], conversation_id, current["version"]),
        )
        if conn.total_changes < 1:
            conn.rollback()
            return {"ok": False, "error": "Conversation changed concurrently; please retry."}
        conn.commit()
        return {"ok": True, "version": current["version"] + 1, **changes}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def append_message(conversation_id: str, sender: str, message: str,
                   metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if sender not in {"customer", "assistant", "system", "agent"}:
        raise ValueError("Unsupported message sender.")
    if not isinstance(message, str) or not message.strip():
        return {"ok": False, "error": "Message cannot be empty."}

    def mutate(row):
        if row["status"] not in {"open", "awaiting_customer", "under_review"}:
            return None
        item = {"role": sender, "message": message, "timestamp": utc_now()}
        if metadata:
            item["metadata"] = metadata
        row["conversation"].append(item)
        row["last_activity_at"] = item["timestamp"]
        return {"message_count": len(row["conversation"])}
    return _mutate(conversation_id, mutate)


def replace_last_assistant_message(conversation_id: str, message: str) -> dict[str, Any]:
    def mutate(row):
        if row["status"] not in {"open", "awaiting_customer", "under_review"}:
            return None
        for item in reversed(row["conversation"]):
            if item.get("role") == "assistant":
                item["message"] = message
                item["timestamp"] = utc_now()
                row["last_activity_at"] = item["timestamp"]
                return {"message_count": len(row["conversation"])}
        return None
    return _mutate(conversation_id, mutate)


def update_state(conversation_id: str, state: dict[str, Any],
                 status: str | None = None) -> dict[str, Any]:
    allowed = {"open", "awaiting_customer", "under_review", "resolved", "closed"}
    if status is not None and status not in allowed:
        raise ValueError("Invalid support conversation status.")

    def mutate(row):
        if row["status"] not in {"open", "awaiting_customer", "under_review"}:
            return None
        row["state"] = state
        if status:
            row["status"] = status
        row["last_activity_at"] = utc_now()
        return {"status": row["status"]}
    return _mutate(conversation_id, mutate)


def select_order(conversation_id: str, customer_id: int, order_id: str) -> dict[str, Any]:
    """Set an order only if it belongs to this conversation's customer."""
    conn = _connect()
    try:
        owns_order = conn.execute(
            "SELECT 1 FROM orders WHERE customer_id = ? AND order_id = ?",
            (customer_id, order_id),
        ).fetchone()
        if not owns_order:
            return {"ok": False, "error": "That order ID was not found for this customer."}
    finally:
        conn.close()

    def mutate(row):
        if row["customer_id"] != customer_id or row["status"] not in {"open", "awaiting_customer"}:
            return None
        row["order_id"] = order_id
        row["state"] = {}
        row["status"] = "open"
        row["last_activity_at"] = utc_now()
        return {"order_id": order_id}
    return _mutate(conversation_id, mutate)


def close_conversation(conversation_id: str, reason: str,
                       notes: str | None = None, resolved: bool = False) -> dict[str, Any]:
    def mutate(row):
        if row["status"] not in {"open", "awaiting_customer", "under_review"}:
            return None
        row["status"] = "resolved" if resolved else "closed"
        row["closed_at"] = utc_now()
        row["last_activity_at"] = row["closed_at"]
        row["closure_reason"] = reason
        row["resolution_notes"] = notes
        row["state"] = {}
        return {"status": row["status"], "closure_reason": reason}
    return _mutate(conversation_id, mutate)


def escalate_conversation(conversation_id: str, reason: str,
                          summary: str, category: str = "general",
                          priority: str = "medium",
                          assigned_team: str = "Customer Support") -> dict[str, Any]:
    """Create an official legacy ticket and link it without moving JSON history."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM support_conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.rollback()
            return {"ok": False, "error": "Conversation not found."}
        if row["ticket_type"] == "official" and row["official_ticket_id"]:
            conn.commit()
            return {"ok": True, "ticket_number": row["ticket_number"],
                    "official_ticket_id": row["official_ticket_id"], "already_escalated": True}
        if row["status"] not in {"open", "awaiting_customer"}:
            conn.rollback()
            return {"ok": False, "error": "Conversation is not eligible for escalation."}

        now = utc_now()
        official_id = f"NST-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
        subject = (reason or "Customer support request").strip()[:240]
        conn.execute(
            """INSERT INTO tickets
               (ticket_id, customer_id, conversation_id, order_id, category, priority,
                ticket_status, assigned_team, subject, created_at, updated_at,
                support_conversation_id)
               VALUES (?, ?, NULL, ?, ?, ?, 'pending_human_review', ?, ?, ?, ?, ?)""",
            (official_id, row["customer_id"], row["order_id"], category, priority,
             assigned_team, subject, now, now, conversation_id),
        )
        conn.execute(
            """INSERT INTO ticket_events
               (ticket_id, event_type, event_description, actor, created_at)
               VALUES (?, 'created', ?, 'system', ?)""",
            (official_id, reason[:1000], now),
        )
        conn.execute(
            """UPDATE support_conversations SET ticket_type = 'official',
               ticket_number = ?, official_ticket_id = ?, status = 'under_review',
               human_intervention_required = 1, resolution_notes = ?,
               last_activity_at = ?, version = version + 1
               WHERE conversation_id = ? AND version = ?""",
            (official_id, official_id, summary[:4000], now, conversation_id, row["version"]),
        )
        conn.commit()
        return {"ok": True, "ticket_number": official_id,
                "official_ticket_id": official_id, "status": "under_review"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_inactive_conversations(timeout_minutes: int = 15) -> int:
    """Close expired temporary chats. Safe to run repeatedly from a worker."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT conversation_id FROM support_conversations
               WHERE ticket_type = 'temporary' AND status IN ('open', 'awaiting_customer')
                 AND last_activity_at <= ?""", (cutoff,)
        ).fetchall()
        now = utc_now()
        for row in rows:
            conn.execute(
                """UPDATE support_conversations SET status = 'closed', closed_at = ?,
                   closure_reason = 'inactive_timeout',
                   resolution_notes = 'Automatically closed after 15 minutes without activity.',
                   state_json = '{}', version = version + 1
                   WHERE conversation_id = ? AND status IN ('open', 'awaiting_customer')
                     AND ticket_type = 'temporary'""",
                (now, row["conversation_id"]),
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_timeout_worker(interval_seconds: int = 30, timeout_minutes: int = 15) -> None:
    """Run as a separate process in deployments; safe to run alongside app workers."""
    import time
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    initialize_support_schema()
    logging.info("Support ticket timeout worker started (timeout=%s minutes).", timeout_minutes)
    try:
        while True:
            try:
                count = close_inactive_conversations(timeout_minutes)
                if count:
                    logging.info("Closed %s inactive support conversation(s).", count)
            except Exception:
                logging.exception("Inactivity sweep failed.")
            time.sleep(max(5, interval_seconds))
    except KeyboardInterrupt:
        logging.info("Support ticket timeout worker stopped.")


if __name__ == "__main__":
    run_timeout_worker()
