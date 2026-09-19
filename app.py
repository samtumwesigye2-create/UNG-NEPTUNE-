from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Literal, Optional

app = FastAPI(title="UNG-NEPTUNE", version="0.1.0")

Domain = Literal["land","air","maritime","space","cyber","joint","civilian"]

class Event(BaseModel):
    domain: Domain
    type: str
    title: str
    source: str
    confidence: float = 1.0
    classification: str = "UNCLASSIFIED"
    releasability: str = "INTERNAL"
    x: Optional[float] = None
    y: Optional[float] = None

class Task(BaseModel):
    title: str
    owner: str
    domain: Domain = "joint"
    priority: Literal["low","normal","high","critical"] = "normal"
    status: Literal["open","in_progress","complete"] = "open"

class ReadinessUpdate(BaseModel):
    name: str
    category: Literal["personnel","logistics","communications","mobility","power","other"]
    status: Literal["ready","limited","degraded","offline"]
    note: str = ""

class CommUpdate(BaseModel):
    link: str
    status: Literal["healthy","degraded","offline"]
    latency_ms: Optional[int] = None
    note: str = ""

EVENTS = [
    {"id":1,"domain":"joint","type":"system","title":"NEPTUNE Core online","source":"NEPTUNE","confidence":1.0,"classification":"UNCLASSIFIED","releasability":"INTERNAL","time":"now","x":31,"y":48},
    {"id":2,"domain":"civilian","type":"readiness","title":"ICS profile available","source":"NEPTUNE","confidence":1.0,"classification":"UNCLASSIFIED","releasability":"INTERNAL","time":"now","x":62,"y":29},
]
TASKS = []
READINESS = [
    {"id":1,"name":"Core command node","category":"communications","status":"ready","note":"Primary services online","time":"now"},
    {"id":2,"name":"Edge synchronization","category":"other","status":"limited","note":"Standing by for remote nodes","time":"now"},
]
COMMS = [
    {"id":1,"link":"Core network","status":"healthy","latency_ms":18,"note":"Nominal","time":"now"},
    {"id":2,"link":"Edge sync","status":"degraded","latency_ms":None,"note":"No remote edge peers connected","time":"now"},
]

@app.get("/health")
def health():
    return {"ok": True, "system": "UNG-NEPTUNE", "version": "0.1.0"}

@app.get("/api/events")
def get_events():
    return EVENTS[-100:]

@app.post("/api/events")
def add_event(event: Event):
    item = event.model_dump()
    item["id"] = (EVENTS[-1]["id"] + 1) if EVENTS else 1
    item["time"] = datetime.now(timezone.utc).isoformat()
    EVENTS.append(item)
    return item

@app.get("/api/tasks")
def get_tasks():
    return TASKS

@app.post("/api/tasks")
def add_task(task: Task):
    item = task.model_dump()
    item["id"] = (TASKS[-1]["id"] + 1) if TASKS else 1
    item["created_at"] = datetime.now(timezone.utc).isoformat()
    TASKS.append(item)
    EVENTS.append({"id":(EVENTS[-1]["id"]+1) if EVENTS else 1,"domain":item["domain"],"type":"task","title":f'Task created: {item["title"]}',"source":"COMMAND","confidence":1.0,"classification":"UNCLASSIFIED","releasability":"INTERNAL","time":item["created_at"],"x":None,"y":None})
    return item

@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, status: Literal["open","in_progress","complete"]):
    for item in TASKS:
        if item["id"] == task_id:
            item["status"] = status
            return item
    return {"error":"not_found"}

@app.get("/api/readiness")
def get_readiness():
    return READINESS

@app.post("/api/readiness")
def add_readiness(update: ReadinessUpdate):
    item = update.model_dump()
    item["id"] = (READINESS[-1]["id"] + 1) if READINESS else 1
    item["time"] = datetime.now(timezone.utc).isoformat()
    READINESS.append(item)
    return item

@app.get("/api/comms")
def get_comms():
    return COMMS

@app.post("/api/comms")
def add_comm(update: CommUpdate):
    item = update.model_dump()
    item["id"] = (COMMS[-1]["id"] + 1) if COMMS else 1
    item["time"] = datetime.now(timezone.utc).isoformat()
    COMMS.append(item)
    return item

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UNG-NEPTUNE</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#07111d;color:#eaf1f7;font-family:Arial,sans-serif}
.top{height:82px;background:linear-gradient(90deg,#071629,#0b3152);border-bottom:2px solid #bda251;display:flex;align-items:center;justify-content:space-between;padding:0 26px}
.brand h1{margin:0;font:28px Georgia}.brand small{color:#d2b65e;letter-spacing:2px}
.status{font-size:12px;color:#9fd6ad;border:1px solid #305748;padding:9px 12px;border-radius:9px;background:#09261d}
.layout{display:grid;grid-template-columns:230px minmax(650px,1fr) 320px;min-height:calc(100vh - 82px)}
aside{background:#091827;border-right:1px solid #20364b;padding:22px 16px}
aside button{display:block;width:100%;text-align:left;color:#dce7f0;background:none;border:0;padding:11px;border-radius:8px;margin-bottom:5px;cursor:pointer}
aside button:hover,aside button.active{background:#103252;color:#f0d071}
main{padding:20px}.right{background:#091827;border-left:1px solid #20364b;padding:18px}
.strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:14px}
.metric,.panel{background:#0d1f31;border:1px solid #294159;border-radius:12px;padding:14px}
.metric b{display:block;font-size:20px;color:#f0d071}.metric span{font-size:11px;color:#9fb2c2}
.map{height:430px;background:linear-gradient(#ffffff0b 1px,transparent 1px),linear-gradient(90deg,#ffffff0b 1px,transparent 1px),radial-gradient(circle at 40% 45%,#17486c,#0a2034 58%,#071421);background-size:32px 32px,32px 32px,auto;border:1px solid #31506b;border-radius:14px;position:relative;overflow:hidden}
.map-title{position:absolute;top:15px;left:17px;color:#e4c76d;font:700 12px Arial;letter-spacing:1px;z-index:3}
.marker{position:absolute;width:12px;height:12px;border:2px solid #d6bd69;border-radius:50%;box-shadow:0 0 0 6px #d6bd6920;transform:translate(-50%,-50%)}
.marker span{display:none;position:absolute;left:15px;top:-7px;white-space:nowrap;background:#07111d;border:1px solid #31506b;padding:5px 7px;border-radius:6px;font-size:10px}.marker:hover span{display:block}
.domains{display:flex;gap:8px;margin:14px 0;flex-wrap:wrap}.domains button{background:#10283f;color:#dce7f0;border:1px solid #304b64;border-radius:8px;padding:8px 11px;cursor:pointer}.domains button.active{border-color:#d1b45a;color:#f4d577}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.panel h3{margin:0 0 10px;color:#f0d071}.row{padding:9px 0;border-bottom:1px solid #23394d;font-size:12px}.muted{color:#91a6b7}
.alert{padding:10px;border:1px solid #30475b;background:#0d2032;border-radius:9px;margin-bottom:9px;font-size:12px}.good{color:#9fd6ad}.warn{color:#f0d071}.bad{color:#ff9b9b}
input,select,textarea{width:100%;background:#07131f;color:#eef3f8;border:1px solid #334a61;border-radius:7px;padding:9px;margin:5px 0 9px}textarea{min-height:70px}
.action{background:#c7a247;color:#07111f;border:0;border-radius:7px;padding:9px 12px;font-weight:800;cursor:pointer}.mini{font-size:11px;padding:6px 8px}
.view{display:none}.view.active{display:block}.toolbar{display:flex;gap:8px;align-items:center;justify-content:space-between}.pill{font-size:10px;border:1px solid #3a5369;border-radius:20px;padding:3px 7px}
@media(max-width:900px){body{min-width:1180px}}
</style></head><body>
<div class="top"><div class="brand"><h1>UNG-NEPTUNE</h1><small>FIELD COMMAND MANAGEMENT · COMMON OPERATING PICTURE</small></div><div class="status">CORE ONLINE · EDGE READY</div></div>
<div class="layout">
<aside id="nav">
<button class="active" data-view="cop">Joint COP</button><button data-view="tasks">Command & Tasks</button><button data-view="readiness">Readiness</button><button data-view="logistics">Logistics</button><button data-view="communications">Communications</button><button data-view="incidents">Intel / Incidents</button><button data-view="spectrum">Spectrum Health</button><button data-view="edge">Edge Nodes</button><button data-view="audit">Audit & AAR</button>
</aside>
<main>
<div class="strip">
<div class="metric"><b>7</b><span>DOMAIN PROFILES</span></div><div class="metric"><b class="good">ONLINE</b><span>CORE STATUS</span></div><div class="metric"><b id="criticalCount">0</b><span>CRITICAL ALERTS</span></div><div class="metric"><b>100%</b><span>DATA SERVICES</span></div><div class="metric"><b>EDGE</b><span>DEGRADED MODE READY</span></div>
</div>

<section id="cop" class="view active">
<div class="domains" id="domains"></div>
<div class="map" id="map"><div class="map-title" id="mapTitle">JOINT COMMON OPERATING PICTURE</div></div>
<div class="grid">
<div class="panel"><h3>Command & Task Queue</h3><div id="taskPreview"></div></div>
<div class="panel"><h3>Communications Health</h3><div id="commPreview"></div></div>
<div class="panel"><h3>Readiness</h3><div id="readinessPreview"></div></div>
<div class="panel"><h3>Data Fusion</h3><div class="row">Normalized event bus <span class="good">ready</span></div><div class="row">Provenance & confidence metadata <span class="good">enabled</span></div><div class="row">Selected domain <span id="selectedDomain" class="warn">JOINT</span></div></div>
</div>
</section>

<section id="tasks" class="view"><div class="grid">
<div class="panel"><h3>Create Command Task</h3><form id="taskForm"><input name="title" placeholder="Task title" required><input name="owner" placeholder="Owner / team" required><select name="domain"><option>joint</option><option>land</option><option>air</option><option>maritime</option><option>space</option><option>cyber</option><option>civilian</option></select><select name="priority"><option>normal</option><option>high</option><option>critical</option><option>low</option></select><button class="action">Create Task</button></form></div>
<div class="panel"><h3>Active Task Queue</h3><div id="taskList"></div></div></div></section>

<section id="readiness" class="view"><div class="grid">
<div class="panel"><h3>Post Readiness Update</h3><form id="readinessForm"><input name="name" placeholder="Team / asset / node" required><select name="category"><option>personnel</option><option>logistics</option><option>communications</option><option>mobility</option><option>power</option><option>other</option></select><select name="status"><option>ready</option><option>limited</option><option>degraded</option><option>offline</option></select><textarea name="note" placeholder="Readiness note"></textarea><button class="action">Save Update</button></form></div>
<div class="panel"><h3>Readiness Board</h3><div id="readinessList"></div></div></div></section>

<section id="communications" class="view"><div class="grid">
<div class="panel"><h3>Update Communications Link</h3><form id="commForm"><input name="link" placeholder="Link / network name" required><select name="status"><option>healthy</option><option>degraded</option><option>offline</option></select><input name="latency_ms" type="number" min="0" placeholder="Latency ms (optional)"><textarea name="note" placeholder="Link note"></textarea><button class="action">Save Link Status</button></form></div>
<div class="panel"><h3>Communications Board</h3><div id="commList"></div></div></div></section>

<section id="incidents" class="view"><div class="grid">
<div class="panel"><h3>Post Operational Event</h3><form id="eventForm"><input name="title" placeholder="Event / incident title" required><input name="source" placeholder="Source" required><select name="domain"><option>joint</option><option>land</option><option>air</option><option>maritime</option><option>space</option><option>cyber</option><option>civilian</option></select><input name="type" placeholder="Type (incident, weather, sensor...)" value="incident"><input name="confidence" type="number" min="0" max="1" step=".05" value="1"><input name="x" type="number" min="2" max="98" step=".1" placeholder="Map X %"><input name="y" type="number" min="8" max="95" step=".1" placeholder="Map Y %"><button class="action">Publish Event</button></form></div>
<div class="panel"><h3>Event Ledger</h3><div id="eventLedger"></div></div></div></section>

<section id="logistics" class="view"><div class="panel"><h3>Logistics</h3><p class="muted">Resource readiness and sustainment records plug into the same readiness API. Use the Readiness workspace with category <b>logistics</b>.</p></div></section>
<section id="spectrum" class="view"><div class="panel"><h3>Spectrum Health</h3><p class="muted">Connectivity health, congestion, interference reports, and communications planning will appear here. Offensive electronic attack functions are not part of NEPTUNE.</p></div></section>
<section id="edge" class="view"><div class="panel"><h3>Edge Nodes</h3><div class="row"><span class="good">Core node online</span></div><div class="row">Remote edge nodes <span class="muted">none connected</span></div><div class="row">Store-and-forward <span class="good">ready</span></div></div></section>
<section id="audit" class="view"><div class="panel"><h3>Audit & After-Action Review</h3><p class="muted">Operational events, task creation, readiness updates, and communications changes are retained in the live event/data stores for this first build. Persistent audit storage is the next backend hardening step.</p></div></section>
</main>

<div class="right"><div class="toolbar"><h3 style="color:#f0d071">Live Event Stream</h3><span class="pill" id="eventCount">0 EVENTS</span></div><div id="eventStream"></div><h3 style="color:#f0d071;margin-top:24px">Design Rules</h3><div class="alert">Human authorization required for high-consequence actions.</div><div class="alert">MOSA / open API architecture.</div><div class="alert">Zero-trust / MLS-ready data labels.</div></div>
</div>

<script>
let selectedDomain='joint';
const domains=['joint','land','air','maritime','space','cyber','civilian'];
function cls(status){return ['ready','healthy'].includes(status)?'good':['offline'].includes(status)?'bad':'warn'}
async function api(url,opts){const r=await fetch(url,opts);return r.json()}
function showView(id){document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===id))}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>showView(b.dataset.view));

function renderDomains(){document.getElementById('domains').innerHTML=domains.map(d=>`<button class="${d===selectedDomain?'active':''}" onclick="selectDomain('${d}')">${d==='civilian'?'CIVILIAN ICS':d.toUpperCase()}</button>`).join('')}
function selectDomain(d){selectedDomain=d;document.getElementById('selectedDomain').textContent=d.toUpperCase();document.getElementById('mapTitle').textContent=(d==='joint'?'JOINT':d.toUpperCase())+' COMMON OPERATING PICTURE';renderDomains();refreshEvents()}

async function refreshEvents(){
 const events=await api('/api/events'); const filtered=selectedDomain==='joint'?events:events.filter(e=>e.domain===selectedDomain||e.domain==='joint');
 document.getElementById('eventCount').textContent=events.length+' EVENTS';
 document.getElementById('criticalCount').textContent=events.filter(e=>e.type==='critical').length;
 document.getElementById('eventStream').innerHTML=[...filtered].reverse().slice(0,12).map(e=>`<div class="alert"><b>${e.title}</b><br><span class="muted">${e.domain.toUpperCase()} · ${e.type} · ${e.source}</span></div>`).join('')||'<div class="muted">No events in this domain.</div>';
 document.getElementById('eventLedger').innerHTML=[...events].reverse().slice(0,30).map(e=>`<div class="row"><b>${e.title}</b><br><span class="muted">${e.domain} · ${e.type} · confidence ${Math.round((e.confidence||0)*100)}%</span></div>`).join('');
 const map=document.getElementById('map'); map.querySelectorAll('.marker').forEach(x=>x.remove());
 filtered.filter(e=>e.x!=null&&e.y!=null).forEach(e=>{const m=document.createElement('div');m.className='marker';m.style.left=e.x+'%';m.style.top=e.y+'%';m.innerHTML='<span>'+e.title+'</span>';map.appendChild(m)});
}
async function refreshTasks(){
 const a=await api('/api/tasks');
 const html=a.length?a.map(t=>`<div class="row"><b>${t.title}</b> <span class="pill">${t.priority}</span><br><span class="muted">${t.owner} · ${t.domain} · ${t.status}</span> ${t.status!=='complete'?'<button class="action mini" onclick="finishTask('+t.id+')">Complete</button>':''}</div>`).join(''):'<div class="muted">No active command tasks — ready for assignment.</div>';
 document.getElementById('taskList').innerHTML=html;document.getElementById('taskPreview').innerHTML=html;
}
async function finishTask(id){await api('/api/tasks/'+id+'?status=complete',{method:'PATCH'});refreshTasks()}
async function refreshReadiness(){
 const a=await api('/api/readiness');const html=[...a].reverse().map(r=>`<div class="row"><b>${r.name}</b> <span class="${cls(r.status)}">${r.status}</span><br><span class="muted">${r.category} · ${r.note||''}</span></div>`).join('');
 document.getElementById('readinessList').innerHTML=html;document.getElementById('readinessPreview').innerHTML=html||'<div class="muted">No readiness data.</div>';
}
async function refreshComms(){
 const a=await api('/api/comms');const html=[...a].reverse().map(r=>`<div class="row"><b>${r.link}</b> <span class="${cls(r.status)}">${r.status}</span><br><span class="muted">${r.latency_ms==null?'':r.latency_ms+' ms · '}${r.note||''}</span></div>`).join('');
 document.getElementById('commList').innerHTML=html;document.getElementById('commPreview').innerHTML=html||'<div class="muted">No link data.</div>';
}
document.getElementById('taskForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();await Promise.all([refreshTasks(),refreshEvents()])}
document.getElementById('readinessForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/readiness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();refreshReadiness()}
document.getElementById('commForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));if(o.latency_ms==='')o.latency_ms=null;else o.latency_ms=Number(o.latency_ms);await api('/api/comms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();refreshComms()}
document.getElementById('eventForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));o.confidence=Number(o.confidence);o.x=o.x===''?null:Number(o.x);o.y=o.y===''?null:Number(o.y);o.classification='UNCLASSIFIED';o.releasability='INTERNAL';await api('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.confidence.value=1;refreshEvents()}
renderDomains();Promise.all([refreshEvents(),refreshTasks(),refreshReadiness(),refreshComms()]);
setInterval(()=>Promise.all([refreshEvents(),refreshTasks(),refreshReadiness(),refreshComms()]),5000);
</script></body></html>""")
