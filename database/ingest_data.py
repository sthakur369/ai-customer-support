"""Create/reset the small, deterministic synthetic demo database.

Run once (or whenever you intentionally want to reset the demo data):
    python -m database.seed  # compatibility entry point
    python -m database.ingest_data
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.db import DB_PATH

DATABASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DATABASE_DIR / "schema.sql"

CUSTOMERS = [
    (1, "Aarav", "Sharma", "aarav.sharma@example.test", "+91-9000000001", "2025-01-10T09:00:00Z", "active"),
    (2, "Diya", "Mehta", "diya.mehta@example.test", "+91-9000000002", "2025-01-14T10:30:00Z", "active"),
    (3, "Kabir", "Verma", "kabir.verma@example.test", "+91-9000000003", "2025-02-02T08:15:00Z", "active"),
    (4, "Anaya", "Nair", "anaya.nair@example.test", "+91-9000000004", "2025-02-18T12:00:00Z", "active"),
    (5, "Ishaan", "Rao", "ishaan.rao@example.test", "+91-9000000005", "2025-03-05T11:20:00Z", "active"),
    (6, "Meera", "Kapoor", "meera.kapoor@example.test", "+91-9000000006", "2025-03-19T14:45:00Z", "active"),
    (7, "Vivaan", "Iyer", "vivaan.iyer@example.test", "+91-9000000007", "2025-04-01T09:40:00Z", "active"),
    (8, "Sara", "Khan", "sara.khan@example.test", "+91-9000000008", "2025-04-11T16:10:00Z", "active"),
    (9, "Arjun", "Das", "arjun.das@example.test", "+91-9000000009", "2025-05-07T13:25:00Z", "active"),
    (10, "Tara", "Menon", "tara.menon@example.test", "+91-9000000010", "2025-05-21T10:05:00Z", "active"),
]

ADDRESSES = [
    (1, 1, "shipping", "12 MG Road", "Bengaluru", "Karnataka", "560001", "India", 1),
    (2, 2, "shipping", "44 Baner Road", "Pune", "Maharashtra", "411045", "India", 1),
    (3, 3, "shipping", "8 Sector 17", "Chandigarh", "Chandigarh", "160017", "India", 1),
    (4, 4, "shipping", "21 Kakkanad", "Kochi", "Kerala", "682030", "India", 1),
    (5, 5, "shipping", "17 Banjara Hills", "Hyderabad", "Telangana", "500034", "India", 1),
    (6, 6, "shipping", "6 Andheri East", "Mumbai", "Maharashtra", "400069", "India", 1),
    (7, 7, "shipping", "31 Indiranagar", "Bengaluru", "Karnataka", "560038", "India", 1),
    (8, 8, "shipping", "15 Salt Lake", "Kolkata", "West Bengal", "700091", "India", 1),
    (9, 9, "shipping", "9 Civil Lines", "Jaipur", "Rajasthan", "302006", "India", 1),
    (10, 10, "shipping", "22 Vyttila", "Kochi", "Kerala", "682019", "India", 1),
    (11, 1, "billing", "12 MG Road", "Bengaluru", "Karnataka", "560001", "India", 1),
    (12, 6, "billing", "6 Andheri East", "Mumbai", "Maharashtra", "400069", "India", 1),
]

PRODUCTS = [
    (1, "NS-AUD-001", "Wireless Headphones", "Electronics", 2499.00, 1),
    (2, "NS-MOB-002", "USB-C Charger", "Electronics", 899.00, 1),
    (3, "NS-HOM-003", "Electric Kettle", "Home", 1599.00, 1),
    (4, "NS-HOM-004", "Desk Lamp", "Home", 1199.00, 1),
    (5, "NS-FIT-005", "Fitness Band", "Fitness", 1999.00, 1),
    (6, "NS-ACC-006", "Laptop Sleeve", "Accessories", 699.00, 1),
    (7, "NS-ACC-007", "Premium Gift Card", "Gift Cards", 1000.00, 0),
    (8, "NS-KIT-008", "Steel Water Bottle", "Kitchen", 499.00, 1),
    (9, "NS-ELE-009", "Bluetooth Speaker", "Electronics", 1799.00, 1),
    (10, "NS-HOM-010", "Air Fryer", "Home", 5499.00, 1),
    (11, "NS-ACC-011", "Phone Case", "Accessories", 399.00, 1),
    (12, "NS-STA-012", "Notebook Set", "Stationery", 299.00, 1),
]

# order_id, customer_id, address_id, date, status, total, payment status, shipment status
ORDERS = [
    ("ORD-1001", 1, 1, "2026-10-02T10:00:00Z", "delivered", 2499.00, "paid", "delivered"),
    ("ORD-1002", 1, 1, "2026-11-10T12:15:00Z", "shipped", 899.00, "paid", "in_transit"),
    ("ORD-1003", 2, 2, "2026-10-18T09:30:00Z", "delivered", 1599.00, "partially_refunded", "delivered"),
    ("ORD-1004", 2, 2, "2026-11-19T14:00:00Z", "processing", 1199.00, "paid", "label_created"),
    ("ORD-1005", 3, 3, "2026-11-12T11:00:00Z", "cancelled", 1999.00, "refunded", "returned"),
    ("ORD-1006", 4, 4, "2026-11-15T08:45:00Z", "delivered", 699.00, "paid", "delivered"),
    ("ORD-1007", 5, 5, "2026-11-17T16:20:00Z", "shipped", 1799.00, "paid", "delayed"),
    ("ORD-1008", 6, 6, "2026-10-28T13:10:00Z", "delivered", 5499.00, "partially_refunded", "delivered"),
    ("ORD-1009", 6, 6, "2026-11-20T10:10:00Z", "confirmed", 499.00, "paid", "label_created"),
    ("ORD-1010", 7, 7, "2026-11-18T09:05:00Z", "processing", 1398.00, "paid", "label_created"),
    ("ORD-1011", 8, 8, "2026-11-16T15:45:00Z", "delivered", 1799.00, "paid", "delivered"),
    ("ORD-1012", 9, 9, "2026-11-21T12:00:00Z", "placed", 1298.00, "pending", "label_created"),
    ("ORD-1013", 10, 10, "2026-11-13T10:30:00Z", "delivered", 1000.00, "paid", "delivered"),
    ("ORD-1014", 3, 3, "2026-11-22T09:20:00Z", "confirmed", 299.00, "failed", "label_created"),
    ("ORD-1015", 5, 5, "2026-11-23T08:00:00Z", "placed", 899.00, "pending", "label_created"),
]

# Each order gets one or two line items. Values are deliberately simple demo data.
ORDER_ITEMS = [
    ("ORD-1001", 1, 1), ("ORD-1002", 2, 1), ("ORD-1003", 3, 1),
    ("ORD-1004", 4, 1), ("ORD-1005", 5, 1), ("ORD-1006", 6, 1),
    ("ORD-1007", 9, 1), ("ORD-1008", 10, 1), ("ORD-1009", 8, 1),
    ("ORD-1010", 6, 2), ("ORD-1011", 9, 1), ("ORD-1012", 2, 1),
    ("ORD-1012", 11, 1), ("ORD-1013", 7, 1), ("ORD-1014", 12, 1),
    ("ORD-1015", 2, 1),
]

CONVERSATIONS = [
    ("CONV-2001", 1, "Headphones order status", "open", "2026-11-10T12:20:00Z", "2026-11-10T12:25:00Z"),
    ("CONV-2002", 2, "Partial refund query", "open", "2026-10-20T10:00:00Z", "2026-10-20T10:10:00Z"),
    ("CONV-2003", 3, "Cancelled order refund", "closed", "2026-11-12T12:00:00Z", "2026-11-13T09:00:00Z"),
    ("CONV-2004", 4, "Product information", "closed", "2026-11-15T09:00:00Z", "2026-11-15T09:10:00Z"),
    ("CONV-2005", 5, "Delayed shipment", "open", "2026-11-18T10:00:00Z", "2026-11-18T10:15:00Z"),
    ("CONV-2006", 6, "Air fryer refund", "open", "2026-10-30T11:00:00Z", "2026-10-30T11:20:00Z"),
    ("CONV-2007", 7, "Order processing", "open", "2026-11-18T10:00:00Z", "2026-11-18T10:05:00Z"),
    ("CONV-2008", 8, "Speaker delivery", "closed", "2026-11-16T16:00:00Z", "2026-11-17T10:00:00Z"),
    ("CONV-2009", 9, "Payment pending", "open", "2026-11-21T12:10:00Z", "2026-11-21T12:15:00Z"),
    ("CONV-2010", 10, "Gift card query", "closed", "2026-11-13T11:00:00Z", "2026-11-13T11:05:00Z"),
]

MESSAGES = [
    ("CONV-2001", "customer", "Can you tell me where my headphones order is?", "2026-11-10T12:20:00Z"),
    ("CONV-2001", "assistant", "I can help check the shipment status. Please allow me a moment.", "2026-11-10T12:21:00Z"),
    ("CONV-2001", "customer", "Thank you.", "2026-11-10T12:25:00Z"),
    ("CONV-2002", "customer", "I received only part of my refund.", "2026-10-20T10:00:00Z"),
    ("CONV-2002", "assistant", "I can check the refund record for your order.", "2026-10-20T10:02:00Z"),
    ("CONV-2003", "customer", "My cancelled order refund has not appeared yet.", "2026-11-12T12:00:00Z"),
    ("CONV-2003", "assistant", "I will check the recorded refund status.", "2026-11-12T12:02:00Z"),
    ("CONV-2004", "customer", "Is my item covered by the return policy?", "2026-11-15T09:00:00Z"),
    ("CONV-2004", "assistant", "I can explain the applicable policy.", "2026-11-15T09:02:00Z"),
    ("CONV-2005", "customer", "The delivery is delayed. Can you check it?", "2026-11-18T10:00:00Z"),
    ("CONV-2005", "assistant", "I will look up the latest shipment information.", "2026-11-18T10:02:00Z"),
    ("CONV-2006", "customer", "I returned the air fryer. What is the refund status?", "2026-10-30T11:00:00Z"),
    ("CONV-2006", "assistant", "I can check the refund record linked to your order.", "2026-10-30T11:03:00Z"),
    ("CONV-2007", "customer", "My order is still processing.", "2026-11-18T10:00:00Z"),
    ("CONV-2007", "assistant", "I will check the current order status.", "2026-11-18T10:03:00Z"),
    ("CONV-2008", "customer", "My speaker arrived. Thank you.", "2026-11-16T16:00:00Z"),
    ("CONV-2008", "assistant", "Glad to hear it was delivered.", "2026-11-16T16:02:00Z"),
    ("CONV-2009", "customer", "My payment is pending. Was the order placed?", "2026-11-21T12:10:00Z"),
    ("CONV-2009", "assistant", "I will verify the payment and order records.", "2026-11-21T12:12:00Z"),
    ("CONV-2010", "customer", "Can I return a gift card?", "2026-11-13T11:00:00Z"),
    ("CONV-2010", "assistant", "I can check the product's return eligibility.", "2026-11-13T11:02:00Z"),
]

TICKETS = [
    ("TKT-3001", 1, "CONV-2001", "ORD-1002", "order_status", "low", "open", "Customer Support", "Shipment status request", "2026-11-10T12:25:00Z", "2026-11-10T12:25:00Z"),
    ("TKT-3002", 2, "CONV-2002", "ORD-1003", "refund", "medium", "in_progress", "Payments", "Partial refund query", "2026-10-20T10:10:00Z", "2026-10-21T09:00:00Z"),
    ("TKT-3003", 3, "CONV-2003", "ORD-1005", "refund", "medium", "resolved", "Payments", "Refund for cancelled order", "2026-11-12T12:05:00Z", "2026-11-13T09:00:00Z"),
    ("TKT-3004", 4, "CONV-2004", "ORD-1006", "return_policy", "low", "closed", "Customer Support", "Return policy question", "2026-11-15T09:05:00Z", "2026-11-15T09:10:00Z"),
    ("TKT-3005", 5, "CONV-2005", "ORD-1007", "shipping_delay", "high", "pending_human_review", "Customer Support", "Delayed shipment complaint", "2026-11-18T10:15:00Z", "2026-11-18T10:15:00Z"),
    ("TKT-3006", 6, "CONV-2006", "ORD-1008", "refund", "medium", "in_progress", "Payments", "Air fryer refund status", "2026-10-30T11:20:00Z", "2026-10-31T09:00:00Z"),
    ("TKT-3007", 7, "CONV-2007", "ORD-1010", "order_status", "low", "open", "Customer Support", "Order processing status", "2026-11-18T10:05:00Z", "2026-11-18T10:05:00Z"),
    ("TKT-3008", 9, "CONV-2009", "ORD-1012", "payment_failure", "high", "pending_human_review", "Payments", "Payment pending verification", "2026-11-21T12:15:00Z", "2026-11-21T12:15:00Z"),
]


def main() -> None:
    """Create schema and insert deterministic demo records."""
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(schema)
        with connection:
            # Clear in dependency order so running this script resets the demo data.
            for table in (
                "ticket_events", "tickets", "support_conversations", "messages", "conversations", "refunds",
                "shipments", "payments", "order_items", "orders", "products",
                "addresses", "customers",
            ):
                connection.execute(f"DELETE FROM {table}")

            connection.executemany(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", CUSTOMERS
            )
            connection.executemany(
                "INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ADDRESSES
            )
            connection.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)", PRODUCTS
            )

            product_prices = {row[0]: row[4] for row in PRODUCTS}
            order_lookup = {row[0]: row for row in ORDERS}
            item_rows = []
            order_totals = {row[0]: 0.0 for row in ORDERS}
            for item_id, (order_id, product_id, quantity) in enumerate(ORDER_ITEMS, start=1):
                unit_price = product_prices[product_id]
                line_total = round(unit_price * quantity, 2)
                item_rows.append((item_id, order_id, product_id, quantity, unit_price, line_total))
                order_totals[order_id] += line_total

            # Use item-derived totals so order totals always reconcile.
            adjusted_orders = []
            for row in ORDERS:
                order_id, customer_id, address_id, order_date, status, _total, *_ = row
                adjusted_orders.append((order_id, customer_id, address_id, order_date, status,
                                        round(order_totals[order_id], 2), "INR"))
            connection.executemany(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", adjusted_orders
            )
            connection.executemany(
                "INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)", item_rows
            )

            payment_rows = []
            shipment_rows = []
            for index, row in enumerate(ORDERS, start=1):
                order_id, _customer_id, _address_id, order_date, order_status, _total, payment_status, shipment_status = row
                amount = round(order_totals[order_id], 2)
                payment_id = f"PAY-{4000 + index}"
                paid_at = order_date if payment_status in {"paid", "partially_refunded", "refunded"} else None
                payment_rows.append((payment_id, order_id, "UPI" if index % 2 else "Card",
                                     payment_status, amount, f"TXN-{5000 + index}" if paid_at else None, paid_at))
                shipment_rows.append((f"SHP-{6000 + index}", order_id, "Express Logistics",
                                      f"NS{700000 + index}", shipment_status,
                                      order_date if shipment_status != "label_created" else None,
                                      "2026-11-25" if shipment_status not in {"delivered", "returned"} else None,
                                      "2026-10-05" if shipment_status == "delivered" else None))

            connection.executemany(
                "INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?)", payment_rows
            )
            connection.executemany(
                "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", shipment_rows
            )

            payment_ids = {row[1]: row[0] for row in payment_rows}
            refund_rows = [
                ("REF-8001", "ORD-1003", payment_ids["ORD-1003"], "processed", 500.00,
                 "Partial refund after return inspection", "2026-10-20T10:00:00Z", "2026-10-24T10:00:00Z"),
                ("REF-8002", "ORD-1005", payment_ids["ORD-1005"], "processed", order_totals["ORD-1005"],
                 "Order cancelled", "2026-11-12T12:00:00Z", "2026-11-13T09:00:00Z"),
                ("REF-8003", "ORD-1008", payment_ids["ORD-1008"], "under_review", 1000.00,
                 "Customer reported a defective item", "2026-10-30T11:00:00Z", None),
                ("REF-8004", "ORD-1013", payment_ids["ORD-1013"], "requested", 1000.00,
                 "Customer requested a return", "2026-11-14T09:00:00Z", None),
            ]
            connection.executemany(
                "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?, ?)", refund_rows
            )
            connection.executemany(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)", CONVERSATIONS
            )
            message_rows = [(None, *row) for row in MESSAGES]
            connection.executemany(
                "INSERT INTO messages (message_id, conversation_id, sender, message_text, created_at) VALUES (?, ?, ?, ?, ?)",
                message_rows,
            )
            connection.executemany(
                "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", TICKETS
            )

            event_rows = [
                (1, "TKT-3001", "created", "Customer asked for shipment status.", "system", "2026-11-10T12:25:00Z"),
                (2, "TKT-3002", "created", "Partial refund query received.", "system", "2026-10-20T10:10:00Z"),
                (3, "TKT-3002", "assigned", "Assigned to Payments team.", "admin-demo", "2026-10-21T09:00:00Z"),
                (4, "TKT-3003", "resolved", "Refund recorded as processed.", "admin-demo", "2026-11-13T09:00:00Z"),
                (5, "TKT-3005", "escalated", "Shipment delay requires human review.", "system", "2026-11-18T10:15:00Z"),
                (6, "TKT-3006", "created", "Customer asked about refund status.", "system", "2026-10-30T11:20:00Z"),
                (7, "TKT-3008", "escalated", "Payment is pending verification.", "system", "2026-11-21T12:15:00Z"),
            ]
            connection.executemany(
                "INSERT INTO ticket_events VALUES (?, ?, ?, ?, ?, ?)", event_rows
            )

        print(f"[SUCCESS] Demo database created: {DB_PATH}")
        print(f"[INFO] Customers: {len(CUSTOMERS)} | Products: {len(PRODUCTS)} | Orders: {len(ORDERS)}")
        for table in ("customers", "products", "orders", "order_items", "payments", "shipments",
                      "refunds", "conversations", "messages", "tickets", "ticket_events"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"[INFO] {table}: {count}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
