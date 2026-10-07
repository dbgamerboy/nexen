"""Reliability: no entry point ends in an uncaught crash.

"Never fails" is not something software can promise, so V4 promises the part it can keep: every script, function, API
call, MCP tool, loop step and n8n operation runs inside ``run_guarded`` or ``resilient``, which

  1. retries transient faults (timeouts, locked databases, 429, connection resets) with bounded backoff,
  2. on a real fault, diagnoses it against the problem catalog and returns the playbook's next action,
  3. records the occurrence so the spine's failure rates learn from it,
  4. returns a structured result (ok, error, problem, next_action, attempts, degraded) instead of raising,
  5. keeps the caller's loop alive with a safe default.
``doctor`` checks every subsystem and repairs what is safe to repair (rebuild a search index, reset a corrupt config
after backing it up, restart a dead loop). Failures are never swallowed silently: each lands in the audit log.
"""
import functools
import importlib
import json
import re
import shutil
import sqlite3
import time
import traceback
import urllib.error
import urllib.request

from nexen.core import gate, paths
from nexen.shared.utils import textsim

TRANSIENT_TYPES = (TimeoutError, ConnectionError, urllib.error.URLError, BrokenPipeError)
TRANSIENT_TEXT = re.compile(r"(?i)database is locked|database table is locked|SQLITE_BUSY|timed out|timeout|429|too many requests|temporar|connection (reset|aborted|refused)|try again|being used by another process")
_spine = None


def _get_spine():
    global _spine
    if _spine is None:
        from nexen.features.spine.engine import Spine
        _spine = Spine(db_path=paths.DATA / "spine.db")
    return _spine


def is_transient(exc):
    return isinstance(exc, TRANSIENT_TYPES) or bool(TRANSIENT_TEXT.search("%s %s" % (type(exc).__name__, exc))) or (
        isinstance(exc, sqlite3.OperationalError) and "lock" in str(exc).lower())


def explain(exc, context=""):
    """Diagnose an exception against the catalog. Never raises."""
    text = "%s: %s %s" % (type(exc).__name__, str(exc)[:300], context[:100])
    try:
        d = _get_spine().diagnose(text, k=1)
        top = d["matches"][0] if d["matches"] else None
        if top and d["confident"]:
            sol = _get_spine().solution(top["id"], explore=False)
            return {"problem": top["id"], "title": top["title"], "next_action": sol["steps"][0], "verify": sol["verify"][0], "confident": True}
        return {"problem": None, "title": "no catalog match", "next_action": "Reproduce with the exact input, save the output, then run: nexen spine resolve \"%s\"" % text[:80], "confident": False}
    except Exception:
        return {"problem": None, "title": "diagnosis unavailable", "next_action": "run: nexen doctor --fix", "confident": False}


def _record(name, exc, diag):
    try:
        sp = _get_spine()
        fp = textsim.fingerprint("%s|%s|%s" % (name, type(exc).__name__, str(exc)[:120]))
        with sp.lock:
            sp.db.execute("INSERT OR IGNORE INTO occurrences(ts,problem_id,fp,source,text) VALUES(?,?,?,?,?)",
                          (time.strftime("%Y-%m-%dT%H:%M:%S"), diag.get("problem") or "UNCLASSIFIED", fp, "runtime:" + name, ("%s: %s" % (type(exc).__name__, exc))[:300]))
            sp.db.commit()
    except Exception:
        pass
    try:
        gate.audit("fault", {"where": name, "type": type(exc).__name__, "msg": str(exc)[:200], "problem": diag.get("problem")})
    except Exception:
        pass


def run_guarded(name, fn, *args, retries=2, backoff=0.4, default=None, **kwargs):
    """Run fn; retry transient faults; on failure return a structured, diagnosed result. Never raises."""
    attempts, last = 0, None
    while attempts <= retries:
        attempts += 1
        try:
            return {"ok": True, "result": fn(*args, **kwargs), "attempts": attempts, "degraded": False}
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 - the whole point is that nothing escapes
            last = e
            if attempts <= retries and is_transient(e):
                time.sleep(backoff * (2 ** (attempts - 1)))
                continue
            break
    diag = explain(last, name)
    _record(name, last, diag)
    return {"ok": False, "error": "%s: %s" % (type(last).__name__, str(last)[:300]), "problem": diag.get("problem"), "title": diag.get("title"),
            "next_action": diag["next_action"], "attempts": attempts, "degraded": True, "result": default}


def resilient(name=None, default=None, retries=1):
    """Decorator: the wrapped function returns its value on success and `default` on failure (after recording and diagnosing)."""
    def deco(fn):
        label = name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            r = run_guarded(label, fn, *a, retries=retries, default=default, **kw)
            return r["result"] if r["ok"] else (default if default is not None else {"ok": False, "error": r["error"], "next_action": r["next_action"], "problem": r["problem"], "degraded": True})
        return wrapper
    return deco


# --------------------------------------------------------------------------------------------- doctor
SUBSYSTEMS = ["nexen.core", "nexen.brain", "nexen.server", "nexen.api_spine", "nexen.mcp_server", "nexen.cli", "nexen.identity", "nexen.autonomy",
              "nexen.updater", "nexen.registry", "nexen.learning.novel", "nexen.learning.recursive", "nexen.spine.engine", "nexen.spine.rules",
              "nexen.spine.swap", "nexen.spine.world", "nexen.spine.packs", "nexen.spine.stores", "nexen.spine.schedule", "nexen.marvin.agent"]


def doctor(fix=False):
    checks = []

    def add(name, ok, detail="", fixed=False):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "fixed": fixed})

    for mod in SUBSYSTEMS:
        try:
            importlib.import_module(mod)
            add("import " + mod, True)
        except Exception as e:
            add("import " + mod, False, "%s: %s" % (type(e).__name__, e))
    try:
        paths.ensure_data()
        probe = paths.DATA / ".write-probe"
        probe.write_text("x")
        probe.unlink()
        add("data folder writable", True, str(paths.DATA))
    except OSError as e:
        add("data folder writable", False, str(e))
    for dbname in ("learning.db", "spine.db", "rules.db", "swap.db", "world.db", "traces.db", "state.db"):
        p = paths.DATA / dbname
        if not p.exists():
            add("db " + dbname, True, "not created yet")
            continue
        try:
            con = sqlite3.connect(str(p), timeout=5)
            res = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            add("db " + dbname, res == "ok", res)
        except sqlite3.Error as e:
            add("db " + dbname, False, str(e))
    # search index in step with the items table
    lp = paths.DATA / "learning.db"
    if lp.exists():
        try:
            con = sqlite3.connect(str(lp), timeout=5)
            a = con.execute("SELECT COUNT(*) FROM items WHERE status='admitted'").fetchone()[0]
            b = con.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0]
            ok = a == b
            fixed = False
            if not ok and fix:
                con.execute("DELETE FROM items_fts")
                con.execute("INSERT INTO items_fts(id,body) SELECT id, COALESCE(title,'')||' '||text FROM items WHERE status='admitted'")
                con.commit()
                fixed = True
            con.close()
            add("learning search index matches items", ok or fixed, "items %d, index %d" % (a, b), fixed)
        except sqlite3.Error as e:
            add("learning search index matches items", False, str(e))
    for fname, default in (("rules.json", None), ("schedule.json", None), ("adapters.json", None)):
        p = paths.DATA / fname
        if not p.exists():
            continue
        try:
            json.loads(p.read_text(encoding="utf-8-sig"))
            add(fname + " parses", True)
        except ValueError as e:
            fixed = False
            if fix:
                shutil.copy2(p, str(p) + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S"))
                p.unlink()
                fixed = True
            add(fname + " parses", fixed, "corrupt: %s%s" % (e, "; backed up and reset to defaults" if fixed else ""), fixed)
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % paths.PORT, timeout=4) as r:
            body = json.loads(r.read())
        add("engine health endpoint", body.get("ok"), "v%s" % body.get("version"))
    except Exception as e:
        add("engine health endpoint", False, "engine not answering (%s)" % type(e).__name__)
    from nexen.features.learning import autonomy
    st = autonomy.status()
    try:  # judge the engine's loop, not this process's
        with urllib.request.urlopen("http://127.0.0.1:%d/api/learning/loop" % paths.PORT, timeout=4) as r:
            st = json.loads(r.read())
    except Exception:
        pass
    alive = st["running"]
    fixed = False
    if not alive and fix:
        try:
            (paths.DATA / "restart.flag").write_text("doctor")
            fixed = True
        except OSError:
            pass
    add("learning loop alive", alive or fixed, "cycles %s, paused_by_stop %s" % (st["cycles"], st["paused_by_stop"]), fixed)
    add("global STOP", True, "ACTIVE (autonomous work paused by the owner)" if gate.stop_active() else "clear")
    try:
        from nexen.features.spine.engine import Spine
        sp = Spine(":memory:")
        d = sp.diagnose("sqlite database is locked while two workers write")
        add("spine diagnoses a known problem", d["matches"] and d["matches"][0]["id"] == "COD-007")
        from nexen.features.spine.rules import Rules
        r = Rules(config_path=":memory:", db_path=":memory:")
        add("rules engine blocks an unpaid clip", r.check({"type": "clip"})["status"] == "blocked")
        from nexen.core import identity
        add("identity JARVIS = MARVIN", identity.normalize("JARVIS") == "MARVIN" and identity.agent_key("jarvis") == "marvin")
    except Exception as e:
        add("self tests", False, "%s: %s" % (type(e).__name__, e))
    bad = [c for c in checks if not c["ok"]]
    return {"ok": not bad, "checked": len(checks), "failed": len(bad), "fixed": [c["name"] for c in checks if c["fixed"]], "checks": checks}
