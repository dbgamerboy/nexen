"""Live leading indicators. Each check is cheap, time-boxed and mapped to a problem class,
so risk is computed from what the machine is doing right now, not only from history."""
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

from .. import gate, paths


def _http_ms(url, timeout):
    t = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read(200)
        return round((time.time() - t) * 1000), None
    except Exception as e:
        return None, type(e).__name__


def _disk(drive, warn_gb, bad_gb, pid):
    def run():
        try:
            free = shutil.disk_usage(drive).free / 1e9
        except OSError as e:
            return {"state": "bad", "value": None, "detail": "%s unreadable (%s)" % (drive, type(e).__name__), "problem": "ENV-001" if drive.startswith("F") else pid}
        state = "bad" if free < bad_gb else ("warn" if free < warn_gb else "ok")
        return {"state": state, "value": round(free, 1), "detail": "%s free %.1f GB" % (drive, free), "problem": pid}
    return run


def _stop():
    on = gate.stop_active()
    return {"state": "warn" if on else "ok", "value": on, "detail": "global STOP is %s" % ("ACTIVE" if on else "clear"), "problem": "INF-001"}


def _ollama():
    ms, err = _http_ms(paths.OLLAMA_URL + "/api/version", 8)
    if ms is None:
        return {"state": "bad", "value": None, "detail": "Ollama did not answer (%s)" % err, "problem": "ENV-003"}
    return {"state": "warn" if ms > 3000 else "ok", "value": ms, "detail": "Ollama answered in %d ms" % ms, "problem": "ENV-003"}


def _service(name, url, pid, optional=False):
    def run():
        ms, err = _http_ms(url, 5)
        if ms is None:
            return {"state": "warn" if optional else "bad", "value": None, "detail": "%s down (%s)" % (name, err), "problem": pid}
        return {"state": "ok", "value": ms, "detail": "%s up in %d ms" % (name, ms), "problem": pid}
    return run


def _f_read():
    """Read 64 KB of a small F: file and time it; the drive reads at under 1 MB/s when failing."""
    v = paths.VAULT_CANDIDATES[0]
    log = v / "00-Control" / "SESSION-LOG.md"
    t = time.time()
    try:
        with open(log, "rb") as fh:
            fh.read(65536)
    except OSError as e:
        return {"state": "bad", "value": None, "detail": "F: vault read failed (%s)" % type(e).__name__, "problem": "ENV-001"}
    ms = round((time.time() - t) * 1000)
    return {"state": "bad" if ms > 4000 else ("warn" if ms > 800 else "ok"), "value": ms, "detail": "F: 64 KB read took %d ms" % ms, "problem": "ENV-001"}


def _python():
    ok = paths.PYTHON.exists()
    return {"state": "ok" if ok else "bad", "value": str(paths.PYTHON), "detail": "recovery python %s" % ("present" if ok else "MISSING"), "problem": "ENV-002"}


def _heartbeat():
    p = paths.DATA / "loop-status.json"
    if not p.exists():
        return {"state": "warn", "value": None, "detail": "V4 loop has not completed a cycle yet", "problem": "INF-006"}
    age = (time.time() - p.stat().st_mtime) / 60
    return {"state": "warn" if age > 120 else "ok", "value": round(age), "detail": "V4 loop last cycle %d min ago" % age, "problem": "INF-006"}


def _tail_text(p, n=4096):
    with open(p, "rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - n))
        return fh.read().decode("utf-8", "replace")


def classify_boot_error(text):
    """Map the tail of a boot stderr log to the problem class it matches."""
    if re.search(r"Cannot find module 'C:\\+Users\\+[^\\']*'|can't open file 'C:\\+Users\\+[^\\']*'", text):
        return "OPS-001"
    if re.search(r"ENOENT.*mkdir.*F:\\", text):
        return "OPS-004"
    return "OPS-003"


def _boot_stderr(max_age_days=3):
    """A *-boot.stderr.log with a traceback means the worker boot.log called 'started' is dead."""
    log_dir = paths.H_NEXEN / "logs"
    bad = []
    try:
        for p in log_dir.glob("*boot.stderr.log"):
            st = p.stat()
            if st.st_size == 0 or time.time() - st.st_mtime > max_age_days * 86400:
                continue
            text = _tail_text(p)
            if re.search(r"Traceback|Error:|Error\b", text):
                bad.append((p.name, classify_boot_error(text)))
    except OSError as e:
        return {"state": "warn", "value": None, "detail": "boot logs unreadable (%s)" % type(e).__name__, "problem": "OPS-003"}
    if not bad:
        return {"state": "ok", "value": 0, "detail": "no boot stderr with errors in %d days" % max_age_days, "problem": "OPS-003"}
    return {"state": "bad", "value": len(bad), "detail": "boot stderr errors: " + ", ".join("%s (%s)" % b for b in bad[:4]), "problem": bad[0][1]}


def _bus_handlers():
    """MARVIN actions that failed because no handler exists; they fail on every press until fixed."""
    from ..connectors import base
    rows = base.tail_jsonl(paths.H_NEXEN / "marvin" / "bus" / "events.jsonl", n=300, max_bytes=300_000)
    missing = sorted({r.get("action") for r in rows if r.get("status") == "failed" and re.search(r"handler \w+ missing", str(r.get("summary")))} - {None})
    if missing:
        return {"state": "bad", "value": len(missing), "detail": "actions with no handler: " + ", ".join(missing), "problem": "OPS-005"}
    return {"state": "ok", "value": 0, "detail": "no missing-handler failures in the last 300 events", "problem": "OPS-005"}


def _log_size(limit_mb=5):
    log_dir = paths.H_NEXEN / "logs"
    try:
        big = [(p.name, p.stat().st_size / 1e6) for p in log_dir.glob("*.log") if p.stat().st_size > limit_mb * 1e6]
    except OSError:
        return {"state": "warn", "value": None, "detail": "log folder unreadable", "problem": "OPS-009"}
    if big:
        return {"state": "warn", "value": round(max(b[1] for b in big), 1), "detail": "logs over %d MB: %s" % (limit_mb, ", ".join("%s %.1f MB" % b for b in big[:3])), "problem": "OPS-009"}
    return {"state": "ok", "value": 0, "detail": "no log over %d MB" % limit_mb, "problem": "OPS-009"}


CHECKS = [("boot-stderr", _boot_stderr), ("bus-handlers", _bus_handlers), ("log-size", _log_size), ("stop", _stop), ("ollama", _ollama), ("v3-core", _service("V3 core", paths.V3_CORE_URL + "/healthz", "MOD-006")),
          ("n8n", _service("n8n 5678", paths.N8N_URL + "/healthz", "ENV-005", True)),
          ("n8n-staging", _service("n8n 5680", "http://127.0.0.1:5680/healthz", "ENV-005", True)),
          ("disk-H", _disk("H:\\", 40, 10, "ENV-010")), ("disk-F", _disk("F:\\", 15, 5, "ENV-010")), ("disk-C", _disk("C:\\", 10, 3, "ENV-010")),
          ("f-read", _f_read), ("python", _python), ("loop", _heartbeat)]


def live(timeout=12):
    results, threads = {}, []

    def go(name, fn):
        try:
            results[name] = fn()
        except Exception as e:
            results[name] = {"state": "warn", "value": None, "detail": "check crashed: %s" % type(e).__name__, "problem": None}
    for name, fn in CHECKS:
        t = threading.Thread(target=go, args=(name, fn), daemon=True)
        t.start()
        threads.append(t)
    end = time.time() + timeout
    for t in threads:
        t.join(max(0.1, end - time.time()))
    out = []
    for name, _ in CHECKS:
        r = results.get(name, {"state": "warn", "value": None, "detail": "check timed out", "problem": None})
        out.append({"id": name, **r})
    return out
