"""Self-patching through the one tested path.

MARVIN (or any agent) describes a change; a strong model proposes whole-file replacements as JSON; the proposal is
screened (allowed folders only, size caps, must compile, no shell execution or eval, no credential strings), written as
an update package, and applied only through updater.apply: sha256 verified, old files backed up, the full test suite
run, and every change rolled back if one test fails. Applying needs auto=True and no global STOP. Without those the
package is only prepared. It cannot touch V3, the exe shell, or anything outside engine/, ui/ and modules/.
"""
import ast
import hashlib
import json
import re
import time

from .. import gate, paths, updater

ALLOWED = ("engine/", "ui/", "modules/")
FORBIDDEN = [re.compile(p) for p in (r"shell\s*=\s*True", r"\bos\.system\(", r"(?<![\w.])eval\(", r"(?<![\w.])exec\(", r"(?i)(password|api[_-]?key|secret)\s*=\s*[\"'][^\"']{8,}")]
MAX_FILES, MAX_BYTES = 6, 120_000


def screen(files):
    """Return a list of problems; empty means the proposal may become a package."""
    problems = []
    if not files or len(files) > MAX_FILES:
        return ["need 1 to %d files" % MAX_FILES]
    for f in files:
        rel, content = str(f.get("path", "")).replace("\\", "/"), f.get("content")
        if not isinstance(content, str) or len(content.encode()) > MAX_BYTES:
            problems.append("%s: content missing or over %d bytes" % (rel, MAX_BYTES))
            continue
        if ".." in rel.split("/") or not rel.startswith(ALLOWED):
            problems.append("%s: outside engine/ ui/ modules/" % rel)
            continue
        if rel.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as e:
                problems.append("%s: does not compile (line %s)" % (rel, e.lineno))
            for rx in FORBIDDEN:
                if rx.search(content):
                    problems.append("%s: forbidden pattern %s" % (rel, rx.pattern[:30]))
        if rel.endswith(".json"):
            try:
                json.loads(content)
            except ValueError:
                problems.append("%s: invalid JSON" % rel)
    return problems


def make_package(name, files, notes):
    d = paths.APP / "updates" / name
    entries = []
    for f in files:
        rel = f["path"].replace("\\", "/")
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f["content"].encode("utf-8"))
        entries.append({"path": rel, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"version": "selfpatch-" + time.strftime("%Y%m%d%H%M%S"), "notes": notes, "files": entries}, indent=2), encoding="utf-8")
    return d


def propose(brain, task, files=(), auto=False, model_slot="model.code"):
    """Ask the code model for a patch and prepare (or, with auto, apply) it."""
    sources = []
    for rel in files:
        p = paths.APP / rel
        if p.is_file() and rel.replace("\\", "/").startswith(ALLOWED):
            sources.append("FILE %s\n%s" % (rel, p.read_text(encoding="utf-8", errors="replace")[:20000]))
    prompt = ("Propose a minimal patch for this task. Return ONLY JSON: {\"files\":[{\"path\":\"engine/nexen/...\",\"content\":\"<whole new file>\"}],\"notes\":\"why\"}. "
              "Allowed folders: engine/, ui/, modules/. No shell=True, eval, exec or secrets. Include a test file under tests/ is NOT allowed here; keep behavior covered by existing tests.\n\nTASK: %s\n\n%s" % (task, "\n\n".join(sources)))
    r = brain.models.consult(prompt, slot=model_slot, timeout=240, agent="coder")
    if not r["ok"]:
        return {"ok": False, "stage": "model", "errors": r.get("errors")}
    m = re.search(r"\{.*\}", r["text"], re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {"ok": False, "stage": "parse", "reply": r["text"][:200]}
    files_out = data.get("files") or []
    problems = screen(files_out)
    if problems:
        return {"ok": False, "stage": "screen", "problems": problems}
    name = "selfpatch-" + hashlib.sha256((task + str(time.time())).encode()).hexdigest()[:8]
    pkg = make_package(name, files_out, data.get("notes", task)[:300])
    out = {"ok": True, "package": str(pkg), "name": name, "files": [f["path"] for f in files_out], "model": r["candidate"], "status": "prepared"}
    if auto and not gate.stop_active():
        out["apply"] = updater.apply(name)
        out["status"] = "applied" if out["apply"].get("ok") else "rolled back"
    elif auto:
        out["status"] = "prepared (global STOP blocks auto apply)"
    gate.audit("selfcode", {"task": task[:100], "status": out["status"], "files": out["files"]})
    return out
