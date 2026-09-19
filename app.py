from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Literal

app = FastAPI(title="UNG-NEPTUNE", version="0.1.0")

class Event(BaseModel):
    domain: Literal["land","air","maritime","space","cyber","joint","civilian"]
    type: str
    title: str
    source: str
    confidence: float = 1.0
    classification: str = "UNCLASSIFIED"
    releasability: str = "INTERNAL"

EVENTS = [
    {"domain":"joint","type":"system","title":"NEPTUNE Core online","source":"NEPTUNE","confidence":1.0,"classification":"UNCLASSIFIED","releasability":"INTERNAL","time":"now"},
    {"domain":"civilian","type":"readiness","title":"ICS profile available","source":"NEPTUNE","confidence":1.0,"classification":"UNCLASSIFIED","releasability":"INTERNAL","time":"now"},
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
    item["time"] = datetime.now(timezone.utc).isoformat()
    EVENTS.append(item)
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
.layout{display:grid;grid-template-columns:230px 1fr 300px;min-height:calc(100vh - 82px)}
aside{background:#091827;border-right:1px solid #20364b;padding:22px 16px}
aside a{display:block;color:#dce7f0;text-decoration:none;padding:11px;border-radius:8px;margin-bottom:5px}
aside a:hover{background:#103252;color:#f0d071}
main{padding:20px}
.right{background:#091827;border-left:1px solid #20364b;padding:18px}
.strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:14px}
.metric,.panel{background:#0d1f31;border:1px solid #294159;border-radius:12px;padding:14px}
.metric b{display:block;font-size:20px;color:#f0d071}.metric span{font-size:11px;color:#9fb2c2}
.map{height:430px;background:
linear-gradient(#ffffff0b 1px,transparent 1px),
linear-gradient(90deg,#ffffff0b 1px,transparent 1px),
radial-gradient(circle at 40% 45%,#17486c,#0a2034 58%,#071421);
background-size:32px 32px,32px 32px,auto;border:1px solid #31506b;border-radius:14px;position:relative;overflow:hidden}
.map:before{content:"JOINT COMMON OPERATING PICTURE";position:absolute;top:15px;left:17px;color:#e4c76d;font:700 12px Arial;letter-spacing:1px}
.marker{position:absolute;width:12px;height:12px;border:2px solid #d6bd69;border-radius:50%;box-shadow:0 0 0 6px #d6bd6920}
.m1{left:31%;top:48%}.m2{left:62%;top:29%}.m3{left:71%;top:66%}
.domains{display:flex;gap:8px;margin:14px 0}.domains button{background:#10283f;color:#dce7f0;border:1px solid #304b64;border-radius:8px;padding:8px 11px}
.domains button:first-child{border-color:#d1b45a;color:#f4d577}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
.panel h3{margin:0 0 10px;color:#f0d071}.row{padding:9px 0;border-bottom:1px solid #23394d;font-size:12px}.muted{color:#91a6b7}
.alert{padding:10px;border:1px solid #30475b;background:#0d2032;border-radius:9px;margin-bottom:9px;font-size:12px}
.good{color:#9fd6ad}.warn{color:#f0d071}
</style></head><body>
<div class="top"><div class="brand"><h1>UNG-NEPTUNE</h1><small>FIELD COMMAND MANAGEMENT · COMMON OPERATING PICTURE</small></div><div class="status">CORE ONLINE · EDGE READY</div></div>
<div class="layout">
<aside>
<a href="#">Joint COP</a><a href="#">Command & Tasks</a><a href="#">Readiness</a><a href="#">Logistics</a><a href="#">Communications</a><a href="#">Intel / Incidents</a><a href="#">Spectrum Health</a><a href="#">Edge Nodes</a><a href="#">Audit & AAR</a>
</aside>
<main>
<div class="strip">
<div class="metric"><b>6</b><span>DOMAINS AVAILABLE</span></div>
<div class="metric"><b class="good">ONLINE</b><span>CORE STATUS</span></div>
<div class="metric"><b>0</b><span>CRITICAL ALERTS</span></div>
<div class="metric"><b>100%</b><span>DATA SERVICES</span></div>
<div class="metric"><b>EDGE</b><span>DEGRADED MODE READY</span></div>
</div>
<div class="domains"><button>JOINT</button><button>LAND</button><button>AIR</button><button>MARITIME</button><button>SPACE</button><button>CYBER</button><button>CIVILIAN ICS</button></div>
<div class="map"><span class="marker m1"></span><span class="marker m2"></span><span class="marker m3"></span></div>
<div class="grid">
<div class="panel"><h3>Command & Task Queue</h3><div class="row">No active command tasks <span class="muted">— ready for assignment</span></div></div>
<div class="panel"><h3>Communications Health</h3><div class="row"><span class="good">Core network healthy</span></div><div class="row">Edge sync <span class="muted">standing by</span></div></div>
<div class="panel"><h3>Readiness</h3><div class="row">Personnel / team readiness <span class="muted">not yet populated</span></div><div class="row">Logistics readiness <span class="muted">not yet populated</span></div></div>
<div class="panel"><h3>Data Fusion</h3><div class="row">Normalized event bus <span class="good">ready</span></div><div class="row">Provenance & confidence metadata <span class="good">enabled</span></div></div>
</div>
</main>
<div class="right"><h3 style="color:#f0d071">Live Event Stream</h3><div class="alert"><b>NEPTUNE Core online</b><br><span class="muted">JOINT · system</span></div><div class="alert"><b>ICS profile available</b><br><span class="muted">CIVILIAN · readiness</span></div><h3 style="color:#f0d071;margin-top:24px">Design Rules</h3><div class="alert">Human authorization required for high-consequence actions.</div><div class="alert">MOSA / open API architecture.</div><div class="alert">Zero-trust / MLS-ready data labels.</div></div>
</div></body></html>""")
