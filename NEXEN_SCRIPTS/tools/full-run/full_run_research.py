from __future__ import annotations
import argparse, datetime as dt, hashlib, json, shutil, subprocess, uuid
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description="Bounded YouTube evidence collector for NEXEN FULL RUN")
    p.add_argument("--query", required=True)
    p.add_argument("--max-videos", type=int, default=10)
    p.add_argument("--output", required=True)
    p.add_argument("--fixture")
    args=p.parse_args()
    if not 1 <= args.max_videos <= 25: raise SystemExit("--max-videos must be 1..25")
    out=Path(args.output); out.mkdir(parents=True, exist_ok=True)
    job_id=f"research-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    if args.fixture:
        data=json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    else:
        exe=shutil.which("yt-dlp")
        if not exe: raise SystemExit("yt-dlp CLI unavailable")
        cmd=[exe,"--dump-single-json","--flat-playlist",f"ytsearch{args.max_videos}:{args.query}"]
        run=subprocess.run(cmd,capture_output=True,text=True,timeout=300,check=True)
        data=json.loads(run.stdout)
    entries=data.get("entries",[])[:args.max_videos]
    items=[]
    for x in entries:
        url=x.get("webpage_url") or x.get("url") or ""
        if url and not url.startswith("http") and x.get("id"): url=f"https://www.youtube.com/watch?v={x['id']}"
        items.append({"id":x.get("id"),"url":url,"title":x.get("title"),"channel":x.get("channel") or x.get("uploader"),"duration":x.get("duration"),"sourceHash":hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()})
    receipt={"ok":True,"jobId":job_id,"query":args.query,"adapter":"CLI/yt-dlp" if not args.fixture else "fixture","items":items,"count":len(items),"publish":False,"requiresReview":True}
    path=out/f"{job_id}.json"; path.write_text(json.dumps(receipt,indent=2),encoding="utf-8")
    receipt["receiptPath"]=str(path)
    print(json.dumps(receipt))
if __name__=="__main__": main()
