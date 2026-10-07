"""Bridge from MARVIN to standalone module scripts, behind the approval gate.

A module whose source can write outside the machine (HTTP writes, webhooks, mail, deletes) is an
external effect: it is queued for owner approval and never runs from here. Every other module runs
in an isolated subprocess with a timeout. No call raises; each returns a structured result.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from . import gate, paths

MOD_DIR = Path(os.environ.get("NEXEN_MODBRIDGE_DIR", str(Path(__file__).resolve().parents[3] / "modules")))
OUTBOUND = re.compile(r"requests\.(post|put|delete|patch)|urlopen|smtplib|shutil\.rmtree|os\.remove|webhook|\.send\(", re.I)
NAME = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
MAX_OUT = 4000


def catalog():
    out = []
    if MOD_DIR.is_dir():
        for p in sorted(MOD_DIR.glob("*.py")):
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            out.append({"name": p.stem, "outbound": bool(OUTBOUND.search(src))})
    return out


def run(name, args=None, timeout=20, autonomous=True):
    if not isinstance(name, str) or not NAME.match(name):
        return {"ok": False, "reason": "invalid module name"}
    known = {m["name"]: m for m in catalog()}
    if name not in known:
        return {"ok": False, "reason": "unknown module"}
    args = [str(a) for a in (args or [])][:8]
    kind = "external_api_write" if known[name]["outbound"] else "test"
    verdict = gate.check(kind, "module " + name, {"module": name, "args": args}, autonomous=autonomous)
    if not verdict["allowed"]:
        return {"ok": False, "ran": False, "reason": verdict["reason"], "approval_id": verdict.get("approval_id")}
    script = MOD_DIR / (name + ".py")
    try:
        r = subprocess.run([sys.executable if not paths.PYTHON.exists() else str(paths.PYTHON), "-I", "-B", str(script)] + args,
                           capture_output=True, text=True, timeout=max(1, min(int(timeout), 120)),
                           encoding="utf-8", errors="replace", cwd=str(MOD_DIR))
    except subprocess.TimeoutExpired:
        gate.audit("module_timeout", {"module": name})
        return {"ok": False, "ran": True, "reason": "timeout"}
    except Exception as exc:  # no module call may crash the caller
        return {"ok": False, "ran": False, "reason": "launch failed: %s" % type(exc).__name__}
    gate.audit("module_run", {"module": name, "code": r.returncode})
    return {"ok": r.returncode == 0, "ran": True, "code": r.returncode,
            "stdout": r.stdout[-MAX_OUT:], "stderr": r.stderr[-MAX_OUT:]}
