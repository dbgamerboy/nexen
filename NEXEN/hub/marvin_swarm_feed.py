"""Bounded owner progress and screenshot evidence; never dispatches agents.

SWARM-REPORT.json is a derived display artifact, not another controller or DB.
The optional existing-bus event is note-only; no Discord outbox is touched.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
import zlib

ROOT = Path(r"H:\NEXEN\handoffs\swarm-execution-20261005\marvin-feed")
REPORT = ROOT / "SWARM-REPORT.json"
ROSTER = Path(r"H:\NEXEN\agentic-os\shared\workflows\agent-team.json")
BUS = Path(r"H:\NEXEN\marvin\bus")
EVIDENCE_ROOTS = (ROOT.parent, Path(r"H:\NEXEN\handoffs\one-findable-base-20261005"))
PYTHON = Path(r"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe")
ROLE_IDS = ("coordinator","vault-memory","knowledge-retrieval","core-backend",
            "marvin-interface","workflow-execution","compute-workers","browser-apps",
            "commerce-research","qa-review","integration-release","source-librarian")
STATES = {"prepared","queued","running","held","failed","completed"}
MAX_REPORT = 256 * 1024
MAX_IMAGE = 10 * 1024 * 1024
MAX_REFERENCE = 2 * 1024 * 1024
_GUARD = threading.Lock()


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def unique(pairs):
    value = {}
    for k,v in pairs:
        if k in value: raise ValueError("duplicate_json_key")
        value[k] = v
    return value


def redact(text, limit=600):
    value = str(text or "")
    value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|\Z)","[credential omitted]",value)
    value = re.sub(r"(?i)\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16})\b","[credential omitted]",value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s\"'<>]+",r"\1[credential omitted]",value)
    value = re.sub(r"(?i)\b(?:https?|postgres(?:ql)?|mysql|redis|mongodb)://[^\s/@]+:[^\s/@]+@","[credential URL omitted]@",value)
    value = re.sub(r"(?i)(?:password|passwd|pwd|token|secret|api[_ -]?key|authorization|cookie)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)","[credential omitted]",value)
    value = re.sub(r"(?i)\b(?:desktop|laptop|win)-[a-z0-9-]+\b|\\\\[^\s]+|\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b","[private connection omitted]",value)
    value = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+","[contact omitted]",value)
    return value[:limit]


def safe_path(path, roots=None):
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts or str(p).startswith("\\\\") or len(str(p)) > 1024:
        raise ValueError("unsafe_local_path")
    for part in (p,*p.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0) & 0x400:
            raise ValueError("reparse_or_linked_path")
    p = p.resolve(strict=True)
    if roots and not any(p.is_relative_to(Path(r).resolve(strict=True)) for r in roots):
        raise ValueError("path_outside_owned_evidence_roots")
    return p


def raw_file(path, cap, roots=None):
    p = safe_path(path, roots)
    before = p.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1 or before.st_size > cap:
        raise ValueError("nonregular_linked_or_oversize_file")
    flags = os.O_RDONLY | getattr(os,"O_BINARY",0) | getattr(os,"O_NOFOLLOW",0)
    with os.fdopen(os.open(p,flags),"rb") as stream:
        opened = os.fstat(stream.fileno()); data = stream.read(cap+1)
    safe_path(p, roots)
    after = p.lstat()
    fp = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if len(data)>cap or len(data)!=before.st_size or fp(before)!=fp(opened) or fp(before)!=fp(after):
        raise ValueError("source_changed_during_read")
    return p,data


def load_json(path, cap=MAX_REPORT):
    _,raw = raw_file(path,cap)
    value = json.loads(raw.decode("utf-8-sig"),object_pairs_hook=unique)
    if not isinstance(value,dict): raise ValueError("json_not_object")
    return value


def image_type(raw):
    """Validate finite PNG/JPEG containers, dimensions and MIME; not OCR/pixel QA."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        cursor,header,data,end = 8,False,False,False
        while cursor < len(raw):
            if cursor+12>len(raw): raise ValueError("truncated_png")
            size=struct.unpack(">I",raw[cursor:cursor+4])[0]
            kind=raw[cursor+4:cursor+8];payload=raw[cursor+8:cursor+8+size]
            finish=cursor+12+size
            if finish>len(raw): raise ValueError("truncated_png")
            crc=struct.unpack(">I",raw[cursor+8+size:finish])[0]
            if zlib.crc32(kind+payload)&0xffffffff != crc: raise ValueError("invalid_png_crc")
            if not header:
                if kind!=b"IHDR" or size!=13: raise ValueError("invalid_png_header")
                width,height=struct.unpack(">II",payload[:8])
                if not 0<width<=16000 or not 0<height<=16000 or width*height>40_000_000:
                    raise ValueError("image_dimensions_limit")
                header=True
            if kind==b"IDAT": data=True
            if kind==b"IEND":
                if size or finish!=len(raw): raise ValueError("invalid_png_end")
                end=True
            cursor=finish
        if not data or not end: raise ValueError("incomplete_png")
        return "image/png"
    if raw.startswith(b"\xff\xd8") and raw.endswith(b"\xff\xd9"):
        cursor,frame = 2,False
        while cursor < len(raw)-2:
            if raw[cursor]!=255: raise ValueError("invalid_jpeg_marker")
            while raw[cursor]==255: cursor+=1
            marker=raw[cursor];cursor+=1
            if marker==0xda:
                if not frame: raise ValueError("jpeg_frame_missing")
                return "image/jpeg"
            if marker in (0xd8,0xd9,0x01) or 0xd0<=marker<=0xd7: continue
            if cursor+2>len(raw): raise ValueError("truncated_jpeg")
            size=int.from_bytes(raw[cursor:cursor+2],"big")
            if size<2 or cursor+size>len(raw): raise ValueError("invalid_jpeg_segment")
            if marker in (0xc0,0xc1,0xc2):
                if size<8: raise ValueError("invalid_jpeg_frame")
                height=int.from_bytes(raw[cursor+3:cursor+5],"big");width=int.from_bytes(raw[cursor+5:cursor+7],"big")
                if not 0<width<=16000 or not 0<height<=16000 or width*height>40_000_000:
                    raise ValueError("image_dimensions_limit")
                frame=True
            cursor+=size
    raise ValueError("unsupported_or_invalid_image")


@dataclass(frozen=True)
class FeedConfig:
    report_path: Path = REPORT
    roster_path: Path = ROSTER
    evidence_roots: tuple = EVIDENCE_ROOTS
    bus_path: Path = BUS


class SwarmFeed:
    def __init__(self,config=FeedConfig()): self.config=config
    def roster(self):
        p,raw=raw_file(self.config.roster_path,65536)
        data=json.loads(raw.decode("utf-8-sig"),object_pairs_hook=unique)
        roles=data.get("roles") if isinstance(data,dict) else None
        if not isinstance(roles,list) or len(roles)!=12 or {r.get("id") for r in roles if isinstance(r,dict)}!=set(ROLE_IDS):
            raise ValueError("approved_twelve_role_definition_missing")
        return [dict(id=r["id"],name=redact(r.get("name") or r["id"],80),scope=redact(r.get("scope"),160),definition_only=True) for r in roles],hashlib.sha256(raw).hexdigest()
    def reference(self,path,image=False):
        p,raw=raw_file(path,MAX_IMAGE if image else MAX_REFERENCE,self.config.evidence_roots)
        result=dict(path=str(p),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        if image:
            if p.suffix.lower() not in (".png",".jpg",".jpeg"): raise ValueError("unsupported_image_extension")
            result.update(mime=image_type(raw),scope="nexen_task_evidence",url="/api/marvin/swarm/image/"+result["sha256"])
        return result
    def accepted(self,reference,task_id,worker):
        current=self.reference(reference["path"])
        if current["sha256"]!=reference["sha256"]: raise ValueError("accepted_receipt_changed")
        receipt=load_json(reference["path"],MAX_REFERENCE)
        if (receipt.get("schema")!="nexen.accepted-task-receipt.v1" or receipt.get("accepted") is not True
                or receipt.get("status")!="accepted" or type(receipt.get("task_id")) is not int or receipt.get("task_id")!=task_id or receipt.get("worker")!=worker
                or not isinstance(receipt.get("evidence"),list) or not 1<=len(receipt["evidence"])<=8):
            raise ValueError("accepted_receipt_required")
        for ref in receipt["evidence"][:8]:
            if not isinstance(ref,dict) or self.reference(ref.get("path",""))["sha256"]!=ref.get("sha256"):
                raise ValueError("accepted_evidence_unverified")
        return True
    def empty(self,note="No current executor report."):
        try:roles,sha=self.roster()
        except (OSError,ValueError,TypeError):roles=[dict(id=i,name=i,scope="",definition_only=True) for i in ROLE_IDS];sha=None
        return dict(schema="nexen.swarm-report.v1",status="unavailable",updated_at=None,roster_sha256=sha,
                    roles=[dict(**r,state="held",summary=note,task_id=None,progress=None,reported_at=None,screenshot=None,evidence=[]) for r in roles],
                    history=[],canonical_completion=False,definition_count=12,process_liveness_verified=False,
                    note="Declared roles are not proof of running model workers.")
    def validate_entry(self,entry,verify_files=True):
        if not isinstance(entry,dict) or entry.get("worker") not in ROLE_IDS or entry.get("state") not in STATES:
            raise ValueError("invalid_progress_entry")
        if type(entry.get("task_id")) is not int or not 1<=entry["task_id"]<=2**31-1:
            raise ValueError("invalid_canonical_task")
        progress=entry.get("progress")
        if progress is not None and (isinstance(progress,bool) or not isinstance(progress,(int,float)) or not math.isfinite(progress) or not 0<=progress<=100):
            raise ValueError("invalid_progress")
        stamp=datetime.fromisoformat(entry["reported_at"])
        if stamp.tzinfo is None or stamp.timestamp()>time.time()+300: raise ValueError("invalid_report_timestamp")
        result=dict(entry,summary=redact(entry.get("summary")),process_liveness_verified=False,canonical_completion=False)
        if not isinstance(entry.get("evidence"),list) or len(entry["evidence"])>8: raise ValueError("invalid_evidence_list")
        result["evidence"]=[]
        warnings=[]
        for reference in entry["evidence"]:
            try:
                current=self.reference(reference["path"])
                if current["sha256"]!=reference["sha256"]: raise ValueError("evidence_changed")
                result["evidence"].append(current)
            except (OSError,ValueError,KeyError,TypeError): warnings.append("evidence_missing_or_changed")
        result["screenshot"]=None
        if entry.get("screenshot"):
            try:
                current=self.reference(entry["screenshot"]["path"],image=True)
                if current["sha256"]!=entry["screenshot"]["sha256"]: raise ValueError("image_changed")
                result["screenshot"]=current
            except (OSError,ValueError,KeyError,TypeError): warnings.append("screenshot_missing_changed_or_invalid")
        if result["state"]=="completed":
            try:self.accepted(entry.get("accepted_receipt") or {},entry["task_id"],entry["worker"])
            except (OSError,ValueError,KeyError,TypeError):result["state"]="held";warnings.append("completion_receipt_missing_or_changed")
        age=max(0,time.time()-stamp.timestamp())
        if result["state"]=="running" and age>90:
            result["state"]="held";warnings.append("last_running_report_stale")
        result["warnings"]=warnings;result["age_seconds"]=round(age,1)
        return result
    def read(self):
        if not self.config.report_path.exists(): return self.empty()
        data=load_json(self.config.report_path)
        roles,roster_sha=self.roster()
        if data.get("schema")!="nexen.swarm-report.v1" or not isinstance(data.get("entries"),list) or len(data["entries"])>12 or len(data.get("history",[]))>48:
            raise ValueError("invalid_swarm_report")
        latest={}
        for entry in data["entries"]:
            item=self.validate_entry(entry)
            if item["worker"] in latest: raise ValueError("duplicate_role_report")
            latest[item["worker"]]=item
        display=[]
        for role in roles:
            value=latest.get(role["id"]) or dict(state="held",summary="Defined; no current executor report.",task_id=None,progress=None,reported_at=None,screenshot=None,evidence=[],warnings=[])
            display.append(dict(**role,**{k:v for k,v in value.items() if k not in role}))
        return dict(schema="nexen.swarm-report.v1",status="ready",updated_at=data.get("updated_at"),roles=display,
                    history=[self.validate_entry(e) for e in data.get("history",[])[-12:]],roster_sha256=roster_sha,
                    canonical_completion=False,definition_count=12,process_liveness_verified=False,
                    report_path=str(self.config.report_path),note="Executor-reported progress; completed requires an accepted local receipt.")
    def emit(self,task_id,worker,state,summary,progress,evidence_paths=(),screenshot_path=None,accepted_receipt=None,bus_note=False):
        if not isinstance(evidence_paths,(tuple,list)) or len(evidence_paths)>8: raise ValueError("invalid_evidence_paths")
        roles,roster_sha=self.roster()
        evidence=[self.reference(p) for p in evidence_paths]
        screenshot=self.reference(screenshot_path,True) if screenshot_path else None
        receipt=self.reference(accepted_receipt) if accepted_receipt else None
        entry=dict(event_id=uuid.uuid4().hex,task_id=task_id,worker=worker,state=state,summary=redact(summary),progress=progress,
                   reported_at=utc(),evidence=evidence,screenshot=screenshot,accepted_receipt=receipt,
                   canonical_completion=False,process_liveness_verified=False)
        self.validate_entry(entry)
        if state=="completed": self.accepted(receipt or {},task_id,worker)
        parent=self.config.report_path.parent;parent.mkdir(parents=True,exist_ok=True);safe_path(parent)
        lock=parent/".swarm-report.lock"
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise RuntimeError("swarm_report_writer_busy")
        os.close(fd)
        temp=parent/('.swarm-report-'+entry['event_id']+'.tmp')
        try:
            if self.config.report_path.exists():
                report=load_json(self.config.report_path)
                if report.get("schema")!="nexen.swarm-report.v1" or not isinstance(report.get("entries"),list):raise ValueError("malformed_existing_report")
            else:report=dict(schema="nexen.swarm-report.v1",entries=[],history=[])
            entries=[x for x in report["entries"] if x.get("worker")!=worker]
            if len(entries)>=12: raise ValueError("too_many_reported_roles")
            entries.append(entry)
            history=(report.get("history",[])+[entry])[-48:]
            report.update(entries=entries,history=history,updated_at=entry["reported_at"],roster_sha256=roster_sha,canonical_completion=False)
            payload=json.dumps(report,ensure_ascii=False,allow_nan=False).encode("utf-8")
            while len(payload)>MAX_REPORT and history:
                history.pop(0);payload=json.dumps(report,ensure_ascii=False,allow_nan=False).encode("utf-8")
            if len(payload)>MAX_REPORT:raise ValueError("swarm_report_byte_cap")
            with temp.open("xb") as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,self.config.report_path)
            p,actual=raw_file(self.config.report_path,MAX_REPORT)
            if actual!=payload: raise RuntimeError("report_readback_mismatch")
            bus_status="not_requested"
            if bus_note:
                bus_script=Path(r"H:\NEXEN\marvin\bus\marvin_bus.py")
                if hashlib.sha256(bus_script.read_bytes()).hexdigest()!="d5302d79382ba7e62c507c5c96e565e755171098af38e72c73c203dcd64b9f5d":raise ValueError("reviewed_bus_source_changed")
                spec=importlib.util.spec_from_file_location("_reviewed_marvin_bus",bus_script);bus=importlib.util.module_from_spec(spec);spec.loader.exec_module(bus)
                bus.append(dict(type="note",source="swarm",at=entry["reported_at"],text=f"Task {task_id} · {worker} · {state}: {entry['summary']}",task_id=task_id,worker=worker,refs=[dict(path=r["path"],note="Task evidence; source SHA verified.") for r in evidence]),bus=self.config.bus_path)
                bus_status="note_appended_no_outbox"
            return dict(event_id=entry["event_id"],reported_at=entry["reported_at"],entry=entry,report_path=str(p),report_sha256=hashlib.sha256(actual).hexdigest(),bus_status=bus_status)
        finally:
            temp.unlink(missing_ok=True);lock.unlink(missing_ok=True)
    def image(self,sha):
        if not isinstance(sha,str) or not re.fullmatch(r"[a-f0-9]{64}",sha):raise ValueError("invalid_image_id")
        data=load_json(self.config.report_path)
        for entry in data.get("entries",[])+data.get("history",[]):
            reference=entry.get("screenshot") if isinstance(entry,dict) else None
            if isinstance(reference,dict) and reference.get("sha256")==sha:
                current=self.reference(reference["path"],True)
                if current["sha256"]!=sha:raise ValueError("screenshot_changed")
                _,raw=raw_file(current["path"],MAX_IMAGE,self.config.evidence_roots)
                if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError("screenshot_changed_after_validation")
                return raw,current["mime"]
        raise FileNotFoundError("screenshot_not_in_report")


def emit_progress(task_id,worker,state,summary,progress,evidence_paths=(),screenshot_path=None,accepted_receipt=None,*,bus_note=False):
    if not isinstance(evidence_paths,(list,tuple)) or len(evidence_paths)>8:
        raise ValueError("invalid_evidence_paths")
    values=dict(task_id=task_id,worker=worker,state=state,summary=redact(summary),progress=progress,
                evidence_paths=[str(p) for p in evidence_paths],screenshot_path=str(screenshot_path) if screenshot_path else None,
                accepted_receipt=str(accepted_receipt) if accepted_receipt else None,bus_note=bus_note)
    result=_bounded("emit",values=values,seconds=4)
    if not result.get("event_id") or not result.get("report_sha256"):
        raise RuntimeError(result.get("note") or "Progress write was not verified; inspect report before retrying.")
    return result


def _bounded(operation,config=FeedConfig(),sha=None,seconds=3,values=None):
    if not _GUARD.acquire(blocking=False):return dict(status="busy",roles=[],history=[],note="Owned feed reader busy.")
    process=None;started=time.monotonic()
    try:
        request=dict(operation=operation,config=dict(report_path=str(config.report_path),roster_path=str(config.roster_path),evidence_roots=[str(p) for p in config.evidence_roots],bus_path=str(config.bus_path)),sha=sha,values=values)
        process=subprocess.Popen([str(PYTHON),"-I","-B","-X","utf8",str(Path(__file__).resolve()),"--_reader"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        payload,_=process.communicate(json.dumps(request).encode(),timeout=max(.001,seconds-(time.monotonic()-started)))
        if process.returncode or len(payload)>MAX_IMAGE*2:raise ValueError("reader_failed_or_oversize")
        return json.loads(payload)
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return dict(status="unavailable",roles=[],history=[],note="Feed reader unavailable or reached its finite deadline.")
    finally:
        alive=False
        if process:
            if process.poll() is None:
                process.kill()
                try:process.wait(timeout=.5)
                except subprocess.TimeoutExpired:alive=True
            for stream in (process.stdin,process.stdout):
                if stream:stream.close()
        if not alive:_GUARD.release()


def read_report(report_path=None):
    config=FeedConfig(report_path=Path(report_path) if report_path else REPORT)
    result=_bounded("read",config)
    if not result.get("roles"):
        result["roles"]=[dict(id=i,name=i,scope="Approved role ID; current feed unavailable.",definition_only=True,
                               state="held",task_id=None,progress=None,reported_at=None,screenshot=None,evidence=[],summary="No verified current progress.") for i in ROLE_IDS]
        result.update(definition_count=12,canonical_completion=False,process_liveness_verified=False)
    return result


def read_screenshot(sha):
    result=_bounded("image",sha=sha)
    if result.get("status")!="ready":raise FileNotFoundError("Screenshot is unavailable or unverified.")
    return base64.b64decode(result["data"],validate=True),result["mime"]


if __name__=="__main__" and sys.argv[1:]==["--_reader"]:
    try:
        request=json.loads(sys.stdin.buffer.read(16385),object_pairs_hook=unique)
        cfg=request["config"];feed=SwarmFeed(FeedConfig(Path(cfg["report_path"]),Path(cfg["roster_path"]),tuple(Path(p) for p in cfg["evidence_roots"]),Path(cfg["bus_path"])))
        if request["operation"]=="read":result=feed.read()
        elif request["operation"]=="image":
            raw,mime=feed.image(request["sha"]);result=dict(status="ready",mime=mime,data=base64.b64encode(raw).decode())
        elif request["operation"]=="emit":result=feed.emit(**request["values"])
        else:raise ValueError("invalid_operation")
        sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())
    except Exception:
        sys.stdout.buffer.write(json.dumps(dict(status="unavailable",roles=[],history=[],note="Invalid or unavailable derived feed.")).encode())
