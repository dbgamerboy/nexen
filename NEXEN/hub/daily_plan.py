"""Persistent rent-first NEXEN daily checklist. Completion records are user marks."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, StrictBool

try:
    DAY_ZONE = ZoneInfo("America/Los_Angeles")
    ZONE_LABEL = "America/Los_Angeles"
except ZoneInfoNotFoundError:
    DAY_ZONE = None
    ZONE_LABEL = "system local time (IANA timezone data unavailable)"

ITEMS = (
    ("discord", "08:00", "Review Discord digest", "Read the local digest, choose three useful actions and check any missing source connection.", "/"),
    ("lumipaw", "08:15", "Move Lumipaw one step forward", "Verify the product facts and the next store, payment or ad-account setup step. Keep the ad test capped at $50 total and $50/day.", "/api/hub/document/lumipaw"),
    ("music", "09:00", "Prepare the next music release", "Choose one track or asset, review its bounce and metadata, and draft the next release or content step.", "/lab"),
    ("services", "08:05", "Check service health", "Check the supervisor, local models and configured workflow services. Record any unavailable or degraded service and the next recovery step.", "/diagnostics"),
    ("failed_work", "08:10", "Review failed or blocked work", "Inspect failed jobs and blocked tasks. Record the cause, the next step and who can resolve it; confirm prerequisites before retrying work.", "/diagnostics"),
    ("source_review", "08:20", "Review new knowledge and plan conflicts", "Check what was actually ingested and review new implementation plans. Keep unread sources and conflicting versions visible, and choose the current requirement before starting work.", "/plans"),
    ("required_logins", "08:25", "Clear required login steps", "Review the connections page and finish the sign-ins or setup steps that are currently needed. Verify each connection afterward; never store passwords in task notes.", "/connections"),
)
RENT_ITEM=("rent", "08:00", "Rent first: review the next assistance step", "Review the verified assistance contacts and record the next real follow-up. Completing this daily review does not resolve the main rent task or claim a call was made.", "/tasks")


def _rent_state(c):
    names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'task_details','hub_requests'} <= names:
        row=c.execute("SELECT r.id,r.status FROM hub_requests r JOIN task_details d ON d.request_id=r.id WHERE d.seed_key='rent'").fetchone()
        if row:return {'request_id':row[0],'status':row[1],'requires_action':row[1]!='done'}
    return {'request_id':None,'status':'unconfirmed','requires_action':True}


def _today():
    return (datetime.now(DAY_ZONE) if DAY_ZONE else datetime.now().astimezone()).date().isoformat()


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS daily_plan_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, item_key TEXT NOT NULL,
        scheduled_time TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
        action_path TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
        completed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(day,item_key))""")
    c.execute("""CREATE TABLE IF NOT EXISTS daily_plan_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
        completed INTEGER NOT NULL CHECK(completed IN (0,1)), created_at TEXT NOT NULL)""")


def ensure_day(db, day=None):
    """Idempotently seed the current local day; old completion history is retained."""
    selected = date.fromisoformat(day or _today()).isoformat()
    stamp = _stamp()
    with db.connect() as c:
        _schema(c)
        tasks=([RENT_ITEM] if _rent_state(c)['requires_action'] else [])+list(ITEMS)
        for key, at, title, detail, action in tasks:
            c.execute("""INSERT OR IGNORE INTO daily_plan_items
                (day,item_key,scheduled_time,title,detail,action_path,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)""", (selected,key,at,title,detail,action,stamp,stamp))
    return selected


def get_day(db, day=None):
    selected = ensure_day(db, day)
    with db.connect() as c:
        rent=_rent_state(c)
        rows = c.execute("SELECT * FROM daily_plan_items WHERE day=? AND (? OR item_key!='rent') ORDER BY CASE item_key WHEN 'rent' THEN 0 ELSE 1 END,scheduled_time,id",(selected,int(rent['requires_action']))).fetchall()
        columns = ["id","day","item_key","scheduled_time","title","detail","action_path","completed","completed_at","created_at","updated_at"]
        items = [dict(zip(columns,tuple(row))) for row in rows]
    for item in items:
        item["completed"] = bool(item["completed"])
    return {"day":selected,"timezone":ZONE_LABEL,"items":items,"completed":sum(i["completed"] for i in items),"total":len(items),"rent_priority":rent,"completion_basis":"user_marked","executed_actions":False}


def set_completed(db, item_id, completed, day=None):
    if type(completed) is not bool:
        raise ValueError("completed must be a boolean")
    selected = ensure_day(db,day)
    stamp = _stamp()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT completed FROM daily_plan_items WHERE id=? AND day=?",(item_id,selected)).fetchone()
        if row is None:
            raise KeyError("This item is not part of today's checklist")
        if bool(row[0]) != completed:
            c.execute("UPDATE daily_plan_items SET completed=?,completed_at=?,updated_at=? WHERE id=? AND day=?",(int(completed),stamp if completed else None,stamp,item_id,selected))
            event_id=c.execute("INSERT INTO daily_plan_events(item_id,completed,created_at) VALUES(?,?,?)",(item_id,int(completed),stamp)).lastrowid
            from completion_memory import record_event
            title=c.execute('SELECT title FROM daily_plan_items WHERE id=?',(item_id,)).fetchone()[0]
            record_event(c,'day-event:'+str(event_id),'daily_checklist',item_id,title,'done' if completed else 'reopened',outcome='Checklist date: '+selected)
    from completion_memory import export_journal
    result=get_day(db,selected)
    result['memory_sync']=export_journal(db)
    return result


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: StrictBool


def register(app, db):
    ensure_day(db)

    @app.get("/api/day")
    def read_day():
        return get_day(db)

    @app.get('/api/day/history')
    def day_history():
        with db.connect() as c:
            rows=c.execute('''SELECT e.id,i.day,i.title,e.completed,e.created_at FROM daily_plan_events e
                JOIN daily_plan_items i ON i.id=e.item_id ORDER BY e.id DESC LIMIT 100''').fetchall()
        return {'history':[{'id':r[0],'day':r[1],'title':r[2],'status':'COMPLETED' if r[3] else 'REOPENED','created_at':r[4]} for r in rows],'completion_basis':'user_marked'}

    @app.post("/api/day/{item_id}")
    def complete_item(item_id:int, body:Completion):
        try:
            return set_completed(db,item_id,body.completed)
        except KeyError as e:
            raise HTTPException(404,"That checklist item is not in the current day") from e

    @app.get("/day",response_class=HTMLResponse)
    def day_page():
        return PAGE


PAGE = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXEN / Your day</title><style>
:root{color-scheme:dark;font-family:Inter,Segoe UI,system-ui,sans-serif;background:#06101d;color:#e6f4ff}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 15% 0,#13558370,transparent 60%),radial-gradient(ellipse at 90% 70%,#102c6260,transparent 60%),#06101d}a{color:#9ddcff;text-decoration:none}a:hover{text-decoration:underline}main{width:min(960px,100%);margin:auto;padding:38px 24px 70px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px}.brand{font-size:12px;font-weight:700;letter-spacing:3px;color:#a8c8df}h1{font-size:clamp(40px,7vw,68px);letter-spacing:-3px;line-height:1.05;margin:35px 0 18px;font-weight:600}.intro{color:#9fb9d0;max-width:630px;line-height:1.65}.progress{display:flex;align-items:center;gap:20px;background:#14374d55;border:1px solid #b5e5ff25;border-radius:18px;padding:18px 22px;margin:27px 0;backdrop-filter:blur(22px)}progress{width:100%;height:7px;accent-color:#8fddff}.count{white-space:nowrap;font-size:14px}article{display:grid;grid-template-columns:65px 1fr auto;align-items:start;gap:20px;padding:25px 23px;border:1px solid #b5e5ff25;background:linear-gradient(125deg,#1b415970,#10223780);border-radius:23px;margin:15px 0;box-shadow:0 18px 50px #0002;backdrop-filter:blur(22px)}article.done{border-color:#7fe5b145}.done h2{text-decoration:line-through;text-decoration-color:#9ee8c5;animation:completed-in .55s ease both}.completion-label{display:block;color:#a9efc9;font-size:11px;font-weight:750;letter-spacing:2px;margin-bottom:8px}@keyframes completed-in{from{opacity:.3;transform:translateX(-7px)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){.done h2{animation:none}}time{color:#9ddcff;font-variant-numeric:tabular-nums;font-size:14px;padding-top:4px}h2{font-size:21px;font-weight:550;margin:0 0 10px;letter-spacing:-.4px}article p{color:#a3bdce;line-height:1.55;font-size:14px;margin:0 0 16px}button{font:inherit;cursor:pointer;color:#e6f4ff;border:1px solid #96c6e653;background:#32688955;border-radius:12px;padding:10px 14px}button:disabled{opacity:.5;cursor:wait}button:hover{background:#417c9e77}.done button{background:#275d4355}.fine{font-size:12px;color:#8caabc;line-height:1.7}#status{min-height:26px;color:#b4ddf4}button:focus-visible,a:focus-visible{outline:2px solid #bceaff;outline-offset:4px}@media(max-width:620px){article{grid-template-columns:1fr;gap:11px}article button{justify-self:start}.top{align-items:flex-start}.progress{padding:16px}}
</style></head><body><main><div class="top"><a href="/">← NEXEN</a><span class="brand">LIFE OS / DAILY PLAN</span></div><h1>Make today count.</h1><p class="intro">Rent comes first while its main task is unfinished. Review your digest, check services and blocked work, clear setup steps, then move the store and music forward. Your checklist stays saved between sessions.</p><div class="progress"><span class="count" id="count">Loading today…</span><progress id="progress" max="8" value="0" aria-label="Daily checklist completion"></progress></div><p class="fine" id="date"></p><div id="items"></div><details><summary id="history-open">Completion history</summary><div id="history"></div></details><p id="status" role="status" aria-live="polite"></p><p class="fine">Times organize your day. Checking an item records your own completion mark; it does not run an automation, verify a payment or publish anything. A new checklist starts on the next local day and prior marks remain in history.</p></main><script>
const el=id=>document.getElementById(id);let loading=false;async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.detail||'Checklist request failed');return d}
function render(d){el('count').textContent=d.completed+' / '+d.total+' complete';el('progress').max=d.total||3;el('progress').value=d.completed;el('date').textContent=d.day+' · '+d.timezone;el('items').replaceChildren();for(const item of d.items){const card=document.createElement('article');card.className=item.completed?'done':'';const time=document.createElement('time');time.textContent=item.scheduled_time;const content=document.createElement('div');const title=document.createElement('h2');title.textContent=item.title;const detail=document.createElement('p');detail.textContent=item.detail;const link=document.createElement('a');link.href=item.action_path;link.textContent='Open workspace →';const badge=document.createElement('span');badge.className='completion-label';badge.textContent=item.completed?'COMPLETED':'';content.append(badge,title,detail,link);const button=document.createElement('button');button.textContent=item.completed?'Reopen':'Mark COMPLETED';button.setAttribute('aria-pressed',String(item.completed));button.setAttribute('aria-label',(item.completed?'Reopen ':'Complete ')+item.title);button.onclick=async()=>{if(loading)return;loading=true;button.disabled=true;try{const next=await api('/api/day/'+item.id,{completed:!item.completed});render(next);el('status').textContent='Checklist saved. Completion history is kept in local memory.'}catch(e){el('status').textContent=e.message;button.disabled=false}finally{loading=false}};card.append(time,content,button);el('items').append(card)}}
el('history-open').onclick=async()=>{try{const d=await api('/api/day/history');el('history').replaceChildren();for(const h of d.history){const line=document.createElement('p');line.className='fine';line.textContent=h.created_at+' / '+h.status+' / '+h.title;el('history').append(line)}}catch(e){el('status').textContent=e.message}};
async function refresh(){if(loading)return;try{render(await api('/api/day'))}catch(e){el('status').textContent=e.message}}refresh();setInterval(()=>{if(!document.hidden)refresh()},60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
</script></body></html>'''
