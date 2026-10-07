"""Mine NEXEN's own failure history and classify it against the catalog.

Sources (all read-only): knowledge-ledger lessons, SESSION-LOG 'Blocked on' lines, the desktop coding status
report (PROOF FAIL, BLOCKER), MARVIN bus events that failed, and V4's own provider errors.
Classified failures raise a problem class's observed rate; unclassified ones are candidates for new catalog entries.
"""
import re
import time
from pathlib import Path

from .. import paths, textsim
from ..connectors import base

FAIL_WORDS = re.compile(r"\b(fail|failed|failure|blocked|error|stale|broken|bug|defect|wrong|missing|unverified|hang|hung|timeout|timed out|"
                        r"rejected|refused|did not|didn't|cannot|can't|never ran|fake|lost|crash|collision)\b", re.I)


# Lines that look like failures but are vendor noise or an owner decision, not a defect to repair.
NOISE = re.compile(r"\[Rudder\]|DeprecationWarning|--trace-deprecation|DEP\d{4}", re.I)
OWNER_GATE = re.compile(r"\b(owner|approval|authori[sz]ation|human verification|sign-?in|login|press&hold|w-?9|agreement|budget)\b", re.I)


def is_noise(text):
    return bool(NOISE.search(text))


def _candidates():
    led = paths.KNOWLEDGE / "KNOWLEDGE-LEDGER.jsonl"
    for row in base.stream_jsonl(led, max_bytes=3_000_000):
        for lesson in row.get("lessons") or []:
            if isinstance(lesson, str) and FAIL_WORDS.search(lesson):
                yield "knowledge-ledger", lesson, row.get("t")
    v = paths.vault()
    if v:
        log = v / "00-Control" / "SESSION-LOG.md"
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-1500:]:
                m = re.match(r"\s*-\s*Blocked on:\s*(.+)", line)
                if m and m.group(1).strip().lower() not in {"none", "nothing", "n/a"}:
                    yield "session-log", m.group(1).strip(), None
        except OSError:
            pass
    report = Path.home() / "Desktop" / "MARVIN" / "Reports" / "NEXEN-CODING-STATUS-LATEST.txt"
    try:
        for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r"(PROOF FAIL|BLOCKER)\s*:\s*(.+)", line)
            if m:
                yield "coding-status", m.group(2).strip(), None
    except OSError:
        pass
    for r in base.tail_jsonl(paths.H_NEXEN / "marvin" / "bus" / "events.jsonl", n=400, max_bytes=600_000):
        if r.get("status") == "failed":
            yield "marvin-bus", "%s: %s" % (r.get("action"), r.get("summary")), r.get("at")
    log_dir = paths.H_NEXEN / "logs"
    try:
        for p in log_dir.glob("*.stderr.log"):
            line = last_error_line(p)
            if line:
                yield "nexen-log:" + p.name, line, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))
        boot = log_dir / "boot.log"
        for line in boot.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
            if re.search(r"BOOT REPORT .*=False", line):
                yield "nexen-log:boot.log", line.strip(), None
    except OSError:
        pass


def last_error_line(path, tail_bytes=4096):
    """Final exception line of a stderr log (the line after the last traceback), or None for empty and noise-only logs."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail_bytes))
            lines = [ln.strip() for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    except OSError:
        return None
    lines = [ln for ln in lines if not NOISE.search(ln)]
    for ln in reversed(lines):
        if re.search(r"(Error|Exception)\b", ln) and not ln.startswith("at "):
            return ln[:300]
    return None


def mine(spine, limit=400):
    """Classify and store new failures. Returns counts by problem and the unclassified sample."""
    added, classified, unclassified = 0, {}, []
    seen = 0
    for source, text, ts in _candidates():
        text = base.redact(text)[:500]
        if is_noise(text) or (source == "session-log" and OWNER_GATE.search(text)):
            continue  # vendor noise and owner-only gates are not repairable failures
        fp = textsim.fingerprint(text)
        seen += 1
        if seen > limit * 3:
            break
        d = spine.diagnose(text, k=1)
        pid = d["matches"][0]["id"] if d["confident"] else None
        with spine.lock:
            try:
                spine.db.execute("INSERT INTO failures(ts,fp,source,text,problem_id,score) VALUES(?,?,?,?,?,?)",
                                 (ts or time.strftime("%Y-%m-%dT%H:%M:%S"), fp, source, text, pid, d["top_score"]))
                if pid:
                    spine.db.execute("INSERT OR IGNORE INTO occurrences(ts,problem_id,fp,source,text) VALUES(?,?,?,?,?)",
                                     (ts or time.strftime("%Y-%m-%dT%H:%M:%S"), pid, fp, source, text))
                spine.db.commit()
            except Exception:
                continue  # already stored (fingerprint unique)
        added += 1
        if pid:
            classified[pid] = classified.get(pid, 0) + 1
        else:
            unclassified.append({"source": source, "text": text[:160]})
        if added >= limit:
            break
    return {"added": added, "classified": dict(sorted(classified.items(), key=lambda kv: -kv[1])), "unclassified": len(unclassified),
            "unclassified_sample": unclassified[:8]}


def similar(spine, text, k=3):
    """Past failures most like this text (for decisions and novel plans)."""
    toks = Spine_tok(text)
    with spine.lock:
        rows = [dict(r) for r in spine.db.execute("SELECT text,source,problem_id FROM failures ORDER BY id DESC LIMIT 800")]
    scored = sorted(((textsim.jaccard(toks, Spine_tok(r["text"])), r) for r in rows), key=lambda x: -x[0])
    return [r for s, r in scored[:k] if s > 0.08]


def Spine_tok(text):
    return textsim.tokens(text)
