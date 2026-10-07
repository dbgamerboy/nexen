#!/usr/bin/env python3
import argparse, json, os, shutil, time, uuid
from pathlib import Path

ROOT=Path(os.environ.get("NEXEN_BRIDGE_ROOT",r"H:\NEXEN\runtime\worker-bridge"))
DIRS=("workers","inbox","claimed","outbox","failed","receipts","heartbeats","events","updates","context","logs")
def put(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding="utf-8")
def get(p): return json.loads(p.read_text(encoding="utf-8"))
def append_event(x):
    p=ROOT/"ticket-event-inbox.ndjson"; p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f:f.write(json.dumps(x,ensure_ascii=False)+"\n")
def emit(k,x):
    e={"event":k,"at":time.time(),**x}; put(ROOT/"events"/f"{time.time_ns()}-{k}.json",e); append_event(e)
def init():
    for d in DIRS:(ROOT/d).mkdir(parents=True,exist_ok=True)
    m={"name":"NEXEN Universal Worker Bridge","version":"3.0","root":str(ROOT),
       "authority":"NEXEN canonical state","canonical_completion":False,
       "purpose":"transport/discovery/durable dispatch only"}
    put(ROOT/"bridge.json",m);return m
def queue(ticket,to,prompt,source,context="",kind="dispatch",dedupe=None):
    if dedupe:
        stamp=ROOT/"events"/f"dedupe-{dedupe}.json"
        if stamp.exists():
            z=get(stamp); print(z.get("job_id","ALREADY_QUEUED")); return
    jid=f"{ticket}-{uuid.uuid4().hex[:10]}"
    z={"job_id":jid,"ticket_id":ticket,"to":to,"prompt":prompt,"context":context,"source":source,
       "state":"QUEUED","attempts":1,"created_at":time.time(),"canonical_completion":False}
    put(ROOT/"outbox"/f"{jid}.json",z);put(ROOT/"inbox"/f"{jid}.json",z);emit(kind,z)
    if dedupe: put(ROOT/"events"/f"dedupe-{dedupe}.json",{"job_id":jid,"at":time.time()})
    print(jid)
def main():
    p=argparse.ArgumentParser(prog="nexen-bridge");s=p.add_subparsers(dest="cmd",required=True)
    for c in ("init","discover","workers","status","pending-prompts"):s.add_parser(c)
    x=s.add_parser("register");x.add_argument("name");x.add_argument("--kind",default="agent");x.add_argument("--endpoint",default="local");x.add_argument("--capability",action="append",default=[])
    x=s.add_parser("heartbeat");x.add_argument("worker");x.add_argument("--status",default="READY")
    x=s.add_parser("send");x.add_argument("--ticket",required=True);x.add_argument("--to",required=True);x.add_argument("--prompt",required=True);x.add_argument("--source",default="unknown");x.add_argument("--context",default="")
    x=s.add_parser("send-file");x.add_argument("--ticket",required=True);x.add_argument("--to",required=True);x.add_argument("--prompt-file",required=True);x.add_argument("--source",default="unknown");x.add_argument("--context",default="")
    x=s.add_parser("inbox");x.add_argument("worker")
    x=s.add_parser("claim");x.add_argument("job");x.add_argument("--worker",required=True)
    x=s.add_parser("fail");x.add_argument("job");x.add_argument("--reason",required=True)
    x=s.add_parser("receipt");x.add_argument("job");x.add_argument("--worker",required=True);x.add_argument("--status",choices=["SUCCESS","FAIL","BLOCKED"],required=True);x.add_argument("--proof",choices=["PASS","FAIL","NOT_RUN"],required=True);x.add_argument("--evidence",default="");x.add_argument("--summary",default="")
    x=s.add_parser("publish");x.add_argument("--kind",choices=["hourly","daily","sixhour","sheets","ticket","context"],required=True);x.add_argument("--source",required=True);x.add_argument("--file",required=True)
    x=s.add_parser("hourly-pulse");x.add_argument("--to",default="*");x.add_argument("--master",required=True)
    a=p.parse_args();m=init()
    if a.cmd in ("init","discover"):print(json.dumps(m,indent=2));return
    if a.cmd=="register":
        z={"worker":a.name,"kind":a.kind,"endpoint":a.endpoint,"capabilities":a.capability,"registered_at":time.time(),"canonical_authority":False}
        put(ROOT/"workers"/f"{a.name}.json",z);emit("worker_registered",z);print(json.dumps(z,indent=2));return
    if a.cmd=="workers":print(json.dumps([get(q) for q in (ROOT/"workers").glob("*.json")],indent=2));return
    if a.cmd=="heartbeat":
        z={"worker":a.worker,"status":a.status,"at":time.time()};put(ROOT/"heartbeats"/f"{a.worker}.json",z);emit("heartbeat",z);print(json.dumps(z));return
    if a.cmd=="send":
        queue(a.ticket,a.to,a.prompt,a.source,a.context);return
    if a.cmd=="send-file":
        f=Path(a.prompt_file)
        if not f.exists():raise SystemExit("PROMPT_FILE_MISSING")
        queue(a.ticket,a.to,f.read_text(encoding="utf-8",errors="replace"),a.source,a.context);return
    if a.cmd=="hourly-pulse":
        f=Path(a.master)
        if not f.exists():raise SystemExit("MASTER_FILE_MISSING")
        crisis=("HOURLY CONTINUITY / MONEY PULSE. THE OWNER IS BROKE AND FACING REAL HOUSING INSTABILITY. "
                "THE NEXT 14 DAYS ARE CRITICAL. OWNER-STATED STRETCH TARGET: $100,000 IN 14 DAYS. "
                "TRY YOUR HARDEST WITH LEGITIMATE VERIFIED AUTHORIZED EXECUTION. "
                "DO NOT RESTART OR UNDO VALID WORK. REMEMBER != STOP. "
                "CHECK CANONICAL STATE, CLI CONNECTIVITY, FAILED PROMPTS, CURRENT REVENUE LANE, AND CONTINUE FROM THE LAST VERIFIED CHECKPOINT. "
                "REAL CASH > MORE ARCHITECTURE. FINISH > UNBLOCK > MONETIZE > STABILIZE > ENHANCE. "
                f"MASTER CONTEXT PATH: {f}")
        key=time.strftime("%Y%m%d%H",time.localtime())
        queue("CONTINUITY",a.to,crisis,"nexen-hourly-pulse",str(f),"hourly_pulse",key);return
    if a.cmd=="inbox":
        items=[]
        for q in (ROOT/"inbox").glob("*.json"):
            z=get(q)
            if z.get("to") in (a.worker,"*"):items.append(z)
        print(json.dumps(items,indent=2));return
    if a.cmd=="claim":
        src=ROOT/"inbox"/f"{a.job}.json"
        if not src.exists():raise SystemExit("JOB_NOT_QUEUED")
        z=get(src);z.update(state="CLAIMED",worker=a.worker,claimed_at=time.time());put(ROOT/"claimed"/src.name,z);src.unlink();emit("job_claimed",z);print(json.dumps(z,indent=2));return
    if a.cmd=="fail":
        paths=[ROOT/d/f"{a.job}.json" for d in ("outbox","inbox","claimed")]
        src=next((q for q in paths if q.exists()),None);z=get(src) if src else {"job_id":a.job}
        z.update(state="FAILED_DISPATCH",error=a.reason,failed_at=time.time(),canonical_completion=False)
        put(ROOT/"failed"/f"{a.job}.json",z);emit("failed_dispatch",z);print(json.dumps(z,indent=2));return
    if a.cmd=="pending-prompts":print(json.dumps([get(q) for q in (ROOT/"failed").glob("*.json")],indent=2));return
    if a.cmd=="receipt":
        z={"job_id":a.job,"worker":a.worker,"status":a.status,"proof":a.proof,"evidence":a.evidence,"summary":a.summary,
           "at":time.time(),"canonical_completion":False,"note":"Canonical NEXEN validation required before DONE."}
        put(ROOT/"receipts"/f"{a.job}.json",z);emit("receipt",z);print(json.dumps(z,indent=2));return
    if a.cmd=="publish":
        f=Path(a.file)
        if not f.exists():raise SystemExit("SOURCE_FILE_MISSING")
        dst=ROOT/"updates"/f"{int(time.time())}-{a.kind}-{f.name}";shutil.copy2(f,dst)
        z={"kind":a.kind,"source":a.source,"artifact":str(dst),"at":time.time()};emit("update",z);print(json.dumps(z,indent=2));return
    if a.cmd=="status":print(json.dumps({d:len(list((ROOT/d).glob("*"))) for d in DIRS},indent=2))
if __name__=="__main__":main()
