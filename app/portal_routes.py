"""Portal endpoints for customer, admin and supervisor workspaces."""
from __future__ import annotations
import hashlib, secrets, time, sqlite3, json, os, re, threading
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from api import _api_connection, bearer, _issue_token
from database.db import start_db, stop_db, validate_login, get_recent_customer_orders
from app.ticket_service import (get_conversation, get_active_conversation, create_conversation,
    select_order, append_message, close_conversation, update_state)

router=APIRouter(prefix='/api')

class LoginBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)

    @field_validator("user_id")
    @classmethod
    def clean_user_id(cls, value):
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Enter a numeric demo ID.")
        return value


class SelectOrderBody(BaseModel):
    # An order is optional: customers must still be able to contact support
    # when they have no recent order or their issue is account-level.
    order_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("order_id")
    @classmethod
    def clean_order_id(cls, value):
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"ORD-[A-Z0-9-]{1,55}", value):
            raise ValueError("Enter a valid order ID.")
        return value


class ReplyBody(BaseModel):
    message: str = Field(min_length=1, max_length=5000)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value):
        value = value.strip()
        if not value or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
            raise ValueError("Message is empty or contains invalid control characters.")
        return value


class UpdateBody(BaseModel):
    status: str | None = None
    priority: str | None = None
    assigned_team: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    intervention_required: bool | None = None
    resolution_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value is not None and value not in {"open", "awaiting_customer", "under_review", "resolved", "closed"}:
            raise ValueError("Invalid case status.")
        return value

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, value):
        if value is not None and value not in {"low", "medium", "high", "urgent"}:
            raise ValueError("Invalid priority.")
        return value

    @field_validator("assigned_team", "category", "resolution_notes")
    @classmethod
    def clean_text_fields(cls, value):
        if value is None:
            return value
        value = value.strip()
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
            raise ValueError("Invalid control characters.")
        return value


_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _check_portal_login_rate(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    with _login_lock:
        recent = [stamp for stamp in _login_attempts.get(ip, []) if now - stamp < 300]
        if len(recent) >= 10:
            raise HTTPException(429, "Too many login attempts. Try again in five minutes.")
        recent.append(now)
        _login_attempts[ip] = recent


def init_portal_tables():
    c = _api_connection()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS portal_users(
            user_id TEXT PRIMARY KEY,
            role TEXT NOT NULL CHECK(role IN ('admin','supervisor')),
            display_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS portal_sessions(
            token_hash TEXT PRIMARY KEY, user_type TEXT NOT NULL, customer_id INTEGER,
            staff_id TEXT, role TEXT, created_at TEXT NOT NULL, expires_at INTEGER NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        );
        """)
        portal_columns = {row['name'] for row in c.execute('PRAGMA table_info(portal_sessions)')}
        if 'revoked' not in portal_columns:
            c.execute('ALTER TABLE portal_sessions ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0')
        refund_columns = {row['name'] for row in c.execute('PRAGMA table_info(refunds)')}
        if 'idempotency_key' not in refund_columns:
            c.execute('ALTER TABLE refunds ADD COLUMN idempotency_key TEXT')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_refunds_idempotency ON refunds(idempotency_key) WHERE idempotency_key IS NOT NULL')
        c.execute("INSERT OR IGNORE INTO portal_users(user_id,role,display_name) VALUES('900001','admin','Platform Admin')")
        c.execute("INSERT OR IGNORE INTO portal_users(user_id,role,display_name) VALUES('900002','supervisor','Support Supervisor')")
    finally:
        c.close()


def issue_portal_token(user_type, customer_id=None, staff_id=None, role=None):
    token = secrets.token_urlsafe(40)
    c = _api_connection()
    try:
        c.execute("""INSERT INTO portal_sessions
            (token_hash,user_type,customer_id,staff_id,role,created_at,expires_at,revoked)
            VALUES(?,?,?,?,?,?,?,0)""",
            (hashlib.sha256(token.encode()).hexdigest(), user_type, customer_id, staff_id,
             role, datetime.now(timezone.utc).isoformat(), int(time.time()) + 28800))
    finally:
        c.close()
    return token


def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Please sign in again.')
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    c = _api_connection()
    try:
        row = c.execute('SELECT * FROM portal_sessions WHERE token_hash=?', (digest,)).fetchone()
        if not row or row['revoked'] or row['expires_at'] < int(time.time()):
            raise HTTPException(401, 'Session expired. Please sign in again.')
        session = dict(row)
        if session['user_type'] == 'staff':
            user = c.execute('SELECT role,active FROM portal_users WHERE user_id=?', (session['staff_id'],)).fetchone()
            if not user or not user['active'] or user['role'] != session['role']:
                raise HTTPException(401, 'Staff account is inactive. Please sign in again.')
        c.execute('UPDATE portal_sessions SET expires_at=? WHERE token_hash=?', (int(time.time()) + 28800, digest))
        return session
    finally:
        c.close()


def customer(a=Depends(auth)):
    if a['user_type'] != 'customer':
        raise HTTPException(403, 'Customer access required.')
    return a


def staff(a=Depends(auth)):
    if a['user_type'] != 'staff' or a.get('role') not in {'admin', 'supervisor'}:
        raise HTTPException(403, 'Staff access required.')
    return a


@router.post('/login')
def login(body: LoginBody, request: Request):
    _check_portal_login_rate(request)
    uid = body.user_id
    c = _api_connection()
    try:
        u = c.execute('SELECT * FROM portal_users WHERE user_id=? AND active=1', (uid,)).fetchone()
    finally:
        c.close()
    if u:
        return {'token': issue_portal_token('staff', staff_id=uid, role=u['role']),
                'user_type': 'staff', 'role': u['role'], 'display_name': u['display_name']}
    db = start_db()
    try:
        result = validate_login(uid, '', db)
    finally:
        stop_db(db)
    if not result.get('ok'):
        raise HTTPException(401, 'ID not recognised. Please try again.')
    return {'token': issue_portal_token('customer', customer_id=result['customer_id']),
            'user_type': 'customer', 'role': 'customer',
            'display_name': f"{result['customer']['first_name']} {result['customer']['last_name']}".strip(),
            'customer': result['customer']}


@router.post('/logout')
def logout(a=Depends(auth)):
    c = _api_connection()
    try:
        c.execute('UPDATE portal_sessions SET revoked=1 WHERE token_hash=?', (a['token_hash'],))
        if a['user_type'] == 'customer':
            c.execute('UPDATE api_sessions SET revoked=1 WHERE customer_id=?', (a['customer_id'],))
    finally:
        c.close()
    return {'ok': True}


def _customer_safe_messages(conversation: dict) -> list[dict]:
    """Do not expose staff-only ML, LLM, security or intervention diagnostics."""
    return [
        {"role": item.get("role"), "message": item.get("message", ""),
         "timestamp": item.get("timestamp")}
        for item in conversation.get("conversation", [])
    ]


@router.get('/customer/tickets')
def customer_tickets(a=Depends(customer)):
    c=_api_connection()
    try:
        rows=c.execute('SELECT sc.conversation_id,sc.ticket_number,sc.ticket_type,sc.status,sc.order_id,sc.created_at,sc.last_activity_at,sc.human_intervention_required,COALESCE(t.category,sc.category) AS category,COALESCE(t.priority,sc.priority) AS priority,t.subject FROM support_conversations sc LEFT JOIN tickets t ON t.ticket_id=sc.official_ticket_id WHERE sc.customer_id=? ORDER BY sc.last_activity_at DESC',(a['customer_id'],)).fetchall()
        return {'tickets':[dict(x) for x in rows]}
    finally:c.close()

@router.get('/customer/orders')
def customer_orders(a=Depends(customer)):
    c=start_db()
    try:return {'orders':[{'order_id':o.get('order_id'),'order_date':o.get('order_date'),'order_status':o.get('order_status'),'total_amount':o.get('total_amount'),'currency':o.get('currency'),'items':o.get('items',[])} for o in get_recent_customer_orders(a['customer_id'],5,c)]}
    finally:stop_db(c)

@router.post('/customer/contact')
def contact(body:SelectOrderBody,a=Depends(customer)):
    db=start_db()
    try:
        # Only validate order ownership when an order was actually selected.
        if body.order_id:
            valid=validate_login(str(a['customer_id']),body.order_id,db)
            if not valid.get('ok'):raise HTTPException(400,valid['message'])
        if body.order_id:
            existing=get_active_conversation(a['customer_id'],body.order_id)
        else:
            c=_api_connection()
            try:
                row=c.execute("SELECT conversation_id FROM support_conversations WHERE customer_id=? AND order_id IS NULL AND status IN ('open','awaiting_customer','under_review') ORDER BY created_at DESC LIMIT 1",(a['customer_id'],)).fetchone()
            finally:c.close()
            existing=get_conversation(row['conversation_id'],a['customer_id']) if row else None
        if existing and existing['status']=='under_review':
            return {'already_under_review':True,'session_id':existing['conversation_id'],
                    'ticket_number':existing['ticket_number'],
                    'session_token':_issue_token(existing['conversation_id'],a['customer_id']),
                    'selected_order_id':existing.get('order_id'),
                    'messages':_customer_safe_messages(existing),
                    'conversation_status':existing['status']}
        if existing: conv=existing
        else:
            made=create_conversation(a['customer_id'],body.order_id)
            if made.get('ok'):
                conv=get_conversation(made['conversation_id'],a['customer_id'])
            elif body.order_id:
                conv=get_active_conversation(a['customer_id'],body.order_id)
            else:
                c=_api_connection()
                try:
                    row=c.execute("SELECT conversation_id FROM support_conversations WHERE customer_id=? AND order_id IS NULL AND status IN ('open','awaiting_customer','under_review') ORDER BY created_at DESC LIMIT 1",(a['customer_id'],)).fetchone()
                finally:c.close()
                conv=get_conversation(row['conversation_id'],a['customer_id']) if row else None
            if not conv:raise HTTPException(409,'Could not start a support conversation.')
        if body.order_id and conv.get('order_id')!=body.order_id:
            selected=select_order(conv['conversation_id'],a['customer_id'],body.order_id)
            if not selected.get('ok'):raise HTTPException(400,selected.get('error'))
            conv=get_conversation(conv['conversation_id'],a['customer_id'])
        return {'session_id':conv['conversation_id'],'ticket_number':conv['ticket_number'],'session_token':_issue_token(conv['conversation_id'],a['customer_id']),'selected_order_id':body.order_id,'messages':_customer_safe_messages(conv)}
    finally:stop_db(db)

@router.get('/customer/conversations/{cid}')
def customer_conversation(cid:str,a=Depends(customer)):
    conv=get_conversation(cid,a['customer_id'])
    if not conv:raise HTTPException(404,'Ticket not found.')
    return {'session_id':cid,'ticket_number':conv['ticket_number'],'status':conv['status'],'ticket_type':conv['ticket_type'],'messages':_customer_safe_messages(conv)}

@router.get('/staff/tickets')
def staff_tickets(status:str|None=None,ticket_type:str|None=None,priority:str|None=None,assigned_team:str|None=None,category:str|None=None,intervention:bool|None=None,search:str|None=None,a=Depends(staff)):
    sql='SELECT sc.conversation_id,sc.ticket_number,sc.customer_id,c.first_name,c.last_name,sc.order_id,sc.ticket_type,sc.status,sc.created_at,sc.last_activity_at,sc.human_intervention_required,COALESCE(t.category,sc.category) AS category,COALESCE(t.priority,sc.priority) AS priority,COALESCE(t.assigned_team,sc.assigned_team) AS assigned_team,t.subject FROM support_conversations sc JOIN customers c ON c.customer_id=sc.customer_id LEFT JOIN tickets t ON t.ticket_id=sc.official_ticket_id WHERE 1=1'; p=[]
    for col,val in [('sc.status',status),('sc.ticket_type',ticket_type),('COALESCE(t.priority,sc.priority)',priority)]:
        if val:sql+=f' AND {col}=?';p.append(val)
    if assigned_team:sql+=' AND COALESCE(t.assigned_team,sc.assigned_team)=?';p.append(assigned_team)
    if category:sql+=' AND COALESCE(t.category,sc.category)=?';p.append(category)
    if intervention is not None:sql+=' AND sc.human_intervention_required=?';p.append(int(intervention))
    if search:
        sql+=' AND (sc.ticket_number LIKE ? OR CAST(sc.customer_id AS TEXT) LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ?)';p += [f'%{search}%']*4
    sql+=' ORDER BY sc.human_intervention_required DESC,sc.last_activity_at DESC LIMIT 500';c=_api_connection()
    try:
        rows=[dict(x) for x in c.execute(sql,p).fetchall()]; counts={x['status']:x['n'] for x in c.execute('SELECT status,COUNT(*) n FROM support_conversations GROUP BY status')}
        return {'tickets':rows,'counts':counts,'role':a['role']}
    finally:c.close()

@router.get('/staff/tickets/{cid}')
def staff_detail(cid:str,a=Depends(staff)):
    conv=get_conversation(cid)
    if not conv:raise HTTPException(404,'Ticket not found.')
    c=_api_connection()
    try:
        cust=c.execute('SELECT customer_id,first_name,last_name,email,phone,account_status FROM customers WHERE customer_id=?',(conv['customer_id'],)).fetchone(); official=None;events=[];order=None
        if conv.get('official_ticket_id'):
            official=c.execute('SELECT * FROM tickets WHERE ticket_id=?',(conv['official_ticket_id'],)).fetchone();events=[dict(x) for x in c.execute('SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY created_at',(conv['official_ticket_id'],)).fetchall()]
        if conv.get('order_id'):order=c.execute('SELECT * FROM orders WHERE order_id=? AND customer_id=?',(conv['order_id'],conv['customer_id'])).fetchone()
        return {'conversation':conv,'customer':dict(cust) if cust else None,'official_ticket':dict(official) if official else None,'events':events,'order':dict(order) if order else None,'technical':{'version':conv.get('version'),'state':conv.get('state'),'intervention_required':conv.get('human_intervention_required')}}
    finally:c.close()

@router.post('/staff/tickets/{cid}/reply')
def staff_reply(cid:str,body:ReplyBody,a=Depends(staff)):
    conv=get_conversation(cid)
    if not conv:raise HTTPException(404,'Ticket not found.')
    result=append_message(cid,'agent',body.message,{'staff_id':a['staff_id'],'role':a['role']})
    if not result.get('ok'):raise HTTPException(409,result.get('error','Unable to reply.'))
    c=_api_connection()
    try:
        if conv.get('official_ticket_id'):
            now=datetime.now(timezone.utc).isoformat();c.execute('UPDATE tickets SET updated_at=? WHERE ticket_id=?',(now,conv['official_ticket_id']))
            c.execute('INSERT INTO ticket_events(ticket_id,event_type,event_description,actor,created_at) VALUES(?,?,?,?,?)',(conv['official_ticket_id'],'staff_reply',body.message[:1000],a['staff_id'],now))
    finally:c.close()
    return {'ok':True}

@router.patch('/staff/tickets/{cid}')
def staff_update(cid:str,body:UpdateBody,a=Depends(staff)):
    conv=get_conversation(cid)
    if not conv:raise HTTPException(404,'Ticket not found.')
    if a['role']=='admin' and any(v is not None for v in [body.priority, body.assigned_team, body.category]):
        raise HTTPException(403, 'Only supervisors can change priority, category or assigned team.')
    if a['role']=='admin' and body.status not in {None, 'closed'}:
        raise HTTPException(403, 'Admins can close cases; only supervisors can change status or reopen cases.')
    if body.status and body.status not in {'open','awaiting_customer','under_review','resolved','closed'}:raise HTTPException(400,'Invalid status.')
    now=datetime.now(timezone.utc).isoformat()
    if body.status in {'closed','resolved'}:
        r=close_conversation(cid,'staff_action',body.resolution_notes,resolved=body.status=='resolved')
        if not r.get('ok'):raise HTTPException(409,r.get('error','Unable to close ticket.'))
    else:
        if body.status:
            if conv['status'] in {'closed','resolved'} and a['role']=='supervisor' and body.status in {'open','awaiting_customer','under_review'}:
                c=_api_connection()
                try:
                    c.execute('UPDATE support_conversations SET status=?,closed_at=NULL,closure_reason=NULL,last_activity_at=?,version=version+1 WHERE conversation_id=?',(body.status,now,cid))
                finally:c.close()
            else:
                r=update_state(cid,conv.get('state',{}),body.status)
                if not r.get('ok'):raise HTTPException(409,r.get('error','Unable to update ticket.'))
        if body.intervention_required is not None:
            c=_api_connection()
            try:c.execute('UPDATE support_conversations SET human_intervention_required=?,last_activity_at=?,version=version+1 WHERE conversation_id=?',(int(body.intervention_required),now,cid))
            finally:c.close()
    # Supervisor-only triage fields apply to temporary conversations too.
    if a['role']=='supervisor' and any(v is not None for v in [body.priority,body.assigned_team,body.category]):
        c=_api_connection()
        try:
            for column,value in [('priority',body.priority),('assigned_team',body.assigned_team),('category',body.category)]:
                if value is not None:
                    c.execute(f'UPDATE support_conversations SET {column}=?,version=version+1 WHERE conversation_id=?',(value,cid))
            if conv.get('official_ticket_id'):
                fields=[];vals=[]
                for column,value in [('priority',body.priority),('assigned_team',body.assigned_team),('category',body.category)]:
                    if value is not None:fields.append(column+'=?');vals.append(value)
                if fields:
                    fields.append('updated_at=?');vals.extend([now,conv['official_ticket_id']])
                    c.execute('UPDATE tickets SET '+','.join(fields)+' WHERE ticket_id=?',vals)
        finally:c.close()
    # Keep the legacy official-ticket status in sync with the support conversation.
    latest=get_conversation(cid)
    if latest and latest.get('official_ticket_id'):
        mapped={'open':'open','awaiting_customer':'in_progress','under_review':'pending_human_review','resolved':'resolved','closed':'closed'}
        c=_api_connection()
        try:
            c.execute('UPDATE tickets SET ticket_status=?,updated_at=? WHERE ticket_id=?',(mapped.get(latest['status'],'open'),now,latest['official_ticket_id']))
            if body.status:
                c.execute('INSERT INTO ticket_events(ticket_id,event_type,event_description,actor,created_at) VALUES(?,?,?,?,?)',(latest['official_ticket_id'],'status_changed',f"Status changed to {latest['status']}",a['staff_id'],now))
            if body.resolution_notes:
                c.execute('INSERT INTO ticket_events(ticket_id,event_type,event_description,actor,created_at) VALUES(?,?,?,?,?)',(latest['official_ticket_id'],'resolution_note',body.resolution_notes[:1000],a['staff_id'],now))
        finally:c.close()
    return {'ok':True}