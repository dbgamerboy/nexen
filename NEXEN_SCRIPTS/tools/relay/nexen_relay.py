#!/usr/bin/env python3
import argparse, json, os, time, uuid, shutil, subprocess
from pathlib import Path

ROOT = Path(os.environ.get("NEXEN_BRIDGE_ROOT", r"H:\NEXEN\runtime\worker-bridge"))
DIRS = ("workers","inbox","claimed","outbox","failed","receipts","heartbeats","events","updates","context","logs")
KNOWN = ("hermes","marvin","claude","codex","gemini","antigravity","chatgpt")

def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def get(path): return json.loads(path.read_text(encoding="utf-8"))

def init():
    for d in DIRS: (ROOT/d).mkdir(parents=True, exist_ok=True)
    m={"name":"NEXEN Universal Relay","version":"2.0","root":str(ROOT),
       "authority":"NEXEN canonical state","canonical_completion":False,
       "principle":"transport/discovery only; never become a second task authority"}
    put(ROOT/"bridge.json",m)
    return m

def event(kind, data):
    put(ROOT/"events"/f"{time.time_ns()}-{kind}.json", {"event":kind,"at":time.time(),**data})

def command_exists(name):
    from shutil import which
    return which(name) is not None

def cli_discovery():
    names = {
      "nexen":["nexen"],
      "codex":["codex"],
      "claude":["claude"],
      "gemini":["gemini"],
      "hermes":["hermes","hermes-agent"],
      "antigravity":["antigravity"],
      "ollama":["ollama"],
      "n8n":["n8n"],
      "git":["git"],
      "node":["node"],
      "python":["py","python","python3"]
    }
    out={}
    for label,cands in names.items():
        found=next((c for c in cands if command_exists(c)),None)
        out[label]={"found":bool(found),"command":found,"authenticated":"UNVERIFIED"}
    return out

def main():
    p=argparse.ArgumentParser(prog="nexen-relay")
    s=p.add_subparsers(dest="c",required=True)
    for c in ("init","discover","workers","status","pending-prompts","cli-check"): s.add_parser(c)

    x=s.add_parser("register"); x.add_argument("name"); x.add_argument("--capability",action="append",default=[]); x.add_argument("--endpoint",default="local")
    x=s.add_parser("heartbeat"); x.add_argument("worker"); x.add_argument("--status",default="READY")
    x=s.add_parser("send"); x.add_argument("--ticket",required=True); x.add_argument("--to",required=True); x.add_argument("--prompt",required=True); x.add_argument("--source",default="chatgpt"); x.add_argument("--context",default="")
    x=s.add_parser("fail"); x.add_argument("job"); x.add_argument("--reason",required=True)
    x=s.add_parser("receipt"); x.add_argument("job"); x.add_argument("--worker",required=True); x.add_argument("--status",choices=["SUCCESS","FAIL","BLOCKED"],required=True); x.add_argument("--proof",choices=["PASS","FAIL","NOT_RUN"],required=True); x.add_argument("--evidence",default=""); x.add_argument("--summary",default="")
    x=s.add_parser("publish"); x.add_argument("--kind",choices=["hourly","daily","sixhour","sheets","ticket","context"],required=True); x.add_argument("--source",required=True); x.add_argument("--file",required=True)
    x=s.add_parser("pulse"); x.add_argument("--ticket",default="CONTINUITY"); x.add_argument("--to",default="*")

    a=p.parse_args(); m=init()

    if a.c in ("init","discover"):
        print(json.dumps(m,indent=2)); return
    if a.c=="cli-check":
        z=cli_discovery(); put(ROOT/"context"/"cli-connectivity.json",z); print(json.dumps(z,indent=2)); return
    if a.c=="register":
        z={"worker":a.name,"endpoint":a.endpoint,"capabilities":a.capability,"registered_at":time.time(),"authority":False}
        put(ROOT/"workers"/f"{a.name}.json",z); event("registered",z); print(json.dumps(z)); return
    if a.c=="heartbeat":
        z={"worker":a.worker,"status":a.status,"at":time.time()}; put(ROOT/"heartbeats"/f"{a.worker}.json",z); event("heartbeat",z); print(json.dumps(z)); return
    if a.c=="workers":
        print(json.dumps([get(q) for q in (ROOT/"workers").glob("*.json")],indent=2)); return
    if a.c=="send":
        jid=f"{a.ticket}-{uuid.uuid4().hex[:10]}"
        z={"job_id":jid,"ticket_id":a.ticket,"to":a.to,"prompt":a.prompt,"context":a.context,"source":a.source,
           "state":"QUEUED","attempts":1,"created_at":time.time(),"canonical_completion":False}
        put(ROOT/"outbox"/f"{jid}.json",z); put(ROOT/"inbox"/f"{jid}.json",z); event("queued",z); print(jid); return
    if a.c=="fail":
        candidates=[ROOT/d/f"{a.job}.json" for d in ("outbox","inbox","claimed")]
        src=next((q for q in candidates if q.exists()),None)
        z=get(src) if src else {"job_id":a.job}
        z.update(state="FAILED_DISPATCH",error=a.reason,failed_at=time.time(),canonical_completion=False)
        put(ROOT/"failed"/f"{a.job}.json",z); event("failed_dispatch",z); print(json.dumps(z,indent=2)); return
    if a.c=="pending-prompts":
        print(json.dumps([get(q) for q in (ROOT/"failed").glob("*.json")],indent=2)); return
    if a.c=="receipt":
        z={"job_id":a.job,"worker":a.worker,"status":a.status,"proof":a.proof,"evidence":a.evidence,"summary":a.summary,
           "at":time.time(),"canonical_completion":False,"note":"Canonical NEXEN validation required before ticket DONE."}
        put(ROOT/"receipts"/f"{a.job}.json",z); event("receipt",z); print(json.dumps(z,indent=2)); return
    if a.c=="publish":
        f=Path(a.file)
        if not f.exists(): raise SystemExit("SOURCE_FILE_MISSING")
        dst=ROOT/"updates"/f"{int(time.time())}-{a.kind}-{f.name}"
        shutil.copy2(f,dst)
        z={"kind":a.kind,"source":a.source,"artifact":str(dst),"at":time.time()}
        event("update",z); print(json.dumps(z,indent=2)); return
    if a.c=="pulse":
        prompt=("HOURLY CONTINUITY PULSE: merge newer context and continue from the last verified checkpoint. "
                "DO NOT restart or undo working code merely because this pulse arrived. Preserve the active ticket, lease, "
                "unfinished work and evidence. Check canonical state and CLI connectivity; report only material progress/blockers.")
        jid=f"{a.ticket}-{uuid.uuid4().hex[:10]}"
        z={"job_id":jid,"ticket_id":a.ticket,"to":a.to,"prompt":prompt,"source":"nexen-relay-hourly",
           "state":"QUEUED","attempts":1,"created_at":time.time(),"canonical_completion":False}
        put(ROOT/"outbox"/f"{jid}.json",z); put(ROOT/"inbox"/f"{jid}.json",z); event("hourly_pulse",z); print(jid); return
    if a.c=="status":
        print(json.dumps({d:len(list((ROOT/d).glob("*"))) for d in DIRS},indent=2))

if __name__=="__main__": main()
