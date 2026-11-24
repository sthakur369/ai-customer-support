import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownLeft, ArrowLeft, ArrowRight, ArrowUpRight, BadgeCheck, Bell, Check,
  CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Clock3, Command, FileText,
  Filter, Headphones, LifeBuoy, LogOut, MessageCircle, MoreHorizontal, Package,
  PanelRightClose, Search, Send, ShieldCheck, SlidersHorizontal, Sparkles,
  Tag, UserRound, X, AlertCircle, Activity, CalendarDays, Hash, Layers3
} from 'lucide-react';

const API = '';
const money = (v, currency='INR') => {
  if (v == null || v === '') return '—';
  try { return new Intl.NumberFormat('en-IN',{style:'currency',currency,maximumFractionDigits:0}).format(Number(v)); }
  catch { return `${currency} ${v}`; }
};
const date = (v) => v ? new Date(v).toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const pretty = (v='') => String(v).replaceAll('_',' ').replace(/\b\w/g, m=>m.toUpperCase());

async function request(path, {token, ...options}={}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {'Content-Type':'application/json', ...(token ? {Authorization:`Bearer ${token}`} : {}), ...(options.headers||{})}
  });
  const data = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || data.message || `Request failed (${response.status})`);
  return data;
}

function Brand({small=false}) { return <div className={`brand ${small?'brand-small':''}`}><span className="brand-mark"><span></span><span></span><span></span></span><span>customer support<span className="brand-dot">.</span></span></div>; }
function Button({children, kind='primary', size='', disabled=false, onClick, type='button'}) { return <button type={type} disabled={disabled} onClick={onClick} className={`btn btn-${kind} ${size}`}>{children}</button>; }
function Pill({children,tone='neutral'}) { return <span className={`pill pill-${tone}`}>{children}</span>; }
function Loading({label='Just a moment'}) { return <div className="loading-state"><span className="spinner"/><span>{label}</span></div>; }
function Empty({icon:Icon=FileText,title,body,action}) { return <div className="empty-state"><span className="empty-icon"><Icon size={22}/></span><h3>{title}</h3><p>{body}</p>{action}</div>; }
function ErrorNote({message,onClose}) { if(!message)return null; return <div className="error-note"><AlertCircle size={16}/><span>{message}</span>{onClose&&<button type="button" onClick={onClose}><X size={15}/></button>}</div>; }

export default function App(){
  const [identity,setIdentity]=useState(null);
  const [token,setToken]=useState('');
  const [screen,setScreen]=useState('login');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [toast,setToast]=useState('');
  const [customerTickets,setCustomerTickets]=useState([]);
  const [orders,setOrders]=useState([]);
  const [support,setSupport]=useState(null);
  const [staffTickets,setStaffTickets]=useState([]);
  const [counts,setCounts]=useState({});
  const [selectedTicket,setSelectedTicket]=useState(null);
  const [staffDetail,setStaffDetail]=useState(null);
  const [staffFilters,setStaffFilters]=useState({status:'',ticket_type:'',priority:'',assigned_team:'',category:'',intervention:'',search:''});
  const [staffTab,setStaffTab]=useState('all');
  const [detailTab,setDetailTab]=useState('conversation');

  const notify=(message)=>{setToast(message);window.setTimeout(()=>setToast(''),2800);};
  const logout=()=>{if(token)request('/api/logout',{token,method:'POST'}).catch(()=>{});setIdentity(null);setToken('');setSupport(null);setScreen('login');setError('');};

  async function login(userId){
    setBusy(true);setError('');
    try{
      const data=await request('/api/login',{method:'POST',body:JSON.stringify({user_id:userId.trim()})});
      setIdentity(data);setToken(data.token);
      if(data.user_type==='staff'){
        setScreen('staff');await loadStaff(data.token,staffFilters);
      }else{
        setScreen('customer');
        const [t,o]=await Promise.all([request('/api/customer/tickets',{token:data.token}),request('/api/customer/orders',{token:data.token})]);
        setCustomerTickets(t.tickets||[]);setOrders(o.orders||[]);
      }
    }catch(e){setError(e.message||'Unable to sign in. Check the ID and try again.');}
    finally{setBusy(false);}
  }

  async function loadStaff(auth=token,filters=staffFilters){
    setBusy(true);setError('');
    try{
      const q=new URLSearchParams();Object.entries(filters).forEach(([k,v])=>{if(v!=='')q.set(k,v)});
      const data=await request(`/api/staff/tickets?${q.toString()}`,{token:auth});
      setStaffTickets(data.tickets||[]);setCounts(data.counts||{});
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function openStaffTicket(ticket){
    setSelectedTicket(ticket);setStaffDetail(null);setDetailTab('conversation');
    try{const d=await request(`/api/staff/tickets/${ticket.conversation_id}`,{token});setStaffDetail(d);}
    catch(e){setError(e.message);}
  }
  async function refreshCustomer(){
    const [t,o]=await Promise.all([request('/api/customer/tickets',{token}),request('/api/customer/orders',{token})]);
    setCustomerTickets(t.tickets||[]);setOrders(o.orders||[]);
  }
  // Customer portal-token polling keeps staff replies visible without requiring
  // another customer message. This endpoint also works for closed conversations.
  useEffect(()=>{
    if(screen!=='chat'||!support?.session_id||!token)return;
    let active=true;
    const poll=async()=>{
      try{
        const d=await request(`/api/customer/conversations/${encodeURIComponent(support.session_id)}`,{token});
        if(!active)return;
        setSupport(current=>current?.session_id===support.session_id?({...current,
          messages:d.messages||[],status:d.status||current.status,
          read_only:current.read_only||['closed','resolved'].includes(d.status)
        }):current);
      }catch(e){
        // A transient polling failure must not interrupt the customer's chat.
      }
    };
    poll();
    const timer=window.setInterval(poll,3000);
    return()=>{active=false;window.clearInterval(timer);};
  },[screen,support?.session_id,token]);

  function clearStaffFilters(){
    const empty={status:'',ticket_type:'',priority:'',assigned_team:'',category:'',intervention:'',search:''};
    setStaffFilters(empty);
    loadStaff(token,empty);
  }
  async function beginContact(order=null){
    setBusy(true);setError('');
    try{
      const d=await request('/api/customer/contact',{token,method:'POST',body:JSON.stringify({order_id:order?.order_id?String(order.order_id):null})});
      if(d.already_under_review){notify(`Opening ticket ${d.ticket_number}.`);}
      setSupport({session_id:d.session_id,ticket_number:d.ticket_number,token:d.session_token,order_id:d.selected_order_id,messages:d.messages||[],status:d.conversation_status||'open',read_only:!!d.already_under_review});
      setScreen('chat');
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function resolveSupport(){
    if(!support)return;
    setBusy(true);setError('');
    try{
      await request('/api/resolve',{token:support.token,method:'POST'});
      setSupport(s=>({...s,status:'resolved',read_only:true,resolution_pending:false}));
      notify('Marked as resolved.');
      await refreshCustomer();
    }catch(e){setError(e.message);}
    finally{setBusy(false);}
  }
  async function sendMessage(message){
    if(!message.trim()||!support||support.read_only)return;
    const optimistic=[...(support.messages||[]),{role:'user',content:message,created_at:new Date().toISOString()}];
    setSupport(s=>({...s,resolution_pending:false}));
    setSupport(s=>({...s,messages:optimistic}));setBusy(true);setError('');
    try{
      const d=await request('/api/chat',{token:support.token,method:'POST',body:JSON.stringify({message})});
      if(['closed','resolved'].includes(d.conversation_status)){
        const payload=d.response;
        const reply=typeof payload==='string'?payload:(payload?.message||payload?.answer||'Your support conversation has been closed.');
        setSupport(s=>({...s,messages:[...s.messages,{role:'assistant',message:reply,timestamp:new Date().toISOString()}],status:d.conversation_status,ticket_number:d.ticket_number||s.ticket_number,resolution_pending:d.response?.status==='ANSWERED'}));
      }else{
        const detail=await request(`/api/session/${support.session_id}`,{token:support.token});
        setSupport(s=>({...s,messages:detail.messages||[],status:d.conversation_status,ticket_number:d.ticket_number||s.ticket_number,resolution_pending:d.response?.status==='ANSWERED'}));
      }
      if(['under_review','closed','resolved'].includes(d.conversation_status)){notify('Your message has been added to the support case.');}
    }catch(e){setError(e.message);setSupport(s=>({...s,messages:s.messages.slice(0,-1)}));}
    finally{setBusy(false);}
  }
  async function staffReply(message){
    if(!selectedTicket?.conversation_id||!message.trim())return false;
    setBusy(true);setError('');
    try{
      await request(`/api/staff/tickets/${selectedTicket.conversation_id}/reply`,{token,method:'POST',body:JSON.stringify({message:message.trim()})});
      const d=await request(`/api/staff/tickets/${selectedTicket.conversation_id}`,{token});
      setStaffDetail(d);await loadStaff();notify('Reply sent to customer.');return true;
    }catch(e){setError(e.message||'Could not send the reply. Please try again.');return false;}
    finally{setBusy(false);}
  }
  async function staffUpdate(patch){
    if(!selectedTicket?.conversation_id)return false;
    setBusy(true);setError('');
    try{
      await request(`/api/staff/tickets/${selectedTicket.conversation_id}`,{token,method:'PATCH',body:JSON.stringify(patch)});
      const d=await request(`/api/staff/tickets/${selectedTicket.conversation_id}`,{token});
      setStaffDetail(d);await loadStaff();notify('Ticket updated.');return true;
    }catch(e){setError(e.message||'Could not update this case. Please try again.');return false;}
    finally{setBusy(false);}
  }

  const filteredTickets=useMemo(()=>staffTickets.filter(t=>{
    if(staffTab==='intervention'&&!t.human_intervention_required)return false;
    if(staffTab==='official'&&t.ticket_type!=='official')return false;
    if(staffTab==='temporary'&&t.ticket_type!=='temporary')return false;
    return true;
  }),[staffTickets,staffTab]);

  if(screen==='login') return <Login onLogin={login} busy={busy} error={error}/>;
  if(identity?.user_type==='customer'&&screen==='customer') return <CustomerHome identity={identity} tickets={customerTickets} orders={orders} onContact={beginContact} onLogout={logout} busy={busy} error={error} onClearError={()=>setError('')}/>;
  if(identity?.user_type==='customer'&&screen==='chat') return <CustomerChat identity={identity} support={support} onSend={sendMessage} onResolve={resolveSupport} onBack={()=>{setScreen('customer');refreshCustomer();}} onLogout={logout} busy={busy} error={error}/>;
  if(identity?.user_type==='staff') return <StaffHome identity={identity} tickets={filteredTickets} allTickets={staffTickets} counts={counts} filters={staffFilters} setFilters={setStaffFilters} tab={staffTab} setTab={setStaffTab} detail={staffDetail} selected={selectedTicket} detailTab={detailTab} setDetailTab={setDetailTab} onOpen={openStaffTicket} onBack={()=>{setSelectedTicket(null);setStaffDetail(null);}} onLogout={logout} onRefresh={()=>loadStaff()} onClearFilters={clearStaffFilters} onReply={staffReply} onUpdate={staffUpdate} busy={busy} error={error} onClearError={()=>setError('')}/>;
  return null;
}

function Login({onLogin,busy,error}){
  const [userId,setUserId]=useState('');
  return <main className="login-shell">
    <header className="login-top"><Brand/><span className="top-note"></span></header>
    <section className="login-grid">
      <div className="login-copy">
        <div className="eyebrow">CUSTOMER SUPPORT</div>
        <h1>Customer support</h1>
        <p className="login-lede">Sign in to view your orders and support requests.</p>
      </div>
      <div className="login-card-wrap"><div className="login-card">
        <h2>Sign in</h2><p>Enter your customer or staff ID.</p>
        <form onSubmit={e=>{e.preventDefault();if(userId.trim())onLogin(userId);}}>
          <label htmlFor="user-id">Your ID</label><div className="input-wrap"><UserRound size={17}/><input id="user-id" value={userId} onChange={e=>setUserId(e.target.value)} placeholder="Enter your ID" autoComplete="username" inputMode="numeric" autoFocus/></div>
          <ErrorNote message={error}/><Button type="submit" disabled={!userId.trim()||busy} >{busy?<><span className="button-spinner"/> Checking ID</>:<>Continue <ArrowRight size={17}/></>}</Button>
        </form>
        <div className="demo-logins"><div><b>Demo access</b><small>Choose an ID to fill it in</small></div><div className="demo-login-row"><button type="button" onClick={()=>setUserId('1')}>Customer <b>1</b></button><button type="button" onClick={()=>setUserId('900001')}>Admin <b>900001</b></button><button type="button" onClick={()=>setUserId('900002')}>Supervisor <b>900002</b></button></div><small className="demo-warning">Demo IDs only — replace ID-only login before public deployment.</small></div>
        <div className="login-foot"><ShieldCheck size={15}/> Your workspace is scoped to your account.</div>
      </div><div className="help-line"><CircleHelp size={15}/> Having trouble signing in? <span>Contact support</span></div></div>
    </section>
    <footer className="login-footer"><span>© Customer Support</span><span></span></footer>
  </main>;
}

function AppHeader({identity,onLogout,staff=false}){return <header className="app-header"><Brand small/><div className="header-right">{staff&&<Pill tone="green">{pretty(identity.role)} workspace</Pill>}<div className="user-chip"><span className="avatar">{(identity.display_name||'N').slice(0,1).toUpperCase()}</span><span className="user-chip-name">{identity.display_name}</span></div><button type="button" className="icon-button" title="Sign out" onClick={onLogout}><LogOut size={17}/></button></div></header>;}

function CustomerHome({identity,tickets,orders,onContact,onLogout,busy,error,onClearError}){
  const [tab,setTab]=useState('tickets');const [order,setOrder]=useState(null);
  return <div className="app-shell"><AppHeader identity={identity} onLogout={onLogout}/><main className="customer-main">
    <div className="welcome-row"><div><div className="eyebrow">YOUR ACCOUNT</div><h1>Good to see you, {identity.display_name?.split(' ')[0]}.</h1><p>What can we help you take care of today?</p></div><div className="welcome-stamp"><span className="stamp-icon"><LifeBuoy size={21}/></span><span><b>We're here to help</b><small>Every step of the way</small></span></div></div>
    <ErrorNote message={error} onClose={onClearError}/>
    <div className="customer-tabs"><button type="button" className={tab==='tickets'?'active':''} onClick={()=>setTab('tickets')}><FileText size={16}/> My support requests <span>{tickets.length}</span></button><button type="button" className={tab==='contact'?'active':''} onClick={()=>{setTab('contact');setOrder(null);}}><Headphones size={16}/> Contact customer care</button></div>
    {tab==='tickets'?<section className="section-card"><div className="section-heading"><div><h2>Your support history</h2><p>Updates on current and previous conversations.</p></div><Pill>{tickets.length} {tickets.length===1?'request':'requests'}</Pill></div>
      {tickets.length?<div className="ticket-list">{tickets.map(t=><CustomerTicket key={t.conversation_id} ticket={t}/>)}</div>:<Empty icon={MessageCircle} title="Nothing here just yet" body="When you contact our team, your support requests and updates will appear here." action={<Button kind="outline" onClick={()=>setTab('contact')}>Contact customer care <ArrowRight size={16}/></Button>}/>}</section>
      :<section className="section-card order-section"><div className="section-heading"><div><div className="eyebrow">LET'S GET THIS SORTED</div><h2>What do you need help with?</h2><p>Choose one of your recent orders to start a conversation.</p></div><Pill tone="green">Step 1 of 2</Pill></div>
        {orders.length?<><div className="order-grid">{orders.slice(0,5).map(o=><button type="button" key={o.order_id} className={`order-card ${order?.order_id===o.order_id?'selected':''}`} onClick={()=>setOrder(o)}><div className="order-card-top"><span className="order-icon"><Package size={19}/></span><span className="radio-dot">{order?.order_id===o.order_id&&<span/>}</span></div><b>Order #{o.order_id}</b><small>{date(o.order_date)}</small><div className="order-card-bottom"><Pill tone={o.order_status==='delivered'?'green':'neutral'}>{pretty(o.order_status)}</Pill><strong>{money(o.total_amount,o.currency||'INR')}</strong></div><div className="order-items">{(o.items||[]).slice(0,2).map((it,i)=><span key={i}>{it.product_name||it.name||'Item'}{i===0&&(o.items||[]).length>1?' · ':''}</span>)}</div></button>)}</div>
        <div className="order-continue"><span>{order?`Order #${order.order_id} selected`:'Select an order to continue'}</span><Button disabled={!order||busy} onClick={()=>onContact(order)}>{busy?'Starting…':<>Start a conversation <ArrowRight size={16}/></>}</Button></div></>:<Empty icon={Package} title="No recent orders found" body="You can still contact customer care about an account, payment or general issue." action={<Button disabled={busy} onClick={()=>onContact(null)}>{busy?'Starting…':'Create a support request'} <ArrowRight size={16}/></Button>}/> }
      </section>}
    <div className="customer-assurance"><ShieldCheck size={17}/><span>Your information is private and only visible to the support team handling your request.</span></div>
  </main><Footer/></div>;
}
function CustomerTicket({ticket:t}){
 const [expanded,setExpanded]=useState(false);
 const status=t.status||t.ticket_status||'open';const tone=['resolved','closed'].includes(status)?'green':status==='under_review'?'amber':'blue';
 return <div className="customer-ticket"><button type="button" className="customer-ticket-main" onClick={()=>setExpanded(v=>!v)}><span className="ticket-type-icon"><FileText size={18}/></span><span className="customer-ticket-info"><b>{t.subject||`Support request ${t.ticket_number||''}`}</b><small>{t.ticket_number||`Temporary conversation`} · {date(t.created_at)}</small></span><Pill tone={tone}>{pretty(status)}</Pill><ChevronDown className={expanded?'rotated':''} size={17}/></button>{expanded&&<div className="ticket-expanded"><div><small>Order reference</small><b>{t.order_id?`#${t.order_id}`:'Not linked'}</b></div><div><small>Request type</small><b>{pretty(t.ticket_type||'temporary')}</b></div>{t.priority&&<div><small>Priority</small><b>{pretty(t.priority)}</b></div>}{t.resolution_notes&&<p>{t.resolution_notes}</p>}</div>}</div>
}

function CustomerChat({identity,support,onSend,onResolve,onBack,onLogout,busy,error}){
 const [message,setMessage]=useState('');const end=useRef(null);
 useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth'});},[support?.messages?.length,busy]);
 const submit=e=>{e.preventDefault();if(!message.trim()||busy)return;onSend(message);setMessage('');};
 return <div className="app-shell chat-shell"><AppHeader identity={identity} onLogout={onLogout}/><main className="chat-main"><button type="button" className="back-link" onClick={onBack}><ArrowLeft size={16}/> Back to your requests</button><div className="chat-heading"><div><div className="eyebrow">CUSTOMER CARE</div><h1>Let's talk it through.</h1><p>Our support assistant is here to help. If needed, a team member will step in.</p></div><div className="case-reference"><small>CASE REFERENCE</small><b>{support?.ticket_number||'Temporary session'}</b><Pill tone="green">{pretty(support?.status||'active')}</Pill></div></div>
 <section className="chat-card"><div className="chat-topbar"><div className="support-avatar"><Headphones size={18}/></div><div><b>Customer Support</b><small><span className="online-dot"/> Usually replies in a few moments</small></div><span className="chat-order">Order #{support?.order_id}</span></div>
  <div className="chat-messages">{(support?.messages||[]).map((m,i)=>{const mine=['user','customer'].includes(m.role)||m.sender==='customer';const isLatestAssistant=!mine&&i===support?.messages?.length-1;return <div className={`message-row ${mine?'mine':''}`} key={i}><div className="message-bubble"><p>{m.content||m.message||m.text||''}</p><small>{date(m.created_at||m.timestamp)}</small>{isLatestAssistant&&support?.resolution_pending&&!support?.read_only&&<div className="resolution-action"><Button kind="outline" size="small" disabled={busy} onClick={onResolve}><CheckCircle2 size={14}/> Yes, this is resolved</Button></div>}</div></div>})}{busy&&<div className="message-row"><div className="thinking-indicator"><span className="thinking-dots"><i/><i/><i/></span><span>Reviewing your message…</span></div></div>}<div ref={end}/></div>
 <ErrorNote message={error}/>{support?.read_only||['closed','resolved'].includes(support?.status)?<div className="chat-closed-note">This case is with our support team. You can review the conversation here.</div>:<form className="chat-composer" onSubmit={submit}><input value={message} onChange={e=>setMessage(e.target.value)} placeholder="Write your message…" disabled={busy}/><Button type="submit" disabled={!message.trim()||busy}><Send size={17}/> Send</Button></form>}<div className="chat-note"><ShieldCheck size={14}/> Please don't share passwords or full payment details in chat.</div></section></main><Footer/></div>;
}

function StaffHome({identity,tickets,allTickets,counts,filters,setFilters,tab,setTab,detail,selected,detailTab,setDetailTab,onOpen,onBack,onLogout,onRefresh,onClearFilters,onReply,onUpdate,busy,error,onClearError}){
 const [reply,setReply]=useState('');const [showFilters,setShowFilters]=useState(false);const [resolution,setResolution]=useState('');
 const [mobileDetail,setMobileDetail]=useState(false);
 const supervisor=identity.role==='supervisor';
 const changeFilter=(key,value)=>setFilters(v=>({...v,[key]:value}));
 const selectTicket=async t=>{await onOpen(t);setMobileDetail(true);};
 const submitReply=async e=>{e.preventDefault();if(!reply.trim()||busy)return;const sent=await onReply(reply);if(sent)setReply('');};
 const statusTone=s=>['closed','resolved'].includes(s)?'green':s==='under_review'?'amber':s==='awaiting_customer'?'blue':'neutral';
 return <div className="staff-shell"><AppHeader identity={identity} onLogout={onLogout} staff/><div className="staff-layout">
  <aside className={`staff-sidebar ${mobileDetail?'hide-mobile':''}`}><div className="sidebar-title"><div><div className="eyebrow">WORKSPACE</div><h2>Case management</h2></div><button type="button" className="icon-button" onClick={onRefresh} title="Refresh"><Activity size={17}/></button></div>
   <div className="sidebar-nav"><button type="button" className={tab==='all'?'active':''} onClick={()=>{setTab('all');setMobileDetail(false)}}><Layers3 size={17}/> All tickets <span>{allTickets.length}</span></button><button type="button" className={tab==='intervention'?'active':''} onClick={()=>{setTab('intervention');setMobileDetail(false)}}><AlertCircle size={17}/> Needs intervention <span>{allTickets.filter(t=>t.human_intervention_required).length}</span></button><button type="button" className={tab==='official'?'active':''} onClick={()=>{setTab('official');setMobileDetail(false)}}><FileText size={17}/> Official tickets</button><button type="button" className={tab==='temporary'?'active':''} onClick={()=>{setTab('temporary');setMobileDetail(false)}}><MessageCircle size={17}/> Temporary chats</button></div>
   <div className="sidebar-divider"/><div className="sidebar-metrics"><small>OPEN WORK</small><div><span>Open</span><b>{counts.open||0}</b></div><div><span>Under review</span><b>{counts.under_review||0}</b></div><div><span>Awaiting customer</span><b>{counts.awaiting_customer||0}</b></div></div>
   <div className="sidebar-bottom"><div className="staff-user"><span className="avatar">{identity.display_name?.slice(0,1)}</span><span><b>{identity.display_name}</b><small>{pretty(identity.role)}</small></span></div></div>
  </aside>
  <main className={`ticket-workspace ${mobileDetail?'hide-mobile':''}`}><div className="workspace-head"><div><div className="eyebrow">SUPPORT DESK</div><h1>{tab==='intervention'?'Needs your attention':tab==='official'?'Official tickets':tab==='temporary'?'Temporary conversations':'All tickets'}</h1><p>Review customer conversations and decide what needs to happen next.</p></div><div className="workspace-actions"><Button kind="outline" size="small" onClick={()=>setShowFilters(v=>!v)}><SlidersHorizontal size={16}/> Filters</Button><Button kind="outline" size="small" onClick={onRefresh}><Activity size={16}/> Refresh</Button></div></div>
   <ErrorNote message={error} onClose={onClearError}/>
   {showFilters&&<div className="filter-panel"><div className="filter-grid"><label>Status<select value={filters.status} onChange={e=>changeFilter('status',e.target.value)}><option value="">All statuses</option>{['open','awaiting_customer','under_review','resolved','closed'].map(x=><option key={x} value={x}>{pretty(x)}</option>)}</select></label><label>Type<select value={filters.ticket_type} onChange={e=>changeFilter('ticket_type',e.target.value)}><option value="">All types</option><option value="official">Official</option><option value="temporary">Temporary</option></select></label><label>Priority<select value={filters.priority} onChange={e=>changeFilter('priority',e.target.value)}><option value="">All priorities</option>{['low','medium','high','urgent'].map(x=><option key={x} value={x}>{pretty(x)}</option>)}</select></label><label>Intervention<select value={filters.intervention} onChange={e=>changeFilter('intervention',e.target.value)}><option value="">Any</option><option value="true">Required</option><option value="false">Not required</option></select></label><label>Assigned team<input value={filters.assigned_team} onChange={e=>changeFilter('assigned_team',e.target.value)} placeholder="Exact team name"/></label><label>Category<input value={filters.category} onChange={e=>changeFilter('category',e.target.value)} placeholder="Exact category"/></label></div><div className="filter-footer"><button type="button" className="text-button" onClick={onClearFilters}>Clear all</button><Button size="small" onClick={onRefresh}>Apply filters</Button></div></div>}
   <div className="ticket-search"><Search size={17}/><input placeholder="Search by ticket, customer name or ID" value={filters.search} onChange={e=>changeFilter('search',e.target.value)} onKeyDown={e=>e.key==='Enter'&&onRefresh()}/><button type="button" onClick={onRefresh}>Search</button></div>
   <div className="ticket-table-head"><span>CASE / CUSTOMER</span><span>TYPE</span><span>PRIORITY</span><span>STATUS</span><span>LAST ACTIVITY</span></div>
   <div className="staff-ticket-list">{tickets.length?tickets.map(t=><button type="button" key={t.conversation_id} className={`staff-ticket-row ${selected?.conversation_id===t.conversation_id?'selected':''}`} onClick={()=>selectTicket(t)}><span className="case-cell"><span className="case-icon">{t.human_intervention_required?<AlertCircle size={17}/>:<MessageCircle size={17}/>}</span><span><b>{t.ticket_number||'Temporary conversation'}</b><small>{t.first_name} {t.last_name} · #{t.customer_id}</small></span></span><span><Pill>{pretty(t.ticket_type)}</Pill></span><span><Pill tone={t.priority==='urgent'||t.priority==='high'?'amber':'neutral'}>{pretty(t.priority||'—')}</Pill></span><span><Pill tone={statusTone(t.status)}>{pretty(t.status)}</Pill></span><span className="activity-cell">{date(t.last_activity_at)}</span></button>):<Empty icon={Filter} title="No matching tickets" body="Try changing your filters or search terms."/>}</div>
   <div className="list-foot">Showing {tickets.length} {tickets.length===1?'case':'cases'} · Sorted by attention and latest activity</div>
  </main>
  <aside className={`ticket-detail ${mobileDetail?'mobile-open':''}`}>{selected?<><div className="detail-top"><button type="button" className="mobile-back" onClick={()=>setMobileDetail(false)}><ArrowLeft size={16}/> Back to list</button><div className="detail-top-actions"><button type="button" className="icon-button" title="Close detail" onClick={()=>{onBack();setMobileDetail(false);}}><X size={17}/></button></div><div className="eyebrow">CASE DETAILS</div><h2>{selected.ticket_number||'Temporary conversation'}</h2><div className="detail-tags"><Pill tone={statusTone(detail?.conversation?.status||selected.status)}>{pretty(detail?.conversation?.status||selected.status)}</Pill><Pill>{pretty(selected.ticket_type)}</Pill>{selected.human_intervention_required&&<Pill tone="amber">Needs intervention</Pill>}</div></div>
   {!detail?<Loading label="Loading case details"/>:<><div className="detail-tabs"><button type="button" className={detailTab==='conversation'?'active':''} onClick={()=>setDetailTab('conversation')}>Conversation</button><button type="button" className={detailTab==='overview'?'active':''} onClick={()=>setDetailTab('overview')}>Overview</button><button type="button" className={detailTab==='technical'?'active':''} onClick={()=>setDetailTab('technical')}>Technical data</button></div>
   {detailTab==='conversation'&&<><div className="detail-conversation">{(detail.conversation?.conversation||[]).map((m,i)=><div className={`detail-message ${['agent','staff'].includes(m.role)?'staff-message':''}`} key={i}><div><b>{pretty(m.role||'customer')}</b><small>{date(m.created_at||m.timestamp)}</small></div><p>{m.content||m.message||m.text||JSON.stringify(m)}</p>{m.metadata&&<details><summary>Message metadata</summary><pre>{JSON.stringify(m.metadata,null,2)}</pre></details>}</div>)}</div><form className="reply-box" onSubmit={submitReply}><textarea rows="3" placeholder={['closed','resolved'].includes(detail.conversation?.status)?'This case is closed. Reopen it to reply.':'Write a reply to the customer…'} value={reply} onChange={e=>setReply(e.target.value)} disabled={['closed','resolved'].includes(detail.conversation?.status)}/><div><small>Reply will be added to the customer conversation.</small><Button size="small" type="submit" disabled={!reply.trim()||busy||['closed','resolved'].includes(detail.conversation?.status)}>{busy?'Sending…':'Send reply'} <Send size={14}/></Button></div></form></>}
   {detailTab==='overview'&&<div className="detail-overview"><DetailGroup title="Customer"><DetailItem label="Name" value={`${detail.customer?.first_name||''} ${detail.customer?.last_name||''}`}/><DetailItem label="Customer ID" value={detail.customer?.customer_id}/><DetailItem label="Email" value={detail.customer?.email}/><DetailItem label="Phone" value={detail.customer?.phone}/></DetailGroup><DetailGroup title="Order"><DetailItem label="Order ID" value={detail.order?.order_id}/><DetailItem label="Order status" value={detail.order?.order_status}/><DetailItem label="Created" value={date(detail.order?.created_at)}/></DetailGroup><DetailGroup title="Ticket"><DetailItem label="Category" value={detail.official_ticket?.category||selected.category}/><DetailItem label="Priority" value={detail.official_ticket?.priority||selected.priority}/><DetailItem label="Assigned team" value={detail.official_ticket?.assigned_team||selected.assigned_team}/><DetailItem label="Created" value={date(detail.conversation?.created_at)}/></DetailGroup></div>}
   {detailTab==='technical'&&<div className="technical-panel"><div className="technical-intro"><Activity size={16}/><span>Internal diagnostics · visible to staff only</span></div><TechnicalSummary conversation={detail.conversation} technical={detail.technical}/><TechBlock title="Conversation state" data={detail.technical}/><TechBlock title="Full conversation record" data={detail.conversation}/><TechBlock title="Official ticket record" data={detail.official_ticket}/><TechBlock title="Ticket event history" data={detail.events}/><TechBlock title="Linked order" data={detail.order}/></div>}
   <div className="staff-actions"><div className="action-heading"><b>Case actions</b><span>{supervisor?'Supervisor controls':'Admin controls'}</span></div><div className="action-row">{supervisor?<label>Status<select value={detail.conversation?.status||selected.status} onChange={e=>onUpdate({status:e.target.value,resolution_notes:resolution})}><option value="open">Open</option><option value="awaiting_customer">Awaiting customer</option><option value="under_review">Under review</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select></label>:<Button kind="outline" size="small" disabled={busy||['closed','resolved'].includes(detail.conversation?.status)} onClick={()=>onUpdate({status:'closed',resolution_notes:resolution})}>Close case</Button>}<Button kind="outline" size="small" disabled={busy} onClick={()=>onUpdate({intervention_required:!Boolean(detail.conversation?.human_intervention_required)})}>{detail.conversation?.human_intervention_required?'Clear human review':'Request human review'}</Button></div><p className="action-help">{detail.conversation?.human_intervention_required?'Human review is flagged. Clear it only after the issue has been reviewed.':'Flag this when the AI should stop handling the case and a staff member must take over.'}</p>
   {supervisor&&<div className="supervisor-controls"><label>Priority<select defaultValue={detail.official_ticket?.priority||selected.priority||'medium'} onChange={e=>onUpdate({priority:e.target.value})}>{['low','medium','high','urgent'].map(x=><option key={x}>{x}</option>)}</select></label><label>Category<input defaultValue={detail.official_ticket?.category||selected.category||''} onBlur={e=>onUpdate({category:e.target.value})}/></label><label>Assigned team<input defaultValue={detail.official_ticket?.assigned_team||selected.assigned_team||''} onBlur={e=>onUpdate({assigned_team:e.target.value})}/></label></div>}
   <label className="resolution-label">Resolution note (optional)<textarea rows="2" value={resolution} onChange={e=>setResolution(e.target.value)} placeholder="Add a short internal note…"/></label>
   </div></>}
  </>:<div className="detail-placeholder"><span className="detail-placeholder-icon"><PanelRightClose size={24}/></span><h3>Choose a case to inspect</h3><p>Select any ticket from the list to view its conversation, customer details and internal diagnostics.</p></div>}</aside>
 </div><Footer/></div>;
}
function DetailGroup({title,children}){return <section className="detail-group"><h4>{title}</h4>{children}</section>}
function DetailItem({label,value}){return <div className="detail-item"><small>{label}</small><b>{value||'—'}</b></div>}
function TechnicalSummary({conversation,technical}){
 const messages=conversation?.conversation||[];
 const latest=[...messages].reverse().find(m=>m?.metadata?.technical_diagnostics);
 const diag=latest?.metadata?.technical_diagnostics||{};
 const ml=diag.ml_assessment||{};
 const predictions=ml.predictions||{};
 const models=diag.models||{};
 const latencies=diag.stage_latencies_seconds||{};
 const evidence=diag.policy_evidence||diag.retrieval?.evidence||[];
 const toolCalls=diag.tool_diagnostics?.calls||[];
 const pct=v=>Number.isFinite(Number(v))?`${Math.round(Number(v)*100)}%`:'—';
 const metric=(label,value)=> <div className="detail-item" key={label}><small>{label}</small><b>{value??'—'}</b></div>;
 return <div className="detail-overview">
  <DetailGroup title="AI decision summary">
   {metric('ML architecture',models.ml_model==='huggingface'?'MuRIL multitask classifier':models.ml_model==='traditional_ml'?'Traditional ML (TF-IDF + classifiers)':models.ml_model||'Not recorded')}
   {metric('Predicted intent',predictions.intent?.label?`${pretty(predictions.intent.label)} · ${pct(predictions.intent.confidence)}`:'—')}
   {metric('Predicted priority',predictions.priority?.label?`${pretty(predictions.priority.label)} · ${pct(predictions.priority.confidence)}`:'—')}
   {metric('Escalation risk',predictions.escalation_risk?.label!=null?`${pretty(String(predictions.escalation_risk.label))} · ${pct(predictions.escalation_risk.confidence)}`:'—')}
   {metric('Language',ml.language||'—')}
  </DetailGroup>
  <DetailGroup title="LLM and knowledge retrieval">
   {metric('LLM',models.llm_provider&&models.llm_model?`${models.llm_provider} · ${models.llm_model}`:diag.intervention_assessment?'Diagnostics captured':'—')}
   {metric('RAG status',diag.retrieval?.status|| (diag.knowledge_routing?.rag_required?'Required':'Not recorded'))}
   {metric('Embedding model',models.embedding_model||'—')}
   {metric('Reranker',models.reranker_model||'—')}
   {metric('Retrieved evidence',evidence.length)}
  </DetailGroup>
  <DetailGroup title="Business tools">
   {metric('Tools used',toolCalls.length)}
   {metric('Tools',toolCalls.length?toolCalls.map(x=>pretty(x.tool||'')).join(', '):'None required')}
   {metric('Tool latency',diag.tool_diagnostics?.latency_seconds!=null?`${diag.tool_diagnostics.latency_seconds}s`:'—')}
  </DetailGroup>
  <DetailGroup title="Performance">
   {metric('ML',latencies.ml!=null?`${latencies.ml}s`:(ml.latency_seconds!=null?`${ml.latency_seconds}s`:'—'))}
   {metric('Security / intervention',latencies.security_and_intervention!=null?`${latencies.security_and_intervention}s`:'—')}
   {metric('RAG retrieval',latencies.rag_retrieval_and_reranking!=null?`${latencies.rag_retrieval_and_reranking}s`:'—')}
   {metric('LLM response',latencies.final_response!=null?`${latencies.final_response}s`:'—')}
   {metric('Total',diag.total_latency_seconds!=null?`${diag.total_latency_seconds}s`:'—')}
  </DetailGroup>
  {!latest&&<p className="detail-muted">Detailed ML/LLM diagnostics are available for turns processed after diagnostics were enabled. Conversation state version: {technical?.version??'—'}.</p>}
  {diag.intervention_assessment&&<TechBlock title="Intervention assessment" data={diag.intervention_assessment}/>}
  {diag.security_assessment&&<TechBlock title="Security assessment" data={diag.security_assessment}/>}
  {diag.knowledge_routing&&<TechBlock title="Knowledge routing decision" data={diag.knowledge_routing}/>}
  {evidence.length>0&&<TechBlock title={`Retrieved policy evidence (${evidence.length})`} data={evidence}/>}
  {diag.tool_diagnostics&&<TechBlock title="Tool-call results (staff only)" data={diag.tool_diagnostics}/> }
  {diag.stage_latencies_seconds&&<TechBlock title="Pipeline stage timings" data={diag.stage_latencies_seconds}/>}
 </div>;
}
function TechBlock({title,data}){const [open,setOpen]=useState(false);return <section className="tech-block"><button type="button" onClick={()=>setOpen(v=>!v)}><span>{title}</span><ChevronDown size={15} className={open?'rotated':''}/></button>{open&&<pre>{JSON.stringify(data??null,null,2)}</pre>}</section>}
function Footer(){return <footer className="app-footer"><span>© Customer Support</span><span></span></footer>;}