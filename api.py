"""Small authenticated FastAPI surface for customer support.

Demo authentication uses customer IDs; replace it with OTP/password verification
before exposing this API publicly. Issued bearer tokens are opaque, random,
stored hashed, and scoped to one support conversation.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from config.settings import MAX_QUERY_LENGTH
from database.db import (
    DB_PATH, check_db, get_recent_customer_orders, start_db, stop_db, validate_login,
)
from app.ticket_service import (
    append_message, close_conversation, create_conversation, get_active_conversation,
    get_conversation, initialize_support_schema,
)
from app.support_pipeline import _handle_customer_turn, startup

TOKEN_TTL_SECONDS = int(os.getenv("API_SESSION_TTL_SECONDS", "900"))
bearer = HTTPBearer(auto_error=False)
_runtime: dict[str, Any] = {"ready": False, "error": None, "started_at": None}
_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _api_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _init_api_sessions() -> None:
    conn = _api_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_sessions (
                token_hash TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_sessions_conversation ON api_sessions(conversation_id)")
    finally:
        conn.close()


def _issue_token(conversation_id: str, customer_id: int) -> str:
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = _api_connection()
    try:
        conn.execute(
            """INSERT INTO api_sessions
               (token_hash, conversation_id, customer_id, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest, conversation_id, customer_id,
             datetime.now(timezone.utc).isoformat(), int(time.time()) + TOKEN_TTL_SECONDS),
        )
    finally:
        conn.close()
    return token


def _authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer session token required.")
    digest = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    conn = _api_connection()
    try:
        row = conn.execute(
            """SELECT conversation_id, customer_id, expires_at, revoked
               FROM api_sessions WHERE token_hash = ?""", (digest,)
        ).fetchone()
    finally:
        conn.close()
    if not row or row["revoked"] or row["expires_at"] < int(time.time()):
        raise HTTPException(status_code=401, detail="Session token is invalid or expired.")
    # Sliding expiry: active customers keep the session alive; idle tokens expire.
    conn = _api_connection()
    try:
        conn.execute(
            "UPDATE api_sessions SET expires_at = ? WHERE token_hash = ?",
            (int(time.time()) + TOKEN_TTL_SECONDS, digest),
        )
    finally:
        conn.close()
    conversation = get_conversation(row["conversation_id"], row["customer_id"])
    if not conversation or conversation["status"] in {"closed", "resolved"}:
        raise HTTPException(status_code=401, detail="Support session is no longer active.")
    return {
        "customer_id": row["customer_id"],
        "conversation_id": row["conversation_id"],
        "conversation": conversation,
    }



def _customer_safe_messages(conversation: dict) -> list[dict]:
    """Expose conversation text only; internal ML/LLM/security metadata is staff-only."""
    safe = []
    for item in conversation.get("conversation", []):
        safe.append({
            "role": item.get("role"),
            "message": item.get("message", ""),
            "timestamp": item.get("timestamp"),
        })
    return safe


def _revoke_token(credentials: HTTPAuthorizationCredentials | None) -> None:
    if not credentials:
        return
    digest = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    conn = _api_connection()
    try:
        conn.execute("UPDATE api_sessions SET revoked = 1 WHERE token_hash = ?", (digest,))
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_support_schema()
    _init_api_sessions()
    init_portal_tables()
    try:
        db_health = check_db()
        if not db_health.get("ok"):
            raise RuntimeError("Customer database is not reachable.")
        # Loads ML + LLM client + embedding/reranker + Chroma once per process.
        startup()
        _runtime.update(ready=True, error=None, started_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        _runtime.update(ready=False, error=type(exc).__name__)
        # Keep the process alive so /health can explain readiness failure.
    yield
    _runtime["ready"] = False


app = FastAPI(
    title="Customer Support API",
    version="1.0.0",
    description="Small customer-facing API for the existing support lifecycle.",
    lifespan=lifespan,
)

origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


class StartSessionRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=10)
    order_id: str | None = Field(default=None, max_length=64)

    @field_validator("customer_id")
    @classmethod
    def valid_customer_id(cls, value):
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Customer ID must contain digits only.")
        return value

    @field_validator("order_id")
    @classmethod
    def valid_order_id(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip().upper()
        if not __import__("re").fullmatch(r"ORD-[A-Z0-9-]{1,55}", value):
            raise ValueError("Enter a valid order ID.")
        return value


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value):
        value = value.strip()
        if not value or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
            raise ValueError("Message is empty or contains invalid control characters.")
        return value


@app.get("/health")
def health():
    db = check_db()
    return {
        "status": "ready" if _runtime["ready"] and db.get("ok") else "not_ready",
        "models_loaded": _runtime["ready"],
        "database": db.get("ok", False),
        "startup_error": _runtime["error"],
    }


@app.post("/api/session")
def start_support_session(payload: StartSessionRequest, request: Request):
    """Customer Care button calls this once to create/resume a support session."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _login_lock:
        recent = [stamp for stamp in _login_attempts.get(client_ip, []) if now - stamp < 300]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again in five minutes.")
        recent.append(now)
        _login_attempts[client_ip] = recent
    if not _runtime["ready"]:
        raise HTTPException(status_code=503, detail="Support service is still starting.")
    conn = start_db()
    try:
        login = validate_login(payload.customer_id, payload.order_id or "", conn)
        if not login.get("ok"):
            raise HTTPException(status_code=401, detail=login["message"])
        customer_id = login["customer_id"]
        existing = get_active_conversation(customer_id, login.get('order_id'))
        if existing and existing["status"] == "under_review":
            raise HTTPException(
                status_code=409,
                detail={"message": "An active support ticket is already being reviewed.",
                        "ticket_number": existing["ticket_number"]},
            )
        if existing:
            conversation = existing
        else:
            created = create_conversation(customer_id, login.get("order_id"))
            if not created.get("ok"):
                existing = get_active_conversation(customer_id, login.get('order_id'))
                if not existing or existing["status"] == "under_review":
                    raise HTTPException(status_code=409, detail="Could not create a support session.")
                conversation = existing
            else:
                conversation = get_conversation(created["conversation_id"], customer_id)
        if login.get("order_id") and conversation.get("order_id") != login["order_id"]:
            from app.ticket_service import select_order
            selected = select_order(conversation["conversation_id"], customer_id, login["order_id"])
            if not selected.get("ok"):
                raise HTTPException(status_code=400, detail=selected.get("error"))
            conversation = get_conversation(conversation["conversation_id"], customer_id)
        token = _issue_token(conversation["conversation_id"], customer_id)
        orders = get_recent_customer_orders(customer_id, 5, conn)
        return {
            "session_id": conversation["conversation_id"],
            "ticket_number": conversation["ticket_number"],
            "session_token": token,
            "token_type": "Bearer",
            "expires_in": TOKEN_TTL_SECONDS,
            "customer": login["customer"],
            "selected_order_id": conversation.get("order_id"),
            "recent_orders": [
                {"order_id": o.get("order_id"), "order_status": o.get("order_status"),
                 "items": o.get("items", [])}
                for o in orders
            ],
            "conversation_status": conversation["status"],
            "message": "Customer support session is ready.",
        }
    finally:
        stop_db(conn)


@app.post("/api/chat")
def chat(payload: ChatRequest, auth: dict = Depends(_authenticate),
         credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    conn = start_db()
    try:
        conversation = get_conversation(auth["conversation_id"], auth["customer_id"])
        response, ended = _handle_customer_turn(
            payload.message,
            {"customer_id": auth["customer_id"]},
            conversation,
            conn,
        )
        latest = get_conversation(auth["conversation_id"], auth["customer_id"])
        if ended or (latest and latest["status"] in {"closed", "resolved"}):
            _revoke_token(credentials)
        return {
            "session_id": auth["conversation_id"],
            "response": {
                "status": response.get("status"),
                "message": response.get("message"),
                "citations": response.get("citations", []),
            } if isinstance(response, dict) else response,
            "conversation_status": latest.get("status") if latest else "closed",
            "ticket_number": latest.get("ticket_number") if latest else None,
        }
    finally:
        stop_db(conn)


@app.get("/api/session/{session_id}")
def session_details(session_id: str, auth: dict = Depends(_authenticate)):
    if session_id != auth["conversation_id"]:
        raise HTTPException(status_code=404, detail="Session not found.")
    conversation = get_conversation(session_id, auth["customer_id"])
    if not conversation:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {
        "session_id": session_id,
        "ticket_number": conversation["ticket_number"],
        "status": conversation["status"],
        "ticket_type": conversation["ticket_type"],
        "selected_order_id": conversation["order_id"],
        "messages": _customer_safe_messages(conversation),
    }


@app.get("/api/tickets/{ticket_id}")
def ticket_details(ticket_id: str, auth: dict = Depends(_authenticate)):
    conn = _api_connection()
    try:
        row = conn.execute(
            """SELECT ticket_id, category, priority, ticket_status, assigned_team,
                      subject, created_at, updated_at
               FROM tickets WHERE ticket_id = ? AND customer_id = ?""",
            (ticket_id, auth["customer_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ticket not found.")
        return dict(row)
    finally:
        conn.close()



@app.post("/api/resolve")
def resolve_support(auth: dict = Depends(_authenticate),
                    credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    result = close_conversation(auth["conversation_id"], "customer_confirmed",
                                "Customer confirmed the issue was resolved.", resolved=True)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "Unable to resolve this case."))
    _revoke_token(credentials)
    return {"ok": True, "status": "resolved"}

# Portal tables and role-aware customer/staff API.
from app.portal_routes import router as portal_router, init_portal_tables
app.include_router(portal_router)

# Serve the compiled React application from the same FastAPI origin.
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'frontend')
_FRONTEND_DIST = os.path.join(_FRONTEND_DIR, 'dist')
if os.path.isdir(os.path.join(_FRONTEND_DIST, 'assets')):
    app.mount('/assets', StaticFiles(directory=os.path.join(_FRONTEND_DIST, 'assets')), name='assets')

    @app.get('/', include_in_schema=False)
    def frontend_home():
        return FileResponse(os.path.join(_FRONTEND_DIST, 'index.html'))
else:
    @app.get('/', include_in_schema=False)
    def frontend_build_missing():
        return {
            'message': 'React frontend has not been built yet.',
            'instructions': 'Run: cd frontend && npm install && npm run build',
        }
