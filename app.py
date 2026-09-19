from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Literal, Optional
import os
import base64
import re
import html
import json
import httpx
import psycopg
from psycopg.rows import dict_row
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.units import inch
from io import BytesIO

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
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class TrackUpdate(BaseModel):
    track_id: Optional[str] = None
    object_class: Literal["aircraft","helicopter","uas","balloon","satellite","vehicle","vessel","unknown"] = "unknown"
    domain: Domain = "air"
    identification: Literal["friendly","civilian","unknown","suspected"] = "unknown"
    source: str
    latitude: float
    longitude: float
    altitude_ft: Optional[float] = None
    speed_kt: Optional[float] = None
    heading_deg: Optional[float] = None
    confidence: float = 1.0

class ZoneCreate(BaseModel):
    name: str
    zone_type: Literal["restricted","protected","training","hazard","civilian"] = "restricted"
    latitude: float
    longitude: float
    radius_nm: float = 5.0
    min_altitude_ft: Optional[float] = None
    max_altitude_ft: Optional[float] = None
    active: bool = True

class AlertCreate(BaseModel):
    title: str
    severity: Literal["info","warning","critical"] = "warning"
    source: str
    category: Literal["track","zone","communications","readiness","system","other"] = "other"
    related_id: Optional[str] = None
    details: str = ""

class DirectiveCreate(BaseModel):
    title: str
    directive_type: Literal["strategic_directive","request_options","readiness_order","protection_priority","emergency_coordination"] = "strategic_directive"
    recipient: str = "Chief of Defence Forces / High Command"
    priority: Literal["routine","priority","immediate"] = "priority"
    classification: Literal["UNCLASSIFIED","RESTRICTED","CONFIDENTIAL","SECRET"] = "RESTRICTED"
    text: str

class DirectiveStatus(BaseModel):
    status: Literal["issued","acknowledged","planning","returned","approved","executing","complete"]
    note: str = ""
    actor: str = "AUTHORIZED COMMAND"

class CommandMessage(BaseModel):
    recipient: str
    subject: str
    text: str
    classification: Literal["UNCLASSIFIED","RESTRICTED","CONFIDENTIAL","SECRET"] = "RESTRICTED"

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

DATABASE_URL = os.environ.get("DATABASE_URL", "")
UNG_IAM_URL = os.environ.get("UNG_IAM_URL", "").rstrip("/")
UNG_VAULT_URL = os.environ.get("UNG_VAULT_URL", "").rstrip("/")

def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    if not DATABASE_URL:
        return
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS events(
                id BIGSERIAL PRIMARY KEY,
                domain TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                classification TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
                releasability TEXT NOT NULL DEFAULT 'INTERNAL',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                x DOUBLE PRECISION,
                y DOUBLE PRECISION,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                provenance JSONB NOT NULL DEFAULT '{}'::jsonb
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS tracks(
                id BIGSERIAL PRIMARY KEY,
                track_id TEXT UNIQUE NOT NULL,
                object_class TEXT NOT NULL,
                domain TEXT NOT NULL,
                identification TEXT NOT NULL,
                source TEXT NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                altitude_ft DOUBLE PRECISION,
                speed_kt DOUBLE PRECISION,
                heading_deg DOUBLE PRECISION,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS track_history(
                id BIGSERIAL PRIMARY KEY,
                track_id TEXT NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                altitude_ft DOUBLE PRECISION,
                speed_kt DOUBLE PRECISION,
                heading_deg DOUBLE PRECISION,
                observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE INDEX IF NOT EXISTS idx_track_history_track_time ON track_history(track_id, observed_at DESC)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS zones(
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                radius_nm DOUBLE PRECISION NOT NULL DEFAULT 5.0,
                min_altitude_ft DOUBLE PRECISION,
                max_altitude_ft DOUBLE PRECISION,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS tasks(
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                owner TEXT NOT NULL,
                domain TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS readiness(
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS comms(
                id BIGSERIAL PRIMARY KEY,
                link TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS executive_directives(
                id BIGSERIAL PRIMARY KEY,
                directive_no TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                directive_type TEXT NOT NULL,
                recipient TEXT NOT NULL,
                priority TEXT NOT NULL,
                classification TEXT NOT NULL,
                directive_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'issued',
                status_note TEXT NOT NULL DEFAULT '',
                status_actor TEXT,
                issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS command_messages(
                id BIGSERIAL PRIMARY KEY,
                message_no TEXT UNIQUE NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                message_text TEXT NOT NULL,
                classification TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'sent',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS alerts(
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT NOT NULL,
                related_id TEXT,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                acknowledged_by TEXT,
                acknowledged_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS audit_log(
                id BIGSERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute("SELECT COUNT(*) AS n FROM events")
            if cur.fetchone()["n"] == 0:
                cur.execute("""INSERT INTO events(domain,type,title,source,confidence,classification,releasability,x,y,latitude,longitude,provenance)
                               VALUES
                               ('joint','system','NEPTUNE Core online','NEPTUNE',1.0,'UNCLASSIFIED','INTERNAL',31,48,'{"seed":true}'::jsonb),
                               ('civilian','readiness','ICS profile available','NEPTUNE',1.0,'UNCLASSIFIED','INTERNAL',62,29,'{"seed":true}'::jsonb)""")
            cur.execute("SELECT COUNT(*) AS n FROM readiness")
            if cur.fetchone()["n"] == 0:
                cur.execute("""INSERT INTO readiness(name,category,status,note) VALUES
                               ('Core command node','communications','ready','Primary services online'),
                               ('Edge synchronization','other','limited','Standing by for remote nodes')""")
            cur.execute("SELECT COUNT(*) AS n FROM comms")
            if cur.fetchone()["n"] == 0:
                cur.execute("""INSERT INTO comms(link,status,latency_ms,note) VALUES
                               ('Core network','healthy',18,'Nominal'),
                               ('Edge sync','degraded',NULL,'No remote edge peers connected')""")

@app.on_event("startup")
def startup():
    init_db()

def rows(query, params=()):
    if not DATABASE_URL:
        return []
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

def one(query, params=()):
    if not DATABASE_URL:
        return None
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

def audit(action, entity_type, entity_id=None, details=None):
    if not DATABASE_URL:
        return
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO audit_log(action,entity_type,entity_id,details) VALUES(%s,%s,%s,%s::jsonb)",
                        (action, entity_type, str(entity_id) if entity_id is not None else None, json.dumps(details or {})))

DOCUMENT_AGENCIES = {
    "presidential": ("OFFICE OF THE PRESIDENT", "COMMANDER-IN-CHIEF"),
    "defence": ("MINISTRY OF DEFENCE", "UGANDA PEOPLES' DEFENCE FORCES"),
    "updf": ("UGANDA PEOPLES' DEFENCE FORCES", "GENERAL HEADQUARTERS"),
    "nsc": ("NATIONAL SECURITY COUNCIL", "EXECUTIVE SECURITY COORDINATION"),
    "state_house": ("STATE HOUSE", "EXECUTIVE OFFICE"),
    "executive": ("EXECUTIVE OFFICE OF THE PRESIDENT", "NATIONAL COMMAND AUTHORITY"),
    "air": ("UGANDA PEOPLES' DEFENCE FORCES", "AIR FORCE"),
    "land": ("UGANDA PEOPLES' DEFENCE FORCES", "LAND FORCES"),
    "maritime": ("UGANDA PEOPLES' DEFENCE FORCES", "MARITIME / LAKE SECURITY"),
}

def document_agency(key: str):
    return DOCUMENT_AGENCIES.get(key, DOCUMENT_AGENCIES["executive"])

def official_document_html(*, agency_key: str, title: str, reference: str, classification: str,
                           body: str, recipient: str = "", status: str = "", metadata: dict | None = None):
    agency, subagency = document_agency(agency_key)
    meta = metadata or {}
    rows_html = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k,v in meta.items() if v not in (None,"")
    )
    recipient_html = f"<tr><th>Recipient</th><td>{html.escape(recipient)}</td></tr>" if recipient else ""
    status_html = f"<tr><th>Status</th><td>{html.escape(status)}</td></tr>" if status else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(reference)} · {html.escape(title)}</title>
<style>
@page{{margin:18mm 16mm 20mm}}
body{{font-family:Arial,sans-serif;color:#111;background:#fff;margin:0}}
.doc{{max-width:900px;margin:0 auto;padding:28px}}
.hdr{{display:grid;grid-template-columns:90px 1fr 90px;align-items:center;border-bottom:3px solid #111;padding-bottom:14px}}
.hdr img{{width:78px;height:78px;object-fit:contain}}
.gov{{text-align:center;line-height:1.25}}.gov .country{{font:700 15px Georgia;letter-spacing:1.5px}}
.gov .agency{{font-weight:800;font-size:18px;margin-top:4px}}.gov .sub{{font-size:12px;letter-spacing:1px;margin-top:3px}}
.class{{text-align:center;font-weight:900;letter-spacing:1.5px;border:2px solid #111;padding:7px;margin:18px 0}}
h1{{font:700 24px Georgia;margin:18px 0 10px;text-align:center}}table{{width:100%;border-collapse:collapse;margin:14px 0}}
th,td{{border:1px solid #aaa;padding:8px;text-align:left;font-size:12px}}th{{width:190px;background:#f2f2f2}}
.body{{white-space:pre-wrap;line-height:1.55;font-size:14px;min-height:280px;margin-top:18px}}
.footer{{border-top:1px solid #777;margin-top:30px;padding-top:8px;font-size:10px;display:flex;justify-content:space-between}}
.toolbar{{position:fixed;right:18px;top:18px}}button{{padding:9px 12px;font-weight:700}}
@media print{{.toolbar{{display:none}}.doc{{padding:0}}}}
</style></head><body>
<div class="toolbar"><button onclick="window.print()">Print</button> <a href="#" onclick="window.location.href=window.location.pathname+'/pdf';return false;" style="display:inline-block;padding:9px 12px;font-weight:700;background:#eee;color:#111;border-radius:6px;text-decoration:none">Save PDF</a></div>
<div class="doc">
<div class="hdr"><img src="/presidential-seal" alt="Presidential Seal"><div class="gov"><div class="country">REPUBLIC OF UGANDA</div><div class="agency">{html.escape(agency)}</div><div class="sub">{html.escape(subagency)}</div></div><div></div></div>
<div class="class">{html.escape(classification)}</div>
<h1>{html.escape(title)}</h1>
<table><tr><th>Reference / Tracking No.</th><td>{html.escape(reference)}</td></tr>{recipient_html}{status_html}{rows_html}</table>
<div class="body">{html.escape(body)}</div>
<div class="footer"><span>Official NEPTUNE document · Automatically branded</span><span>{html.escape(reference)}</span></div>
</div></body></html>"""

@app.get("/presidential-seal")
def presidential_seal():
    # Reuse the already-approved seal embedded in the NEPTUNE header so every official document is identical.
    page = home().body.decode("utf-8")
    m = re.search(r'class="brand-seal" src="data:image/png;base64,([^"]+)"', page)
    if not m:
        return Response(status_code=404)
    return Response(base64.b64decode(m.group(1)), media_type="image/png", headers={"Cache-Control":"public, max-age=86400"})

@app.get("/api/document-policy")
def document_policy():
    return {
        "mandatory_header":["Presidential Seal","Republic of Uganda","Issuing institution / military branch / executive agency"],
        "mandatory_identity":["document title","reference or tracking number","classification","issuing authority","date/time","recipient","status"],
        "agencies":DOCUMENT_AGENCIES,
        "rule":"All generated, printable, and exported NEPTUNE records use the centralized official document header."
    }

@app.get("/documents/directive/{directive_id}", response_class=HTMLResponse)
def directive_document(directive_id: int):
    d=one("""SELECT id,directive_no,title,directive_type,recipient,priority,classification,directive_text,
                    status,status_actor,issued_at,updated_at FROM executive_directives WHERE id=%s""",(directive_id,))
    if not d:
        return HTMLResponse("Document not found",status_code=404)
    return HTMLResponse(official_document_html(
        agency_key="presidential", title=d["title"], reference=d["directive_no"],
        classification=d["classification"], recipient=d["recipient"], status=d["status"],
        body=d["directive_text"],
        metadata={"Document Type":d["directive_type"].replace("_"," ").title(),
                  "Priority":d["priority"].upper(),"Issued":d["issued_at"],
                  "Last Updated":d["updated_at"],"Status Authority":d["status_actor"] or ""}
    ))

@app.get("/documents/message/{message_id}", response_class=HTMLResponse)
def message_document(message_id: int):
    m=one("""SELECT id,message_no,recipient,subject,message_text,classification,status,created_at
             FROM command_messages WHERE id=%s""",(message_id,))
    if not m:
        return HTMLResponse("Document not found",status_code=404)
    return HTMLResponse(official_document_html(
        agency_key="executive", title=m["subject"], reference=m["message_no"],
        classification=m["classification"], recipient=m["recipient"], status=m["status"],
        body=m["message_text"], metadata={"Document Type":"Secure Command Message","Issued":m["created_at"]}
    ))

@app.get("/documents/task/{task_id}", response_class=HTMLResponse)
def task_document(task_id: int):
    t=one("SELECT id,title,owner,domain,priority,status,created_at,updated_at FROM tasks WHERE id=%s",(task_id,))
    if not t:
        return HTMLResponse("Document not found",status_code=404)
    agency_key=t["domain"] if t["domain"] in ("air","land","maritime") else "updf"
    return HTMLResponse(official_document_html(
        agency_key=agency_key, title=t["title"], reference=f"TASK-{t['id']:06d}",
        classification="RESTRICTED", recipient=t["owner"], status=t["status"],
        body="Operational tasking record generated by UNG-NEPTUNE.",
        metadata={"Domain":t["domain"].upper(),"Priority":t["priority"].upper(),
                  "Created":t["created_at"],"Updated":t["updated_at"]}
    ))

@app.get("/documents/event/{event_id}", response_class=HTMLResponse)
def event_document(event_id: int):
    e=one("""SELECT id,domain,type,title,source,confidence,classification,releasability,created_at,latitude,longitude
             FROM events WHERE id=%s""",(event_id,))
    if not e:
        return HTMLResponse("Document not found",status_code=404)
    agency_key=e["domain"] if e["domain"] in ("air","land","maritime") else "nsc"
    return HTMLResponse(official_document_html(
        agency_key=agency_key, title=e["title"], reference=f"EVT-{e['id']:06d}",
        classification=e["classification"], status="RECORDED",
        body=f"Source: {e['source']}\nEvent type: {e['type']}\nReleasability: {e['releasability']}",
        metadata={"Domain":e["domain"].upper(),"Confidence":f"{round(float(e['confidence'] or 0)*100)}%",
                  "Recorded":e["created_at"],"Latitude":e["latitude"],"Longitude":e["longitude"]}
    ))

@app.get("/documents/readiness/{record_id}", response_class=HTMLResponse)
def readiness_document(record_id: int):
    r=one("SELECT id,name,category,status,note,created_at FROM readiness WHERE id=%s",(record_id,))
    if not r:
        return HTMLResponse("Document not found",status_code=404)
    return HTMLResponse(official_document_html(
        agency_key="updf", title=f"Readiness Report — {r['name']}", reference=f"RDY-{r['id']:06d}",
        classification="RESTRICTED", status=r["status"].upper(), body=r["note"] or "No additional readiness note.",
        metadata={"Category":r["category"].upper(),"Recorded":r["created_at"]}
    ))

@app.get("/documents/comms/{record_id}", response_class=HTMLResponse)
def comms_document(record_id: int):
    r=one("SELECT id,link,status,latency_ms,note,created_at FROM comms WHERE id=%s",(record_id,))
    if not r:
        return HTMLResponse("Document not found",status_code=404)
    return HTMLResponse(official_document_html(
        agency_key="defence", title=f"Communications Status — {r['link']}", reference=f"COM-{r['id']:06d}",
        classification="RESTRICTED", status=r["status"].upper(), body=r["note"] or "No additional communications note.",
        metadata={"Latency":f"{r['latency_ms']} ms" if r["latency_ms"] is not None else "Not reported","Recorded":r["created_at"]}
    ))

@app.get("/documents/alert/{alert_id}", response_class=HTMLResponse)
def alert_document(alert_id: int):
    a=one("""SELECT id,title,severity,source,category,related_id,details,status,acknowledged_by,acknowledged_at,created_at
             FROM alerts WHERE id=%s""",(alert_id,))
    if not a:
        return HTMLResponse("Document not found",status_code=404)
    agency_key="nsc" if a["category"] in ("system","zone","track") else "executive"
    return HTMLResponse(official_document_html(
        agency_key=agency_key, title=a["title"], reference=f"ALT-{a['id']:06d}",
        classification="RESTRICTED", status=a["status"].upper(), body=a["details"] or "No additional alert details.",
        metadata={"Severity":a["severity"].upper(),"Category":a["category"].upper(),"Source":a["source"],
                  "Related ID":a["related_id"] or "","Created":a["created_at"],
                  "Acknowledged By":a["acknowledged_by"] or "","Acknowledged At":a["acknowledged_at"] or ""}
    ))

@app.get("/documents/audit/{audit_id}", response_class=HTMLResponse)
def audit_document(audit_id: int):
    a=one("SELECT id,action,entity_type,entity_id,details,created_at FROM audit_log WHERE id=%s",(audit_id,))
    if not a:
        return HTMLResponse("Document not found",status_code=404)
    return HTMLResponse(official_document_html(
        agency_key="executive", title="Audit & Accountability Record", reference=f"AUD-{a['id']:06d}",
        classification="RESTRICTED", status="RECORDED",
        body=json.dumps(a["details"] or {},indent=2,default=str),
        metadata={"Action":a["action"],"Entity Type":a["entity_type"],"Entity ID":a["entity_id"] or "",
                  "Recorded":a["created_at"]}
    ))

@app.get("/api/documents")
def document_registry():
    docs=[]
    for d in rows("""SELECT id,directive_no AS ref,title,classification,status,issued_at AS created_at
                     FROM executive_directives ORDER BY issued_at DESC LIMIT 100"""):
        docs.append({"kind":"directive","id":d["id"],"reference":d["ref"],"title":d["title"],
                     "classification":d["classification"],"status":d["status"],"created_at":d["created_at"],
                     "agency":"Office of the President / Commander-in-Chief",
                     "url":f"/documents/directive/{d['id']}"})
    for m in rows("""SELECT id,message_no AS ref,subject AS title,classification,status,created_at
                     FROM command_messages ORDER BY created_at DESC LIMIT 100"""):
        docs.append({"kind":"message","id":m["id"],"reference":m["ref"],"title":m["title"],
                     "classification":m["classification"],"status":m["status"],"created_at":m["created_at"],
                     "agency":"Executive Office of the President",
                     "url":f"/documents/message/{m['id']}"})
    for t in rows("""SELECT id,title,domain,status,created_at FROM tasks ORDER BY created_at DESC LIMIT 100"""):
        agency = "UPDF"
        if t["domain"]=="air": agency="UPDF Air Force"
        elif t["domain"]=="land": agency="UPDF Land Forces"
        elif t["domain"]=="maritime": agency="UPDF Maritime / Lake Security"
        docs.append({"kind":"task","id":t["id"],"reference":f"TASK-{t['id']:06d}","title":t["title"],
                     "classification":"RESTRICTED","status":t["status"],"created_at":t["created_at"],
                     "agency":agency,"url":f"/documents/task/{t['id']}"})
    for e in rows("""SELECT id,title,domain,classification,created_at FROM events ORDER BY created_at DESC LIMIT 100"""):
        agency = "National Security Council"
        if e["domain"]=="air": agency="UPDF Air Force"
        elif e["domain"]=="land": agency="UPDF Land Forces"
        elif e["domain"]=="maritime": agency="UPDF Maritime / Lake Security"
        docs.append({"kind":"event","id":e["id"],"reference":f"EVT-{e['id']:06d}","title":e["title"],
                     "classification":e["classification"],"status":"recorded","created_at":e["created_at"],
                     "agency":agency,"url":f"/documents/event/{e['id']}"})
    for r in rows("""SELECT id,name,category,status,created_at FROM readiness ORDER BY created_at DESC LIMIT 100"""):
        docs.append({"kind":"readiness","id":r["id"],"reference":f"RDY-{r['id']:06d}",
                     "title":f"Readiness Report — {r['name']}","classification":"RESTRICTED","status":r["status"],
                     "created_at":r["created_at"],"agency":"Uganda Peoples' Defence Forces",
                     "url":f"/documents/readiness/{r['id']}"})
    for r in rows("""SELECT id,link,status,created_at FROM comms ORDER BY created_at DESC LIMIT 100"""):
        docs.append({"kind":"communications","id":r["id"],"reference":f"COM-{r['id']:06d}",
                     "title":f"Communications Status — {r['link']}","classification":"RESTRICTED","status":r["status"],
                     "created_at":r["created_at"],"agency":"Ministry of Defence / UPDF",
                     "url":f"/documents/comms/{r['id']}"})
    for a in rows("""SELECT id,title,severity,status,created_at FROM alerts ORDER BY created_at DESC LIMIT 100"""):
        docs.append({"kind":"alert","id":a["id"],"reference":f"ALT-{a['id']:06d}","title":a["title"],
                     "classification":"RESTRICTED","status":a["status"],"created_at":a["created_at"],
                     "agency":"National Security Council","url":f"/documents/alert/{a['id']}"})
    for a in rows("""SELECT id,action,entity_type,created_at FROM audit_log ORDER BY created_at DESC LIMIT 100"""):
        docs.append({"kind":"audit","id":a["id"],"reference":f"AUD-{a['id']:06d}",
                     "title":f"Audit Record — {a['action']}","classification":"RESTRICTED","status":"recorded",
                     "created_at":a["created_at"],"agency":"Executive Office of the President",
                     "url":f"/documents/audit/{a['id']}"})
    docs.sort(key=lambda x:x["created_at"], reverse=True)
    return docs[:300]

def _seal_bytes():
    page = home().body.decode("utf-8")
    m = re.search(r'class="brand-seal" src="data:image/png;base64,([^"]+)"', page)
    return base64.b64decode(m.group(1)) if m else None

def build_official_pdf(*, agency_key: str, title: str, reference: str, classification: str,
                       body: str, recipient: str = "", status: str = "", metadata: dict | None = None):
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=LETTER,rightMargin=42,leftMargin=42,topMargin=36,bottomMargin=42)
    styles=getSampleStyleSheet()
    story=[]
    agency,subagency=document_agency(agency_key)

    seal=_seal_bytes()
    if seal:
        seal_img=RLImage(BytesIO(seal),width=0.78*inch,height=0.78*inch)
    else:
        seal_img=Paragraph("",styles["Normal"])

    header_text=Paragraph(
        f"<b>REPUBLIC OF UGANDA</b><br/><font size='14'><b>{html.escape(agency)}</b></font><br/>"
        f"<font size='9'>{html.escape(subagency)}</font>",
        styles["Normal"]
    )
    ht=Table([[seal_img,header_text,""]],colWidths=[0.95*inch,5.7*inch,0.45*inch])
    ht.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(1,0),(1,0),"CENTER"),
        ("LINEBELOW",(0,0),(-1,-1),2,colors.black),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),
    ]))
    story += [ht,Spacer(1,12)]

    class_tbl=Table([[Paragraph(f"<b>{html.escape(classification)}</b>",styles["Normal"])]],colWidths=[7.0*inch])
    class_tbl.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),1.5,colors.black),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
    ]))
    story += [class_tbl,Spacer(1,16),Paragraph(f"<b>{html.escape(title)}</b>",styles["Title"]),Spacer(1,10)]

    data=[["Reference / Tracking No.", reference]]
    if recipient: data.append(["Recipient",recipient])
    if status: data.append(["Status",status])
    for k,v in (metadata or {}).items():
        if v not in (None,""): data.append([str(k),str(v)])
    meta_tbl=Table(data,colWidths=[2.25*inch,4.75*inch],repeatRows=0)
    meta_tbl.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.6,colors.grey),
        ("BACKGROUND",(0,0),(0,-1),colors.whitesmoke),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
    ]))
    story += [meta_tbl,Spacer(1,16)]

    for para in str(body or "").split("\n"):
        story.append(Paragraph(html.escape(para) if para else "&nbsp;",styles["BodyText"]))
        story.append(Spacer(1,4))

    story += [Spacer(1,18),Table([["Official NEPTUNE document · Automatically branded",reference]],colWidths=[5.3*inch,1.7*inch],style=[
        ("LINEABOVE",(0,0),(-1,-1),0.7,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(1,0),(1,0),"RIGHT"),
        ("TOPPADDING",(0,0),(-1,-1),6)
    ])]
    doc.build(story)
    return buf.getvalue()

def _document_payload(kind: str, record_id: int):
    if kind=="directive":
        d=one("""SELECT id,directive_no,title,directive_type,recipient,priority,classification,directive_text,
                        status,status_actor,issued_at,updated_at FROM executive_directives WHERE id=%s""",(record_id,))
        if not d: return None
        return dict(agency_key="presidential",title=d["title"],reference=d["directive_no"],classification=d["classification"],
                    recipient=d["recipient"],status=d["status"],body=d["directive_text"],
                    metadata={"Document Type":d["directive_type"].replace("_"," ").title(),"Priority":d["priority"].upper(),
                              "Issued":d["issued_at"],"Last Updated":d["updated_at"],"Status Authority":d["status_actor"] or ""})
    if kind=="message":
        m=one("""SELECT id,message_no,recipient,subject,message_text,classification,status,created_at
                 FROM command_messages WHERE id=%s""",(record_id,))
        if not m: return None
        return dict(agency_key="executive",title=m["subject"],reference=m["message_no"],classification=m["classification"],
                    recipient=m["recipient"],status=m["status"],body=m["message_text"],
                    metadata={"Document Type":"Secure Command Message","Issued":m["created_at"]})
    if kind=="task":
        t=one("SELECT id,title,owner,domain,priority,status,created_at,updated_at FROM tasks WHERE id=%s",(record_id,))
        if not t: return None
        agency_key=t["domain"] if t["domain"] in ("air","land","maritime") else "updf"
        return dict(agency_key=agency_key,title=t["title"],reference=f"TASK-{t['id']:06d}",classification="RESTRICTED",
                    recipient=t["owner"],status=t["status"],body="Operational tasking record generated by UNG-NEPTUNE.",
                    metadata={"Domain":t["domain"].upper(),"Priority":t["priority"].upper(),"Created":t["created_at"],"Updated":t["updated_at"]})
    if kind=="event":
        e=one("""SELECT id,domain,type,title,source,confidence,classification,releasability,created_at,latitude,longitude
                 FROM events WHERE id=%s""",(record_id,))
        if not e: return None
        agency_key=e["domain"] if e["domain"] in ("air","land","maritime") else "nsc"
        return dict(agency_key=agency_key,title=e["title"],reference=f"EVT-{e['id']:06d}",classification=e["classification"],status="RECORDED",
                    body=f"Source: {e['source']}\nEvent type: {e['type']}\nReleasability: {e['releasability']}",
                    metadata={"Domain":e["domain"].upper(),"Confidence":f"{round(float(e['confidence'] or 0)*100)}%",
                              "Recorded":e["created_at"],"Latitude":e["latitude"],"Longitude":e["longitude"]})
    if kind=="readiness":
        r=one("SELECT id,name,category,status,note,created_at FROM readiness WHERE id=%s",(record_id,))
        if not r:return None
        return dict(agency_key="updf",title=f"Readiness Report — {r['name']}",reference=f"RDY-{r['id']:06d}",classification="RESTRICTED",
                    status=r["status"].upper(),body=r["note"] or "No additional readiness note.",
                    metadata={"Category":r["category"].upper(),"Recorded":r["created_at"]})
    if kind=="comms":
        r=one("SELECT id,link,status,latency_ms,note,created_at FROM comms WHERE id=%s",(record_id,))
        if not r:return None
        return dict(agency_key="defence",title=f"Communications Status — {r['link']}",reference=f"COM-{r['id']:06d}",classification="RESTRICTED",
                    status=r["status"].upper(),body=r["note"] or "No additional communications note.",
                    metadata={"Latency":f"{r['latency_ms']} ms" if r["latency_ms"] is not None else "Not reported","Recorded":r["created_at"]})
    if kind=="alert":
        a=one("""SELECT id,title,severity,source,category,related_id,details,status,acknowledged_by,acknowledged_at,created_at
                 FROM alerts WHERE id=%s""",(record_id,))
        if not a:return None
        agency_key="nsc" if a["category"] in ("system","zone","track") else "executive"
        return dict(agency_key=agency_key,title=a["title"],reference=f"ALT-{a['id']:06d}",classification="RESTRICTED",status=a["status"].upper(),
                    body=a["details"] or "No additional alert details.",
                    metadata={"Severity":a["severity"].upper(),"Category":a["category"].upper(),"Source":a["source"],"Related ID":a["related_id"] or "",
                              "Created":a["created_at"],"Acknowledged By":a["acknowledged_by"] or "","Acknowledged At":a["acknowledged_at"] or ""})
    if kind=="audit":
        a=one("SELECT id,action,entity_type,entity_id,details,created_at FROM audit_log WHERE id=%s",(record_id,))
        if not a:return None
        return dict(agency_key="executive",title="Audit & Accountability Record",reference=f"AUD-{a['id']:06d}",classification="RESTRICTED",
                    status="RECORDED",body=json.dumps(a["details"] or {},indent=2,default=str),
                    metadata={"Action":a["action"],"Entity Type":a["entity_type"],"Entity ID":a["entity_id"] or "","Recorded":a["created_at"]})
    return None

@app.get("/documents/{kind}/{record_id}/pdf")
def document_pdf(kind: str, record_id: int):
    payload=_document_payload(kind,record_id)
    if not payload:
        return Response("Document not found",status_code=404,media_type="text/plain")
    pdf=build_official_pdf(**payload)
    filename=re.sub(r"[^A-Za-z0-9._-]+","_",payload["reference"])+".pdf"
    return Response(pdf,media_type="application/pdf",headers={
        "Content-Disposition":f'attachment; filename="{filename}"',
        "Cache-Control":"no-store, max-age=0"
    })

@app.get("/health")
def health():
    return {"ok": True, "system": "UNG-NEPTUNE", "version": "0.1.0"}

@app.get("/api/events")
def get_events():
    return rows("""SELECT id,domain,type,title,source,confidence,classification,releasability,
                         created_at AS time,x,y,latitude,longitude,provenance
                  FROM events ORDER BY id DESC LIMIT 100""")[::-1]

@app.post("/api/events")
def add_event(event: Event):
    item = event.model_dump()
    if not DATABASE_URL:
        return {"error":"database_unavailable"}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO events(domain,type,title,source,confidence,classification,releasability,x,y,latitude,longitude,provenance)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                           RETURNING id,domain,type,title,source,confidence,classification,releasability,created_at AS time,x,y,latitude,longitude,provenance""",
                        (item["domain"],item["type"],item["title"],item["source"],item["confidence"],item["classification"],item["releasability"],item["x"],item["y"],item["latitude"],item["longitude"],json.dumps({"ingest":"api"})))
            saved=cur.fetchone()
    audit("create","event",saved["id"],{"title":saved["title"],"domain":saved["domain"]})
    return saved

@app.get("/api/tracks")
def get_tracks():
    return rows("""SELECT track_id,object_class,domain,identification,source,latitude,longitude,
                         altitude_ft,speed_kt,heading_deg,confidence,first_seen,last_seen,
                         CASE
                           WHEN last_seen < NOW() - INTERVAL '10 minutes' THEN 'lost'
                           WHEN last_seen < NOW() - INTERVAL '2 minutes' THEN 'stale'
                           ELSE 'live'
                         END AS track_status
                  FROM tracks ORDER BY last_seen DESC""")

@app.post("/api/tracks")
def upsert_track(track: TrackUpdate):
    item = track.model_dump()
    track_id = (item["track_id"] or "").strip().upper()
    if not track_id:
        track_id = "TRK-" + item["domain"].upper()[:3] + "-" + datetime.now(timezone.utc).strftime("%H%M%S%f")[-9:]
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tracks(track_id,object_class,domain,identification,source,latitude,longitude,
                                              altitude_ft,speed_kt,heading_deg,confidence)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(track_id) DO UPDATE SET
                              object_class=EXCLUDED.object_class,
                              domain=EXCLUDED.domain,
                              identification=EXCLUDED.identification,
                              source=EXCLUDED.source,
                              latitude=EXCLUDED.latitude,
                              longitude=EXCLUDED.longitude,
                              altitude_ft=EXCLUDED.altitude_ft,
                              speed_kt=EXCLUDED.speed_kt,
                              heading_deg=EXCLUDED.heading_deg,
                              confidence=EXCLUDED.confidence,
                              last_seen=NOW()
                           RETURNING track_id,object_class,domain,identification,source,latitude,longitude,
                                     altitude_ft,speed_kt,heading_deg,confidence,first_seen,last_seen""",
                        (track_id,item["object_class"],item["domain"],item["identification"],item["source"],
                         item["latitude"],item["longitude"],item["altitude_ft"],item["speed_kt"],item["heading_deg"],item["confidence"]))
            saved=cur.fetchone()
            cur.execute("""INSERT INTO track_history(track_id,latitude,longitude,altitude_ft,speed_kt,heading_deg)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
                        (track_id,item["latitude"],item["longitude"],item["altitude_ft"],item["speed_kt"],item["heading_deg"]))
    audit("track_update","track",track_id,{"source":item["source"],"identification":item["identification"]})
    return saved

@app.get("/api/tracks/{track_id}/history")
def track_history(track_id: str):
    return rows("""SELECT track_id,latitude,longitude,altitude_ft,speed_kt,heading_deg,observed_at
                  FROM track_history WHERE track_id=%s ORDER BY observed_at DESC LIMIT 100""",(track_id.upper(),))[::-1]

@app.get("/api/tracks/{track_id}/prediction")
def track_prediction(track_id: str, minutes: int = 10):
    minutes = max(1, min(60, minutes))
    current = one("""SELECT track_id,latitude,longitude,altitude_ft,speed_kt,heading_deg,last_seen
                     FROM tracks WHERE track_id=%s""",(track_id.upper(),))
    if not current:
        return {"error":"not_found"}
    hist = rows("""SELECT latitude,longitude,altitude_ft,speed_kt,heading_deg,observed_at
                   FROM track_history WHERE track_id=%s ORDER BY observed_at DESC LIMIT 25""",(track_id.upper(),))[::-1]
    speed = float(current["speed_kt"] or 0)
    heading = float(current["heading_deg"] or 0)
    lat = float(current["latitude"])
    lon = float(current["longitude"])
    import math
    distance_nm = speed * (minutes / 60.0)
    heading_rad = math.radians(heading)
    dlat = (distance_nm * math.cos(heading_rad)) / 60.0
    cos_lat = max(0.2, math.cos(math.radians(lat)))
    dlon = (distance_nm * math.sin(heading_rad)) / (60.0 * cos_lat)
    predicted = {"latitude":lat+dlat,"longitude":lon+dlon,"minutes":minutes,"method":"constant_velocity"}
    uncertainty_nm = max(1.0, distance_nm * 0.12)
    return {"track_id":track_id.upper(),"current":current,"history":hist,"predicted":predicted,"uncertainty_nm":uncertainty_nm}

@app.get("/api/deconfliction")
def deconfliction(minutes: int = 15, horizontal_nm: float = 5.0, vertical_ft: float = 1000.0):
    minutes = max(1, min(60, minutes))
    horizontal_nm = max(0.5, min(50.0, horizontal_nm))
    vertical_ft = max(100.0, min(10000.0, vertical_ft))
    tracks = rows("""SELECT track_id,latitude,longitude,altitude_ft,speed_kt,heading_deg,last_seen
                     FROM tracks WHERE last_seen >= NOW() - INTERVAL '10 minutes'""")
    import math

    def velocity(t):
        speed = float(t["speed_kt"] or 0.0) / 60.0  # nm/min
        hdg = math.radians(float(t["heading_deg"] or 0.0))
        return speed * math.sin(hdg), speed * math.cos(hdg)  # east,north

    def xy_nm(lat0, lon0, lat, lon):
        north = (float(lat) - lat0) * 60.0
        east = (float(lon) - lon0) * 60.0 * max(0.2, math.cos(math.radians(lat0)))
        return east, north

    conflicts = []
    for i in range(len(tracks)):
        for j in range(i+1, len(tracks)):
            a,b = tracks[i],tracks[j]
            lat0 = (float(a["latitude"]) + float(b["latitude"])) / 2.0
            lon0 = (float(a["longitude"]) + float(b["longitude"])) / 2.0
            ax,ay = xy_nm(lat0,lon0,a["latitude"],a["longitude"])
            bx,by = xy_nm(lat0,lon0,b["latitude"],b["longitude"])
            avx,avy = velocity(a); bvx,bvy = velocity(b)
            rx,ry = bx-ax, by-ay
            rvx,rvy = bvx-avx, bvy-avy
            rv2 = rvx*rvx + rvy*rvy
            t = 0.0 if rv2 < 1e-9 else max(0.0, min(float(minutes), -(rx*rvx + ry*rvy)/rv2))
            cax,cay = ax+avx*t, ay+avy*t
            cbx,cby = bx+bvx*t, by+bvy*t
            sep = math.hypot(cbx-cax,cby-cay)
            alt_a = float(a["altitude_ft"] or 0.0)
            alt_b = float(b["altitude_ft"] or 0.0)
            v_sep = abs(alt_a-alt_b)
            if sep <= horizontal_nm and v_sep <= vertical_ft:
                midx,midy=(cax+cbx)/2.0,(cay+cby)/2.0
                lat = lat0 + midy/60.0
                lon = lon0 + midx/(60.0*max(0.2,math.cos(math.radians(lat0))))
                conflicts.append({
                    "track_a":a["track_id"],"track_b":b["track_id"],
                    "minutes_to_closest":round(t,1),
                    "horizontal_separation_nm":round(sep,2),
                    "vertical_separation_ft":round(v_sep,0),
                    "latitude":lat,"longitude":lon,
                    "severity":"critical" if sep <= horizontal_nm/2 and v_sep <= vertical_ft/2 else "warning"
                })
    conflicts.sort(key=lambda x:(x["minutes_to_closest"],x["horizontal_separation_nm"]))
    return {"horizon_minutes":minutes,"horizontal_threshold_nm":horizontal_nm,"vertical_threshold_ft":vertical_ft,"conflicts":conflicts}

@app.get("/api/zones")
def get_zones():
    return rows("""SELECT id,name,zone_type,latitude,longitude,radius_nm,min_altitude_ft,max_altitude_ft,active,created_at
                  FROM zones ORDER BY id""")

@app.post("/api/zones")
def add_zone(zone: ZoneCreate):
    item=zone.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO zones(name,zone_type,latitude,longitude,radius_nm,min_altitude_ft,max_altitude_ft,active)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,name,zone_type,latitude,longitude,radius_nm,min_altitude_ft,max_altitude_ft,active,created_at""",
                        (item["name"],item["zone_type"],item["latitude"],item["longitude"],item["radius_nm"],
                         item["min_altitude_ft"],item["max_altitude_ft"],item["active"]))
            saved=cur.fetchone()
    audit("create","zone",saved["id"],{"name":saved["name"],"type":saved["zone_type"]})
    return saved

@app.get("/api/zone-alerts")
def zone_alerts(minutes: int = 15):
    minutes=max(1,min(60,minutes))
    tracks=rows("""SELECT track_id,latitude,longitude,altitude_ft,speed_kt,heading_deg,last_seen
                   FROM tracks WHERE last_seen >= NOW() - INTERVAL '10 minutes'""")
    zones=rows("""SELECT id,name,zone_type,latitude,longitude,radius_nm,min_altitude_ft,max_altitude_ft
                  FROM zones WHERE active=TRUE""")
    import math
    alerts=[]
    for t in tracks:
        speed=float(t["speed_kt"] or 0.0)
        hdg=math.radians(float(t["heading_deg"] or 0.0))
        steps=max(1,minutes)
        for z in zones:
            found=None
            for minute in range(0,steps+1):
                dist_nm=speed*(minute/60.0)
                plat=float(t["latitude"])+(dist_nm*math.cos(hdg))/60.0
                coslat=max(0.2,math.cos(math.radians(float(t["latitude"]))))
                plon=float(t["longitude"])+(dist_nm*math.sin(hdg))/(60.0*coslat)
                dy=(plat-float(z["latitude"]))*60.0
                dx=(plon-float(z["longitude"]))*60.0*max(0.2,math.cos(math.radians(float(z["latitude"]))))
                d=math.hypot(dx,dy)
                alt=float(t["altitude_ft"] or 0.0)
                altitude_ok=(z["min_altitude_ft"] is None or alt>=float(z["min_altitude_ft"])) and (z["max_altitude_ft"] is None or alt<=float(z["max_altitude_ft"]))
                if d<=float(z["radius_nm"]) and altitude_ok:
                    found={"minutes_to_entry":minute,"latitude":plat,"longitude":plon,"distance_nm":round(d,2)}
                    break
            if found:
                alerts.append({"track_id":t["track_id"],"zone_id":z["id"],"zone_name":z["name"],"zone_type":z["zone_type"],**found})
    alerts.sort(key=lambda x:x["minutes_to_entry"])
    return {"horizon_minutes":minutes,"alerts":alerts}

@app.get("/api/alerts")
def get_alerts():
    return rows("""SELECT id,title,severity,source,category,related_id,details,status,
                         acknowledged_by,acknowledged_at,created_at
                  FROM alerts ORDER BY created_at DESC LIMIT 200""")

@app.post("/api/alerts")
def create_alert(alert: AlertCreate):
    item=alert.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO alerts(title,severity,source,category,related_id,details)
                           VALUES(%s,%s,%s,%s,%s,%s)
                           RETURNING id,title,severity,source,category,related_id,details,status,created_at""",
                        (item["title"],item["severity"],item["source"],item["category"],item["related_id"],item["details"]))
            saved=cur.fetchone()
    audit("create","alert",saved["id"],{"severity":saved["severity"],"category":saved["category"]})
    return saved

@app.patch("/api/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: int, actor: str = "operator"):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE alerts SET status='acknowledged',acknowledged_by=%s,acknowledged_at=NOW()
                           WHERE id=%s AND status<>'closed'
                           RETURNING id,title,severity,source,category,related_id,details,status,acknowledged_by,acknowledged_at,created_at""",
                        (actor,alert_id))
            saved=cur.fetchone()
    if not saved:
        return {"error":"not_found"}
    audit("acknowledge","alert",alert_id,{"actor":actor})
    return saved

@app.patch("/api/alerts/{alert_id}/close")
def close_alert(alert_id: int):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE alerts SET status='closed' WHERE id=%s
                           RETURNING id,title,severity,source,category,related_id,details,status,acknowledged_by,acknowledged_at,created_at""",(alert_id,))
            saved=cur.fetchone()
    if not saved:
        return {"error":"not_found"}
    audit("close","alert",alert_id,{})
    return saved

@app.post("/api/alerts/sync-derived")
def sync_derived_alerts():
    created=0
    deconf=deconfliction()
    zones=zone_alerts()
    candidates=[]
    for x in deconf.get("conflicts",[]):
        related=f'{x["track_a"]}:{x["track_b"]}'
        candidates.append({
            "title":f'Deconfliction alert: {x["track_a"]} / {x["track_b"]}',
            "severity":x["severity"],"source":"NEPTUNE-DECONFLICTION","category":"track","related_id":related,
            "details":f'Closest approach in {x["minutes_to_closest"]} min; {x["horizontal_separation_nm"]} NM horizontal; {x["vertical_separation_ft"]} ft vertical'
        })
    for x in zones.get("alerts",[]):
        candidates.append({
            "title":f'Predicted zone entry: {x["track_id"]} → {x["zone_name"]}',
            "severity":"warning","source":"NEPTUNE-ZONES","category":"zone","related_id":f'{x["track_id"]}:{x["zone_id"]}',
            "details":f'Predicted entry in {x["minutes_to_entry"]} min'
        })
    with db() as conn:
        with conn.cursor() as cur:
            for x in candidates:
                cur.execute("""SELECT id FROM alerts
                               WHERE source=%s AND related_id=%s AND status IN ('open','acknowledged')
                               AND created_at > NOW() - INTERVAL '30 minutes'
                               LIMIT 1""",(x["source"],x["related_id"]))
                if cur.fetchone():
                    continue
                cur.execute("""INSERT INTO alerts(title,severity,source,category,related_id,details)
                               VALUES(%s,%s,%s,%s,%s,%s)""",
                            (x["title"],x["severity"],x["source"],x["category"],x["related_id"],x["details"]))
                created+=1
    return {"created":created,"candidates":len(candidates)}

@app.get("/api/executive/directives")
def executive_directives():
    return rows("""SELECT id,directive_no,title,directive_type,recipient,priority,classification,
                         directive_text,status,status_note,status_actor,issued_at,updated_at
                  FROM executive_directives ORDER BY issued_at DESC LIMIT 200""")

@app.post("/api/executive/directives")
def create_executive_directive(body: DirectiveCreate):
    item=body.model_dump()
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    directive_no=f"CIC-{stamp}"
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO executive_directives(
                           directive_no,title,directive_type,recipient,priority,classification,directive_text)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id,directive_no,title,directive_type,recipient,priority,classification,
                                     directive_text,status,status_note,status_actor,issued_at,updated_at""",
                        (directive_no,item["title"],item["directive_type"],item["recipient"],
                         item["priority"],item["classification"],item["text"]))
            saved=cur.fetchone()
    audit("issue","executive_directive",saved["directive_no"],{"title":saved["title"],"recipient":saved["recipient"],"priority":saved["priority"]})
    return saved

@app.patch("/api/executive/directives/{directive_id}")
def update_executive_directive(directive_id: int, body: DirectiveStatus):
    item=body.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE executive_directives
                           SET status=%s,status_note=%s,status_actor=%s,updated_at=NOW()
                           WHERE id=%s
                           RETURNING id,directive_no,title,directive_type,recipient,priority,classification,
                                     directive_text,status,status_note,status_actor,issued_at,updated_at""",
                        (item["status"],item["note"],item["actor"],directive_id))
            saved=cur.fetchone()
    if not saved:
        return {"error":"not_found"}
    audit("status_change","executive_directive",saved["directive_no"],{"status":saved["status"],"actor":item["actor"],"note":item["note"]})
    return saved

@app.get("/api/executive/messages")
def executive_messages():
    return rows("""SELECT id,message_no,recipient,subject,message_text,classification,status,created_at
                  FROM command_messages ORDER BY created_at DESC LIMIT 100""")

@app.post("/api/executive/messages")
def create_command_message(body: CommandMessage):
    item=body.model_dump()
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    message_no=f"CMD-{stamp}"
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO command_messages(message_no,recipient,subject,message_text,classification)
                           VALUES(%s,%s,%s,%s,%s)
                           RETURNING id,message_no,recipient,subject,message_text,classification,status,created_at""",
                        (message_no,item["recipient"],item["subject"],item["text"],item["classification"]))
            saved=cur.fetchone()
    audit("send","command_message",saved["message_no"],{"recipient":saved["recipient"],"subject":saved["subject"]})
    return saved

@app.get("/api/executive/brief")
def executive_brief():
    active_alerts=one("SELECT COUNT(*) AS n FROM alerts WHERE status<>'closed'")
    critical_alerts=one("SELECT COUNT(*) AS n FROM alerts WHERE severity='critical' AND status<>'closed'")
    live_tracks=one("SELECT COUNT(*) AS n FROM tracks WHERE last_seen >= NOW() - INTERVAL '2 minutes'")
    open_tasks=one("SELECT COUNT(*) AS n FROM tasks WHERE status<>'complete'")
    open_directives=one("SELECT COUNT(*) AS n FROM executive_directives WHERE status NOT IN ('complete','returned')")
    return {
        "active_alerts":active_alerts["n"] if active_alerts else 0,
        "critical_alerts":critical_alerts["n"] if critical_alerts else 0,
        "live_tracks":live_tracks["n"] if live_tracks else 0,
        "open_tasks":open_tasks["n"] if open_tasks else 0,
        "open_directives":open_directives["n"] if open_directives else 0,
        "generated_at":datetime.now(timezone.utc)
    }

@app.get("/api/tasks")
def get_tasks():
    return rows("SELECT id,title,owner,domain,priority,status,created_at,updated_at FROM tasks ORDER BY id")

@app.post("/api/tasks")
def add_task(task: Task):
    item=task.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tasks(title,owner,domain,priority,status)
                           VALUES(%s,%s,%s,%s,%s)
                           RETURNING id,title,owner,domain,priority,status,created_at,updated_at""",
                        (item["title"],item["owner"],item["domain"],item["priority"],item["status"]))
            saved=cur.fetchone()
            cur.execute("""INSERT INTO events(domain,type,title,source,confidence,classification,releasability,provenance)
                           VALUES(%s,'task',%s,'COMMAND',1.0,'UNCLASSIFIED','INTERNAL',%s::jsonb)""",
                        (saved["domain"],f'Task created: {saved["title"]}',json.dumps({"task_id":saved["id"]})))
    audit("create","task",saved["id"],{"title":saved["title"],"owner":saved["owner"]})
    return saved

@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, status: Literal["open","in_progress","complete"]):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE tasks SET status=%s,updated_at=NOW() WHERE id=%s
                           RETURNING id,title,owner,domain,priority,status,created_at,updated_at""",(status,task_id))
            saved=cur.fetchone()
    if not saved:
        return {"error":"not_found"}
    audit("update_status","task",task_id,{"status":status})
    return saved

@app.get("/api/readiness")
def get_readiness():
    return rows("SELECT id,name,category,status,note,created_at AS time FROM readiness ORDER BY id")

@app.post("/api/readiness")
def add_readiness(update: ReadinessUpdate):
    item=update.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO readiness(name,category,status,note) VALUES(%s,%s,%s,%s)
                           RETURNING id,name,category,status,note,created_at AS time""",
                        (item["name"],item["category"],item["status"],item["note"]))
            saved=cur.fetchone()
    audit("create","readiness",saved["id"],{"name":saved["name"],"status":saved["status"]})
    return saved

@app.get("/api/comms")
def get_comms():
    return rows("SELECT id,link,status,latency_ms,note,created_at AS time FROM comms ORDER BY id")

@app.post("/api/comms")
def add_comm(update: CommUpdate):
    item=update.model_dump()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO comms(link,status,latency_ms,note) VALUES(%s,%s,%s,%s)
                           RETURNING id,link,status,latency_ms,note,created_at AS time""",
                        (item["link"],item["status"],item["latency_ms"],item["note"]))
            saved=cur.fetchone()
    audit("create","comms",saved["id"],{"link":saved["link"],"status":saved["status"]})
    return saved

@app.get("/api/audit")
def get_audit():
    return rows("SELECT id,action,entity_type,entity_id,details,created_at FROM audit_log ORDER BY id DESC LIMIT 200")

@app.get("/api/integrations")
def integrations():
    result = {}
    for name, url in (("iam", UNG_IAM_URL), ("vault", UNG_VAULT_URL)):
        if not url:
            result[name] = {"configured": False, "online": False}
            continue
        try:
            r = httpx.get(url + "/health", timeout=3.0)
            result[name] = {"configured": True, "online": r.status_code < 400, "status_code": r.status_code, "url": url}
        except Exception:
            result[name] = {"configured": True, "online": False, "url": url}
    return result

CLIENT_JS = r"""
let selectedDomain='joint';
let simulationMode=false;
const domains=['joint','land','air','maritime','space','cyber','civilian'];
let map, mapMarkers=[], trackMarkers=[], trackPathLayers=[], conflictLayers=[], zoneLayers=[], simMarkers=[], simTrails=[];
const simulatedObjects=[
 {id:'SIM-AIR-01',kind:'Aircraft',domain:'air',lat:1.20,lon:32.95,altitude_ft:18500,speed_kt:310,heading:125,status:'training'},
 {id:'SIM-UAS-07',kind:'UAS',domain:'air',lat:0.70,lon:32.40,altitude_ft:6200,speed_kt:95,heading:60,status:'training'},
 {id:'SIM-HELO-03',kind:'Helicopter',domain:'air',lat:0.15,lon:31.95,altitude_ft:2400,speed_kt:120,heading:20,status:'training'},
 {id:'SIM-BAL-02',kind:'Balloon',domain:'air',lat:1.55,lon:33.35,altitude_ft:45000,speed_kt:25,heading:210,status:'training'},
 {id:'SIM-SAT-11',kind:'Satellite',domain:'space',lat:2.10,lon:34.10,altitude_ft:1320000,speed_kt:14500,heading:295,status:'training'}
];
const OFFLINE_KEY='neptune_offline_queue_v1';
function queued(){try{return JSON.parse(localStorage.getItem(OFFLINE_KEY)||'[]')}catch(e){return []}}
function saveQueue(q){localStorage.setItem(OFFLINE_KEY,JSON.stringify(q));document.getElementById('offlineQueue').textContent=q.length+' pending'}
function initMap(){
 map=L.map('map',{zoomControl:true}).setView([0.3476,32.5825],6);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);
}
async function flushOffline(){
 const q=queued(), remaining=[];
 for(const item of q){try{const r=await fetch(item.url,item.opts);if(!r.ok)remaining.push(item)}catch(e){remaining.push(item)}}
 saveQueue(remaining);await Promise.all([refreshEvents(),refreshTracks(),refreshZones(),refreshAlerts(),refreshTasks(),refreshReadiness(),refreshComms()])
}
window.addEventListener('online',flushOffline);
function cls(status){return ['ready','healthy'].includes(status)?'good':['offline'].includes(status)?'bad':'warn'}
async function api(url,opts){
 try{const r=await fetch(url,opts);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
 catch(e){
   if(opts&&opts.method&&opts.method!=='GET'){const q=queued();q.push({url,opts});saveQueue(q);return {queued:true}}
   throw e
 }
}
function showView(id){document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('active',x.dataset.view===id))}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>showView(b.dataset.view));

function renderDomains(){document.getElementById('domains').innerHTML=domains.map(d=>`<button class="${d===selectedDomain?'active':''}" onclick="selectDomain('${d}')">${d==='civilian'?'CIVILIAN ICS':d.toUpperCase()}</button>`).join('')+`<button class="sim-toggle ${simulationMode?'active':''}" onclick="toggleSimulation()">${simulationMode?'SIMULATION ON':'SIMULATION OFF'}</button>`}
function selectDomain(d){selectedDomain=d;document.getElementById('selectedDomain').textContent=d.toUpperCase();document.getElementById('mapTitle').textContent=(d==='joint'?'JOINT':d.toUpperCase())+' COMMON OPERATING PICTURE';renderDomains();refreshEvents();refreshTracks();renderSimulation()}

function simColor(kind){
 if(kind==='Satellite') return '#c27cff';
 if(kind==='Aircraft') return '#5fd7ff';
 if(kind==='UAS') return '#7dff94';
 if(kind==='Helicopter') return '#ffd166';
 return '#ff77c8';
}
function renderSimulation(){
 simMarkers.forEach(m=>map.removeLayer(m));simMarkers=[];
 simTrails.forEach(m=>map.removeLayer(m));simTrails=[];
 document.getElementById('simBadge').classList.toggle('show',simulationMode);
 if(!simulationMode) return;
 const visible=simulatedObjects.filter(o=>selectedDomain==='joint'||o.domain===selectedDomain||(selectedDomain==='space'&&o.kind==='Satellite'));
 visible.forEach(o=>{
   const c=simColor(o.kind);
   const trailLen=o.kind==='Satellite'?2.0:.45;
   const p1=[o.lat,o.lon];
   const p2=[o.lat-(Math.cos(o.heading*Math.PI/180)*trailLen),o.lon-(Math.sin(o.heading*Math.PI/180)*trailLen)];
   const trail=L.polyline([p2,p1],{color:c,weight:2,opacity:.65,dashArray:'6,6'}).addTo(map);simTrails.push(trail);
   const marker=L.circleMarker(p1,{radius:o.kind==='Satellite'?9:7,color:c,fillColor:c,fillOpacity:.75,weight:2}).addTo(map)
     .bindPopup('<b>'+o.id+'</b><br>SIMULATED '+o.kind.toUpperCase()+'<br>Altitude: '+o.altitude_ft.toLocaleString()+' ft<br>Speed: '+o.speed_kt.toLocaleString()+' kt<br>Heading: '+o.heading+'°<br><span style="color:#c27cff">TRAINING / SIMULATION ONLY</span>');
   simMarkers.push(marker);
 });
}
function toggleSimulation(){simulationMode=!simulationMode;renderDomains();renderSimulation()}


async function refreshEvents(){
 const events=await api('/api/events'); const filtered=selectedDomain==='joint'?events:events.filter(e=>e.domain===selectedDomain||e.domain==='joint');
 document.getElementById('eventCount').textContent=events.length+' EVENTS';
 document.getElementById('criticalCount').textContent=events.filter(e=>e.type==='critical').length;
 document.getElementById('eventStream').innerHTML=[...filtered].reverse().slice(0,12).map(e=>`<div class="alert"><b>${e.title}</b><br><span class="muted">${e.domain.toUpperCase()} · ${e.type} · ${e.source}</span></div>`).join('')||'<div class="muted">No events in this domain.</div>';
 document.getElementById('eventLedger').innerHTML=[...events].reverse().slice(0,30).map(e=>`<div class="row"><b>${e.title}</b><br><span class="muted">${e.domain} · ${e.type} · confidence ${Math.round((e.confidence||0)*100)}%</span><br><a class="action mini" target="_blank" href="/documents/event/${e.id}" style="text-decoration:none">Official Document</a></div>`).join('');
 mapMarkers.forEach(m=>map.removeLayer(m));mapMarkers=[];
 filtered.filter(e=>e.latitude!=null&&e.longitude!=null).forEach(e=>{const m=L.circleMarker([e.latitude,e.longitude],{radius:7,weight:2,fillOpacity:.45}).addTo(map).bindPopup('<b>'+e.title+'</b><br>'+e.domain.toUpperCase()+' · '+e.type);mapMarkers.push(m)});
 renderSimulation();
}
function clearTrackPath(){trackPathLayers.forEach(x=>map.removeLayer(x));trackPathLayers=[]}
async function showTrackPath(trackId){
 clearTrackPath();
 const mins=Number(document.getElementById('predictionMinutes').value||10);
 const data=await api('/api/tracks/'+encodeURIComponent(trackId)+'/prediction?minutes='+mins);
 if(data.error)return;
 const hist=(data.history||[]).map(p=>[p.latitude,p.longitude]);
 if(hist.length>1){
   const actual=L.polyline(hist,{color:'#68e39a',weight:3,opacity:.8}).addTo(map).bindTooltip('Observed flight path');
   trackPathLayers.push(actual);
 }
 const c=[data.current.latitude,data.current.longitude];
 const p=[data.predicted.latitude,data.predicted.longitude];
 const predicted=L.polyline([c,p],{color:'#72b7ff',weight:3,opacity:.9,dashArray:'8,7'}).addTo(map).bindTooltip('Predicted flight path · '+mins+' min');
 trackPathLayers.push(predicted);
 const end=L.circleMarker(p,{radius:8,color:'#72b7ff',fillColor:'#72b7ff',fillOpacity:.35,weight:2}).addTo(map)
   .bindPopup('<b>'+data.track_id+'</b><br>Predicted position in '+mins+' min<br>Constant-velocity estimate<br>Uncertainty approx '+Math.round(data.uncertainty_nm)+' NM');
 trackPathLayers.push(end);
 const bounds=L.latLngBounds(hist.length?hist:[c]);bounds.extend(p);map.fitBounds(bounds.pad(.25),{maxZoom:9});
}
async function refreshTracks(){
 const tracks=await api('/api/tracks');
 const visible=selectedDomain==='joint'?tracks:tracks.filter(t=>t.domain===selectedDomain||t.domain==='joint');
 trackMarkers.forEach(m=>map.removeLayer(m));trackMarkers=[];
 visible.forEach(t=>{
   const color=t.track_status==='live'?'#68e39a':t.track_status==='stale'?'#f0d071':'#ff7e7e';
   const m=L.circleMarker([t.latitude,t.longitude],{radius:8,color:color,fillColor:color,fillOpacity:.55,weight:2}).addTo(map)
     .bindPopup('<span class="track-id">'+t.track_id+'</span><br>'+t.object_class.toUpperCase()+' · '+t.identification.toUpperCase()+'<br>'+t.track_status.toUpperCase()+'<br>ALT '+(t.altitude_ft==null?'—':Math.round(t.altitude_ft).toLocaleString()+' ft')+' · SPD '+(t.speed_kt==null?'—':Math.round(t.speed_kt)+' kt')+' · HDG '+(t.heading_deg==null?'—':Math.round(t.heading_deg)+'°')+'<br>Source: '+t.source);
   trackMarkers.push(m);
 });
 document.getElementById('trackList').innerHTML=tracks.length?tracks.map(t=>`<div class="row"><span class="track-id">${t.track_id}</span> <span class="pill track-${t.track_status}">${t.track_status.toUpperCase()}</span><br><b>${t.object_class}</b> · ${t.identification}<br><span class="muted">${t.domain} · ${t.source} · ${t.altitude_ft==null?'ALT —':'ALT '+Math.round(t.altitude_ft).toLocaleString()+' ft'} · ${t.speed_kt==null?'SPD —':'SPD '+Math.round(t.speed_kt)+' kt'}</span><br><button class="action mini" onclick="showTrackPath('${t.track_id}')">Show Flight Path</button></div>`).join(''):'<div class="muted">No live tracks yet.</div>';
}
function clearDeconfliction(){conflictLayers.forEach(x=>map.removeLayer(x));conflictLayers=[]}
async function refreshDeconfliction(){
 clearDeconfliction();
 const mins=Number(document.getElementById('deconfMinutes')?.value||15);
 const h=Number(document.getElementById('deconfHorizontal')?.value||5);
 const v=Number(document.getElementById('deconfVertical')?.value||1000);
 const data=await api('/api/deconfliction?minutes='+mins+'&horizontal_nm='+h+'&vertical_ft='+v);
 const list=(data.conflicts||[]);
 document.getElementById('deconfList').innerHTML=list.length?list.map(x=>`<div class="row"><span class="pill conflict-${x.severity}">${x.severity.toUpperCase()}</span> <span class="track-id">${x.track_a}</span> ↔ <span class="track-id">${x.track_b}</span><br><span class="muted">Closest in ${x.minutes_to_closest} min · horizontal ${x.horizontal_separation_nm} NM · vertical ${Math.round(x.vertical_separation_ft).toLocaleString()} ft</span></div>`).join(''):'<div class="good">No predicted conflicts inside current thresholds.</div>';
 list.forEach(x=>{
   const color=x.severity==='critical'?'#ff6b6b':'#f0d071';
   const m=L.circleMarker([x.latitude,x.longitude],{radius:10,color:color,fillColor:color,fillOpacity:.22,weight:2}).addTo(map)
    .bindPopup('<b>DECONFLICTION POINT</b><br>'+x.track_a+' ↔ '+x.track_b+'<br>Closest approach in '+x.minutes_to_closest+' min<br>'+x.horizontal_separation_nm+' NM horizontal · '+Math.round(x.vertical_separation_ft)+' ft vertical');
   conflictLayers.push(m);
 });
}
async function refreshZones(){
 zoneLayers.forEach(x=>map.removeLayer(x));zoneLayers=[];
 const zones=await api('/api/zones');
 const mins=Number(document.getElementById('zoneMinutes')?.value||15);
 const data=await api('/api/zone-alerts?minutes='+mins);
 zones.forEach(z=>{
   const color=z.zone_type==='hazard'?'#ff8f8f':z.zone_type==='protected'?'#72b7ff':z.zone_type==='training'?'#b38cff':'#f0d071';
   const circle=L.circle([z.latitude,z.longitude],{radius:z.radius_nm*1852,color:color,weight:2,fillOpacity:.08,dashArray:'6,5'}).addTo(map)
    .bindPopup('<b>'+z.name+'</b><br>'+z.zone_type.toUpperCase()+' ZONE<br>Radius '+z.radius_nm+' NM');
   zoneLayers.push(circle);
 });
 document.getElementById('zoneList').innerHTML=zones.length?zones.map(z=>`<div class="row"><b>${z.name}</b> <span class="pill">${z.zone_type}</span><br><span class="muted">Radius ${z.radius_nm} NM · ${z.min_altitude_ft==null?'floor open':'min '+Math.round(z.min_altitude_ft).toLocaleString()+' ft'} · ${z.max_altitude_ft==null?'ceiling open':'max '+Math.round(z.max_altitude_ft).toLocaleString()+' ft'}</span></div>`).join(''):'<div class="muted">No active zones.</div>';
 const alerts=data.alerts||[];
 document.getElementById('zoneAlerts').innerHTML=alerts.length?alerts.map(a=>`<div class="row"><span class="pill conflict-warning">PREDICTED ENTRY</span> <span class="track-id">${a.track_id}</span><br><b>${a.zone_name}</b><br><span class="muted">${a.minutes_to_entry===0?'inside zone now':'entry in '+a.minutes_to_entry+' min'} · ${a.zone_type}</span></div>`).join(''):'<div class="good">No predicted zone incursions in current horizon.</div>';
}
let documentCache=[];
function renderDocuments(){
 const mode=document.getElementById('docFilter')?.value||'all';
 const list=mode==='all'?documentCache:documentCache.filter(d=>d.kind===mode);
 const el=document.getElementById('documentRegistry');
 if(!el)return;
 el.innerHTML=list.length?list.map(d=>`<div class="row"><span class="track-id">${d.reference}</span> <span class="pill">${d.kind.toUpperCase()}</span><br><b>${d.title}</b><br><span class="muted">${d.agency} · ${d.classification} · ${d.status} · ${new Date(d.created_at).toLocaleString()}</span><br><a class="action mini" target="_blank" href="${d.url}" style="text-decoration:none">Open Official Document</a></div>`).join(''):'<div class="muted">No documents in this view.</div>';
}
async function refreshDocuments(){documentCache=await api('/api/documents');renderDocuments()}
let directiveCache=[];
async function refreshExecutive(){
 const [brief,directives,messages]=await Promise.all([api('/api/executive/brief'),api('/api/executive/directives'),api('/api/executive/messages')]);
 directiveCache=directives;
 document.getElementById('execDirectives').textContent=brief.open_directives;
 document.getElementById('execAlerts').textContent=brief.active_alerts;
 document.getElementById('execCritical').textContent=brief.critical_alerts;
 document.getElementById('execTracks').textContent=brief.live_tracks;
 document.getElementById('directiveList').innerHTML=directives.length?directives.map(d=>`<div class="row directive-card directive-${d.status}"><span class="track-id">${d.directive_no}</span> <span class="pill">${d.status.toUpperCase()}</span><br><b>${d.title}</b><br><span class="muted">${d.directive_type.replaceAll('_',' ')} · ${d.priority} · ${d.classification}<br>To: ${d.recipient}</span><br><span class="muted">${d.directive_text}</span><br><div style="margin-top:6px"><a class="action mini" target="_blank" href="/documents/directive/${d.id}" style="text-decoration:none">Official Document</a> ${d.status==='issued'?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'acknowledged\')">Acknowledge</button> ':''}${['issued','acknowledged','planning','returned'].includes(d.status)?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'planning\')">Planning</button> ':''}${['planning','returned'].includes(d.status)?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'approved\')">Approve Plan</button> ':''}${['planning','approved'].includes(d.status)?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'returned\')">Return</button> ':''}${d.status==='approved'?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'executing\')">Execution Status</button> ':''}${d.status==='executing'?'<button class="action mini" onclick="setDirectiveStatus('+d.id+',\'complete\')">Complete</button>':''}</div></div>`).join(''):'<div class="muted">No executive directives yet.</div>';
 document.getElementById('commandMessageList').innerHTML=messages.length?messages.map(m=>`<div class="row"><span class="track-id">${m.message_no}</span><br><b>${m.subject}</b><br><span class="muted">${m.classification} · To: ${m.recipient}</span><br><a class="action mini" target="_blank" href="/documents/message/${m.id}" style="text-decoration:none">Official Document</a></div>`).join(''):'<div class="muted">No command messages yet.</div>';
}
async function setDirectiveStatus(id,status){
 const note=prompt('Status note (optional):','')||'';
 await api('/api/executive/directives/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,note,actor:'AUTHORIZED COMMAND'})});
 refreshExecutive();
}
let alertCache=[];
function renderAlerts(){
 const mode=document.getElementById('alertFilter')?.value||'active';
 let list=alertCache;
 if(mode==='active')list=list.filter(a=>a.status!=='closed');
 if(mode==='critical')list=list.filter(a=>a.severity==='critical'&&a.status!=='closed');
 document.getElementById('alertList').innerHTML=list.length?list.map(a=>`<div class="row alert-open alert-${a.severity} alert-${a.status}"><span class="pill conflict-${a.severity==='critical'?'critical':'warning'}">${a.severity.toUpperCase()}</span> <b>${a.title}</b><br><span class="muted">${a.category} · ${a.source} · ${a.status}${a.related_id?' · '+a.related_id:''}</span><br><span class="muted">${a.details||''}</span><br><a class="action mini" target="_blank" href="/documents/alert/${a.id}" style="text-decoration:none">Official Document</a> ${a.status==='open'?'<button class="action mini" onclick="ackAlert('+a.id+')">Acknowledge</button> ':''}${a.status!=='closed'?'<button class="action mini" onclick="closeAlert('+a.id+')">Close</button>':''}</div>`).join(''):'<div class="good">No alerts in this view.</div>';
 document.getElementById('criticalCount').textContent=alertCache.filter(a=>a.severity==='critical'&&a.status!=='closed').length;
}
async function refreshAlerts(){alertCache=await api('/api/alerts');renderAlerts()}
async function ackAlert(id){await api('/api/alerts/'+id+'/ack?actor=NEPTUNE-OPERATOR',{method:'PATCH'});refreshAlerts()}
async function closeAlert(id){await api('/api/alerts/'+id+'/close',{method:'PATCH'});refreshAlerts()}
async function syncDerivedAlerts(){await api('/api/alerts/sync-derived',{method:'POST'});await refreshAlerts()}
async function refreshTasks(){
 const a=await api('/api/tasks');
 const html=a.length?a.map(t=>`<div class="row"><b>${t.title}</b> <span class="pill">${t.priority}</span><br><span class="muted">${t.owner} · ${t.domain} · ${t.status}</span> <a class="action mini" target="_blank" href="/documents/task/${t.id}" style="text-decoration:none">Document</a> ${t.status!=='complete'?'<button class="action mini" onclick="finishTask('+t.id+')">Complete</button>':''}</div>`).join(''):'<div class="muted">No active command tasks — ready for assignment.</div>';
 document.getElementById('taskList').innerHTML=html;document.getElementById('taskPreview').innerHTML=html;
}
async function finishTask(id){await api('/api/tasks/'+id+'?status=complete',{method:'PATCH'});refreshTasks()}
async function refreshReadiness(){
 const a=await api('/api/readiness');const html=[...a].reverse().map(r=>`<div class="row"><b>${r.name}</b> <span class="${cls(r.status)}">${r.status}</span><br><span class="muted">${r.category} · ${r.note||''}</span><br><a class="action mini" target="_blank" href="/documents/readiness/${r.id}" style="text-decoration:none">Official Document</a></div>`).join('');
 document.getElementById('readinessList').innerHTML=html;document.getElementById('readinessPreview').innerHTML=html||'<div class="muted">No readiness data.</div>';
}
async function refreshComms(){
 const a=await api('/api/comms');const html=[...a].reverse().map(r=>`<div class="row"><b>${r.link}</b> <span class="${cls(r.status)}">${r.status}</span><br><span class="muted">${r.latency_ms==null?'':r.latency_ms+' ms · '}${r.note||''}</span><br><a class="action mini" target="_blank" href="/documents/comms/${r.id}" style="text-decoration:none">Official Document</a></div>`).join('');
 document.getElementById('commList').innerHTML=html;document.getElementById('commPreview').innerHTML=html||'<div class="muted">No link data.</div>';
}
document.getElementById('zoneForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));['latitude','longitude','radius_nm','min_altitude_ft','max_altitude_ft'].forEach(k=>{o[k]=o[k]===''?null:Number(o[k])});o.active=true;await api('/api/zones',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.radius_nm.value=5;await refreshZones()}
document.getElementById('directiveForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/executive/directives',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.recipient.value='Chief of Defence Forces / High Command';e.target.priority.value='priority';e.target.classification.value='RESTRICTED';await refreshExecutive()}
document.getElementById('commandMessageForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/executive/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.recipient.value='Chief of Defence Forces / High Command';e.target.classification.value='RESTRICTED';await refreshExecutive()}
document.getElementById('taskForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();await Promise.all([refreshTasks(),refreshEvents()])}
document.getElementById('readinessForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));await api('/api/readiness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();refreshReadiness()}
document.getElementById('commForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));if(o.latency_ms==='')o.latency_ms=null;else o.latency_ms=Number(o.latency_ms);await api('/api/comms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();refreshComms()}
document.getElementById('trackForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));['latitude','longitude','altitude_ft','speed_kt','heading_deg','confidence'].forEach(k=>{o[k]=o[k]===''?null:Number(o[k])});if(!o.track_id)o.track_id=null;await api('/api/tracks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.confidence.value=1;await refreshTracks()}
document.getElementById('eventForm').onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));o.confidence=Number(o.confidence);o.x=null;o.y=null;o.latitude=o.latitude===''?null:Number(o.latitude);o.longitude=o.longitude===''?null:Number(o.longitude);o.classification='UNCLASSIFIED';o.releasability='INTERNAL';await api('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.confidence.value=1;refreshEvents()}
async function refreshAudit(){
 const a=await api('/api/audit');
 const el=document.getElementById('auditList');
 if(!el)return;
 el.innerHTML=a.length?a.map(x=>`<div class="row"><span class="track-id">AUD-${String(x.id).padStart(6,'0')}</span> <b>${x.action}</b><br><span class="muted">${x.entity_type} · ${x.entity_id||'—'} · ${new Date(x.created_at).toLocaleString()}</span><br><a class="action mini" target="_blank" href="/documents/audit/${x.id}" style="text-decoration:none">Official Document</a></div>`).join(''):'<div class="muted">No audit records yet.</div>';
}
async function refreshIntegrations(){const x=await api('/api/integrations');for(const n of ['iam','vault']){const e=x[n],el=document.getElementById(n+'Status');el.innerHTML=e.online?'<span class="good">ONLINE</span> · connected':'<span class="bad">OFFLINE</span> · '+(e.configured?'configured':'not configured')}}
initMap();renderDomains();renderSimulation();saveQueue(queued());Promise.all([refreshEvents(),refreshTracks(),refreshDeconfliction(),refreshZones(),refreshAlerts(),refreshExecutive(),refreshTasks(),refreshReadiness(),refreshComms(),refreshAudit(),refreshDocuments(),refreshIntegrations()]);flushOffline();
setInterval(()=>Promise.all([refreshEvents(),refreshTracks(),refreshDeconfliction(),refreshAlerts(),refreshExecutive(),refreshTasks(),refreshReadiness(),refreshComms(),refreshAudit(),refreshDocuments(),refreshIntegrations()]),5000);
"""

@app.get("/app.js")
def client_js():
    return Response(
        CLIENT_JS,
        media_type="application/javascript",
        headers={"Cache-Control":"no-store, max-age=0"}
    )

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UNG-NEPTUNE</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{box-sizing:border-box}body{margin:0;background:#07111d;color:#eaf1f7;font-family:Arial,sans-serif}
.top{height:82px;background:linear-gradient(90deg,#071629,#0b3152);border-bottom:2px solid #bda251;display:flex;align-items:center;justify-content:space-between;padding:0 26px}
.brand-wrap{display:flex;align-items:center;gap:14px}.brand-seal{width:64px;height:64px;border-radius:50%;object-fit:cover;border:2px solid #d2b65e;box-shadow:0 0 0 4px rgba(210,182,94,.12);background:#0a1a2b}.brand h1{margin:0;font:28px Georgia}.brand small{color:#d2b65e;letter-spacing:2px}
.status{font-size:12px;color:#9fd6ad;border:1px solid #305748;padding:9px 12px;border-radius:9px;background:#09261d}
.layout{display:grid;grid-template-columns:230px minmax(650px,1fr) 320px;min-height:calc(100vh - 82px)}
aside{background:#091827;border-right:1px solid #20364b;padding:22px 16px}
aside button{display:block;width:100%;text-align:left;color:#dce7f0;background:none;border:0;padding:11px;border-radius:8px;margin-bottom:5px;cursor:pointer}
aside button:hover,aside button.active{background:#103252;color:#f0d071}
main{padding:20px;background:linear-gradient(180deg,rgba(5,18,32,.52) 0,rgba(7,17,29,.96) 520px),url('https://statehouse.go.ug/wp-content/uploads/elementor/thumbs/Statehouse-night-1500x500-2-q9vxq9dyceh2kh2rboi8fllpgxf49dg9zigx1c9uh4.jpeg') center top/100% auto no-repeat}.right{background:#091827e8;border-left:1px solid #20364b;padding:18px}
.executive-hero{min-height:190px;margin:-20px -20px 18px;padding:48px 28px 24px;display:flex;flex-direction:column;justify-content:flex-end;background:linear-gradient(90deg,rgba(5,20,38,.84),rgba(8,31,52,.22));border-bottom:1px solid #bda251}.executive-kicker{font-size:11px;letter-spacing:2.2px;color:#e3c769;font-weight:800}.executive-title{font:700 31px Georgia;color:#fff;margin-top:7px;text-shadow:0 2px 9px #000}.executive-sub{color:#c7d3dd;margin-top:6px}.strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:14px}
.metric,.panel{background:rgba(13,31,49,.92);border:1px solid #294159;border-radius:12px;padding:14px;backdrop-filter:blur(3px)}
.metric b{display:block;font-size:20px;color:#f0d071}.metric span{font-size:11px;color:#9fb2c2}
.map{height:430px;border:1px solid #31506b;border-radius:14px;position:relative;overflow:hidden;background:#0a2034}
.map-title{position:absolute;top:15px;left:50px;color:#e4c76d;background:#07111ddd;padding:7px 10px;border-radius:7px;font:700 12px Arial;letter-spacing:1px;z-index:600}
.leaflet-container{background:#0a2034}.leaflet-control-attribution{font-size:9px}
.domains{display:flex;gap:8px;margin:14px 0;flex-wrap:wrap;align-items:center}.domains button{background:#10283f;color:#dce7f0;border:1px solid #304b64;border-radius:8px;padding:8px 11px;cursor:pointer}.domains button.active{border-color:#d1b45a;color:#f4d577}.sim-toggle{margin-left:auto;border-color:#5b4b88!important}.sim-toggle.active{background:#2a1f49!important;color:#d9c9ff!important;border-color:#9b7be5!important}.sim-badge{position:absolute;top:15px;right:15px;z-index:650;background:#4a245dcc;color:#f3d9ff;border:1px solid #a56ac2;border-radius:7px;padding:6px 9px;font:700 11px Arial;letter-spacing:1px;display:none}.sim-badge.show{display:block}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.panel h3{margin:0 0 10px;color:#f0d071}.row{padding:9px 0;border-bottom:1px solid #23394d;font-size:12px}.muted{color:#91a6b7}
.alert{padding:10px;border:1px solid #30475b;background:#0d2032;border-radius:9px;margin-bottom:9px;font-size:12px}.good{color:#9fd6ad}.warn{color:#f0d071}.bad{color:#ff9b9b}
input,select,textarea{width:100%;background:#07131f;color:#eef3f8;border:1px solid #334a61;border-radius:7px;padding:9px;margin:5px 0 9px}textarea{min-height:70px}
.action{background:#c7a247;color:#07111f;border:0;border-radius:7px;padding:9px 12px;font-weight:800;cursor:pointer}.mini{font-size:11px;padding:6px 8px}
.view{display:none}.view.active{display:block}.toolbar{display:flex;gap:8px;align-items:center;justify-content:space-between}.pill{font-size:10px;border:1px solid #3a5369;border-radius:20px;padding:3px 7px}.track-live{color:#9fd6ad}.track-stale{color:#f0d071}.track-lost{color:#ff9b9b}.track-id{font:700 12px monospace;color:#8fd5ff}.conflict-critical{color:#ff8f8f}.conflict-warning{color:#f0d071}.alert-open{border-left:3px solid #f0d071;padding-left:9px}.alert-critical{border-left-color:#ff6b6b}.alert-acknowledged{opacity:.72}.alert-closed{opacity:.45}.directive-card{border-left:3px solid #d2b65e;padding-left:10px}.directive-issued{border-left-color:#d2b65e}.directive-approved{border-left-color:#68e39a}.directive-returned{border-left-color:#ff8f8f}.directive-complete{opacity:.55}.path-live{color:#68e39a}.path-predicted{color:#72b7ff}.path-muted{color:#9fb2c2}
@media(max-width:900px){body{min-width:1180px}}
</style></head><body>
<div class="top"><div class="brand-wrap"><img class="brand-seal" src="data:image/png;base64,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" alt="Presidential Seal"><div class="brand"><h1>UNG-NEPTUNE</h1><small>FIELD COMMAND MANAGEMENT · COMMON OPERATING PICTURE</small></div></div><div class="status">CORE ONLINE · EDGE READY</div></div>
<div class="layout">
<aside id="nav">
<button class="active" data-view="cop">Joint COP</button><button data-view="executive">Commander-in-Chief</button><button data-view="tracks">Live Tracks</button><button data-view="deconfliction">Deconfliction</button><button data-view="zones">Zones & Incursions</button><button data-view="alerts">Alert Center</button><button data-view="documents">Document Center</button><button data-view="tasks">Command & Tasks</button><button data-view="readiness">Readiness</button><button data-view="logistics">Logistics</button><button data-view="communications">Communications</button><button data-view="incidents">Intel / Incidents</button><button data-view="spectrum">Spectrum Health</button><button data-view="edge">Edge Nodes</button><button data-view="integrations">JANUS / VAULT</button><button data-view="audit">Audit & AAR</button>
</aside>
<main>
<section class="executive-hero"><div class="executive-kicker">REPUBLIC OF UGANDA · EXECUTIVE COMMAND</div><div class="executive-title">SERVICE · SECURITY · NATIONAL READINESS</div><div class="executive-sub">Unified command awareness and resilient national coordination.</div></section>
<div class="strip">
<div class="metric"><b>7</b><span>DOMAIN PROFILES</span></div><div class="metric"><b class="good">ONLINE</b><span>CORE STATUS</span></div><div class="metric"><b id="criticalCount">0</b><span>CRITICAL ALERTS</span></div><div class="metric"><b>100%</b><span>DATA SERVICES</span></div><div class="metric"><b>EDGE</b><span>DEGRADED MODE READY</span></div>
</div>

<section id="cop" class="view active">
<div class="domains" id="domains"></div>
<div class="map" id="map"><div class="map-title" id="mapTitle">JOINT COMMON OPERATING PICTURE</div><div class="sim-badge" id="simBadge">SIMULATION MODE</div></div>
<div class="grid">
<div class="panel"><h3>Command & Task Queue</h3><div id="taskPreview"></div></div>
<div class="panel"><h3>Communications Health</h3><div id="commPreview"></div></div>
<div class="panel"><h3>Readiness</h3><div id="readinessPreview"></div></div>
<div class="panel"><h3>Data Fusion</h3><div class="row">Normalized event bus <span class="good">ready</span></div><div class="row">Provenance & confidence metadata <span class="good">enabled</span></div><div class="row">Selected domain <span id="selectedDomain" class="warn">JOINT</span></div></div>
</div>
</section>

<section id="executive" class="view">
<div class="panel" style="margin-bottom:12px"><div class="toolbar"><div><h3>Commander-in-Chief Console</h3><p class="muted">Strategic command, high-command coordination, national readiness and directive tracking. Tactical weapon control is not exposed here.</p></div><span class="pill">EXECUTIVE COMMAND</span></div>
<div class="grid"><div class="metric"><b id="execDirectives">0</b><span>OPEN DIRECTIVES</span></div><div class="metric"><b id="execAlerts">0</b><span>ACTIVE ALERTS</span></div><div class="metric"><b id="execCritical">0</b><span>CRITICAL ALERTS</span></div><div class="metric"><b id="execTracks">0</b><span>LIVE TRACKS</span></div></div></div>
<div class="grid">
<div class="panel"><h3>Issue Strategic Directive</h3><form id="directiveForm">
<input name="title" placeholder="Directive title" required>
<select name="directive_type"><option value="strategic_directive">Strategic Directive</option><option value="request_options">Request Military Options</option><option value="readiness_order">Readiness Order</option><option value="protection_priority">Protection Priority</option><option value="emergency_coordination">Emergency Coordination</option></select>
<input name="recipient" value="Chief of Defence Forces / High Command" placeholder="Recipient" required>
<select name="priority"><option>routine</option><option selected>priority</option><option>immediate</option></select>
<select name="classification"><option>UNCLASSIFIED</option><option selected>RESTRICTED</option><option>CONFIDENTIAL</option><option>SECRET</option></select>
<textarea name="text" placeholder="Strategic intent / directive. Operational execution remains with the command chain." required></textarea>
<button class="action">Issue Directive</button></form></div>
<div class="panel"><h3>High Command Directive Queue</h3><div id="directiveList"></div></div>
</div>
<div class="grid">
<div class="panel"><h3>Secure Command Message</h3><form id="commandMessageForm">
<input name="recipient" value="Chief of Defence Forces / High Command" placeholder="Recipient" required>
<input name="subject" placeholder="Subject" required>
<select name="classification"><option>UNCLASSIFIED</option><option selected>RESTRICTED</option><option>CONFIDENTIAL</option><option>SECRET</option></select>
<textarea name="text" placeholder="Command coordination message" required></textarea>
<button class="action">Send Command Message</button></form></div>
<div class="panel"><h3>Recent Command Messages</h3><div id="commandMessageList"></div></div>
</div>
</section>

<section id="tracks" class="view"><div class="grid">
<div class="panel"><h3>Post / Update Track</h3><form id="trackForm">
<input name="track_id" placeholder="Track ID (optional — auto generated)">
<select name="object_class"><option>aircraft</option><option>helicopter</option><option>uas</option><option>balloon</option><option>satellite</option><option>vehicle</option><option>vessel</option><option selected>unknown</option></select>
<select name="domain"><option>air</option><option>land</option><option>maritime</option><option>space</option><option>joint</option></select>
<select name="identification"><option>friendly</option><option>civilian</option><option selected>unknown</option><option>suspected</option></select>
<input name="source" placeholder="Track source" required>
<input name="latitude" type="number" min="-90" max="90" step=".000001" placeholder="Latitude" required>
<input name="longitude" type="number" min="-180" max="180" step=".000001" placeholder="Longitude" required>
<input name="altitude_ft" type="number" step="1" placeholder="Altitude ft">
<input name="speed_kt" type="number" step=".1" placeholder="Speed kt">
<input name="heading_deg" type="number" min="0" max="359.9" step=".1" placeholder="Heading degrees">
<input name="confidence" type="number" min="0" max="1" step=".05" value="1">
<button class="action">Save Track Update</button></form></div>
<div class="panel"><h3>Track Directory</h3><div style="display:flex;gap:8px;margin-bottom:10px"><select id="predictionMinutes" style="max-width:150px"><option value="5">5 min prediction</option><option value="10" selected>10 min prediction</option><option value="20">20 min prediction</option><option value="30">30 min prediction</option></select><button type="button" class="action mini" onclick="clearTrackPath()">Clear Path</button></div><div id="trackList"></div></div></div></section>

<section id="deconfliction" class="view"><div class="grid">
<div class="panel"><h3>Airspace Deconfliction</h3><p class="muted">Predicts closest approach between active tracks for collision/conflict awareness. This is not a targeting or engagement tool.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<select id="deconfMinutes" style="max-width:160px"><option value="5">5 min horizon</option><option value="15" selected>15 min horizon</option><option value="30">30 min horizon</option></select>
<input id="deconfHorizontal" type="number" min=".5" max="50" step=".5" value="5" style="max-width:140px" placeholder="Horizontal NM">
<input id="deconfVertical" type="number" min="100" max="10000" step="100" value="1000" style="max-width:140px" placeholder="Vertical ft">
<button class="action mini" onclick="refreshDeconfliction()">Recalculate</button></div></div>
<div class="panel"><h3>Conflict Alerts</h3><div id="deconfList"></div></div></div></section>

<section id="zones" class="view"><div class="grid">
<div class="panel"><h3>Create Airspace / Safety Zone</h3><form id="zoneForm">
<input name="name" placeholder="Zone name" required>
<select name="zone_type"><option>restricted</option><option>protected</option><option>training</option><option>hazard</option><option>civilian</option></select>
<input name="latitude" type="number" min="-90" max="90" step=".000001" placeholder="Center latitude" required>
<input name="longitude" type="number" min="-180" max="180" step=".000001" placeholder="Center longitude" required>
<input name="radius_nm" type="number" min=".5" max="200" step=".5" value="5" placeholder="Radius NM">
<input name="min_altitude_ft" type="number" step="100" placeholder="Minimum altitude ft (optional)">
<input name="max_altitude_ft" type="number" step="100" placeholder="Maximum altitude ft (optional)">
<button class="action">Create Zone</button></form></div>
<div class="panel"><h3>Predicted Zone Incursions</h3><div style="display:flex;gap:8px;margin-bottom:10px"><select id="zoneMinutes" style="max-width:160px"><option value="5">5 min horizon</option><option value="15" selected>15 min horizon</option><option value="30">30 min horizon</option></select><button class="action mini" onclick="refreshZones()">Recalculate</button></div><div id="zoneAlerts"></div><h3 style="margin-top:16px">Active Zones</h3><div id="zoneList"></div></div></div></section>

<section id="alerts" class="view"><div class="grid">
<div class="panel"><h3>Operational Alert Center</h3><p class="muted">Persistent alerts from deconfliction, zone-entry prediction, communications, readiness, and operator reports.</p>
<button class="action" onclick="syncDerivedAlerts()">Sync Derived Alerts</button>
<div style="margin-top:12px"><select id="alertFilter" onchange="renderAlerts()"><option value="active">Active alerts</option><option value="all">All alerts</option><option value="critical">Critical only</option></select></div></div>
<div class="panel"><h3>Alert Queue</h3><div id="alertList"></div></div></div></section>

<section id="documents" class="view"><div class="grid">
<div class="panel"><h3>Official Document Standard</h3>
<div class="row"><b>Presidential Seal</b><br><span class="good">Mandatory on every official document</span></div>
<div class="row"><b>Institution Header</b><br><span class="muted">Automatically selected from Office of the President, Ministry of Defence, UPDF, National Security Council, State House, Executive Office, or military branch.</span></div>
<div class="row"><b>Document Identity</b><br><span class="muted">Tracking number · classification · recipient · status · timestamps · issuing authority</span></div>
<div class="row"><b>Output</b><br><span class="muted">Official print view with Print / Save PDF.</span></div>
<div class="row"><b>Automatic Registry</b><br><span class="good">Every generated record is indexed by tracking number and issuing authority.</span></div>
</div>
<div class="panel"><h3>Agency / Branch Mapping</h3>
<div class="row"><b>Presidential Directives</b><br><span class="muted">Office of the President · Commander-in-Chief</span></div>
<div class="row"><b>Military Command / Comms</b><br><span class="muted">Ministry of Defence · Uganda Peoples' Defence Forces</span></div>
<div class="row"><b>Air / Land / Maritime Records</b><br><span class="muted">UPDF · relevant branch</span></div>
<div class="row"><b>Security / Incident Records</b><br><span class="muted">National Security Council</span></div>
<div class="row"><b>Executive Messages</b><br><span class="muted">Executive Office of the President</span></div>
</div></div>
<div class="panel" style="margin-top:12px"><div class="toolbar"><h3>Official Document Registry</h3><select id="docFilter" onchange="renderDocuments()" style="max-width:180px"><option value="all">All documents</option><option value="directive">Directives</option><option value="message">Messages</option><option value="task">Tasks</option><option value="event">Events</option><option value="readiness">Readiness</option><option value="communications">Communications</option><option value="alert">Alerts</option><option value="audit">Audit</option></select></div><div id="documentRegistry"></div></div>
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
<div class="panel"><h3>Post Operational Event</h3><form id="eventForm"><input name="title" placeholder="Event / incident title" required><input name="source" placeholder="Source" required><select name="domain"><option>joint</option><option>land</option><option>air</option><option>maritime</option><option>space</option><option>cyber</option><option>civilian</option></select><input name="type" placeholder="Type (incident, weather, sensor...)" value="incident"><input name="confidence" type="number" min="0" max="1" step=".05" value="1"><input name="latitude" type="number" min="-90" max="90" step=".000001" placeholder="Latitude"><input name="longitude" type="number" min="-180" max="180" step=".000001" placeholder="Longitude"><button class="action">Publish Event</button></form></div>
<div class="panel"><h3>Event Ledger</h3><div id="eventLedger"></div></div></div></section>

<section id="logistics" class="view"><div class="panel"><h3>Logistics</h3><p class="muted">Resource readiness and sustainment records plug into the same readiness API. Use the Readiness workspace with category <b>logistics</b>.</p></div></section>
<section id="spectrum" class="view"><div class="panel"><h3>Spectrum Health</h3><p class="muted">Connectivity health, congestion, interference reports, and communications planning will appear here. Offensive electronic attack functions are not part of NEPTUNE.</p></div></section>
<section id="edge" class="view"><div class="panel"><h3>Edge Nodes</h3><div class="row"><span class="good">Core node online</span></div><div class="row">Offline queue <span id="offlineQueue" class="good">0 pending</span></div><div class="row">Store-and-forward <span class="good">enabled in browser client</span></div><button class="action" onclick="flushOffline()">Sync Pending Updates</button></div></section>
<section id="integrations" class="view"><div class="grid"><div class="panel"><h3>JANUS / IAM</h3><div id="iamStatus" class="row">Checking...</div><a class="action" style="display:inline-block;text-decoration:none" href="https://ung-iam-production.up.railway.app" target="_blank">Open Identity Management</a></div><div class="panel"><h3>VAULT</h3><div id="vaultStatus" class="row">Checking...</div><a class="action" style="display:inline-block;text-decoration:none" href="https://ung-vault-production.up.railway.app" target="_blank">Open VAULT</a></div></div></section>
<section id="audit" class="view"><div class="panel"><h3>Audit & After-Action Review</h3><p class="muted">Persistent accountability records for operational and executive actions.</p><div id="auditList"></div></div></section>
</main>

<div class="right"><div class="toolbar"><h3 style="color:#f0d071">Live Event Stream</h3><span class="pill" id="eventCount">0 EVENTS</span></div><div id="eventStream"></div><h3 style="color:#f0d071;margin-top:24px">Design Rules</h3><div class="alert">Human authorization required for high-consequence actions.</div><div class="alert">MOSA / open API architecture.</div><div class="alert">Zero-trust / MLS-ready data labels.</div></div><script src="/app.js" defer></script>
</body></html>""", headers={"Cache-Control":"no-store, max-age=0, must-revalidate"})
