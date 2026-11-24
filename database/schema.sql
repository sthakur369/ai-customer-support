-- Customer-support demo database.
-- All timestamps are stored as ISO-8601 UTC strings.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    customer_id     INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    created_at      TEXT NOT NULL,
    account_status  TEXT NOT NULL DEFAULT 'active'
                    CHECK (account_status IN ('active', 'suspended', 'closed'))
);

CREATE TABLE IF NOT EXISTS addresses (
    address_id      INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    address_type    TEXT NOT NULL CHECK (address_type IN ('billing', 'shipping')),
    line1           TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    postal_code     TEXT NOT NULL,
    country         TEXT NOT NULL DEFAULT 'India',
    is_default      INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
);

CREATE TABLE IF NOT EXISTS products (
    product_id      INTEGER PRIMARY KEY,
    sku             TEXT NOT NULL UNIQUE,
    product_name    TEXT NOT NULL,
    category        TEXT NOT NULL,
    unit_price      REAL NOT NULL CHECK (unit_price >= 0),
    is_returnable   INTEGER NOT NULL DEFAULT 1 CHECK (is_returnable IN (0, 1))
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         INTEGER NOT NULL REFERENCES customers(customer_id),
    shipping_address_id INTEGER REFERENCES addresses(address_id),
    order_date          TEXT NOT NULL,
    order_status        TEXT NOT NULL CHECK (order_status IN
                         ('placed', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled')),
    total_amount        REAL NOT NULL CHECK (total_amount >= 0),
    currency            TEXT NOT NULL DEFAULT 'INR'
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id   INTEGER PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      REAL NOT NULL CHECK (unit_price >= 0),
    line_total      REAL NOT NULL CHECK (line_total >= 0)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    payment_method  TEXT NOT NULL,
    payment_status  TEXT NOT NULL CHECK (payment_status IN
                     ('pending', 'paid', 'failed', 'partially_refunded', 'refunded')),
    amount          REAL NOT NULL CHECK (amount >= 0),
    transaction_ref TEXT,
    paid_at         TEXT
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id     TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    carrier         TEXT NOT NULL,
    tracking_number TEXT NOT NULL UNIQUE,
    shipment_status TEXT NOT NULL CHECK (shipment_status IN
                     ('label_created', 'in_transit', 'out_for_delivery', 'delivered', 'delayed', 'returned')),
    shipped_at      TEXT,
    estimated_delivery TEXT,
    delivered_at    TEXT
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id       TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES orders(order_id),
    payment_id      TEXT NOT NULL REFERENCES payments(payment_id),
    refund_status   TEXT NOT NULL CHECK (refund_status IN
                     ('requested', 'under_review', 'approved', 'processed', 'rejected')),
    amount          REAL NOT NULL CHECK (amount >= 0),
    reason          TEXT NOT NULL,
    requested_at    TEXT NOT NULL,
    processed_at    TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    subject         TEXT,
    conversation_status TEXT NOT NULL DEFAULT 'open'
                        CHECK (conversation_status IN ('open', 'closed', 'archived')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    sender          TEXT NOT NULL CHECK (sender IN ('customer', 'assistant', 'admin', 'system')),
    message_text    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id       TEXT PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    conversation_id TEXT REFERENCES conversations(conversation_id),
    order_id        TEXT REFERENCES orders(order_id),
    category        TEXT NOT NULL,
    priority        TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    ticket_status   TEXT NOT NULL CHECK (ticket_status IN
                     ('open', 'pending_human_review', 'in_progress', 'resolved', 'closed')),
    assigned_team   TEXT,
    subject         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    support_conversation_id TEXT REFERENCES support_conversations(conversation_id)
);

CREATE TABLE IF NOT EXISTS ticket_events (
    event_id        INTEGER PRIMARY KEY,
    ticket_id       TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    event_description TEXT NOT NULL,
    actor           TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- One JSON conversation row per support ticket. Existing legacy conversations/messages
-- tables are retained for compatibility with earlier project functionality.
CREATE TABLE IF NOT EXISTS support_conversations (
    conversation_id TEXT PRIMARY KEY,
    ticket_number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_id TEXT,
    ticket_type TEXT NOT NULL DEFAULT 'temporary'
        CHECK (ticket_type IN ('temporary', 'official')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'awaiting_customer', 'under_review', 'resolved', 'closed')),
    conversation_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(conversation_json)),
    state_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(state_json)),
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

CREATE TABLE IF NOT EXISTS support_schema_meta (version INTEGER NOT NULL);

CREATE INDEX IF NOT EXISTS idx_addresses_customer ON addresses(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer_date ON orders(customer_id, order_date);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_order ON refunds(order_id);
CREATE INDEX IF NOT EXISTS idx_conversations_customer ON conversations(customer_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket ON ticket_events(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_support_conversation ON tickets(support_conversation_id);
CREATE INDEX IF NOT EXISTS idx_support_conversations_customer_status
    ON support_conversations(customer_id, status, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_support_conversations_inactive
    ON support_conversations(status, ticket_type, last_activity_at);
