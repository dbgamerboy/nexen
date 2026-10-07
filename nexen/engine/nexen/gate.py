"""Approval gate. Two tiers decide what runs without a human.

INTERNAL work runs without anyone: reading, indexing, learning, tests, building, writing under V4's
own data folder and the vault's nexen handoff folder. This is the human-out-of-the-loop lane.

EXTERNAL effects never run from here: publish, send a message to a person, spend or buy, accept
terms, enter credentials, delete data, change accounts. They become queued approval requests with
the exact payload hashed. The owner's own decisions (default-deny gate, exact-action approvals) and
the global STOP marker stay binding.
"""
import hashlib
import json
import sqlite3
import threading
import time

from . import paths

INTERNAL = {"read", "search", "learn", "recall", "index", "test", "build", "status", "plan", "write_v4", "handoff"}
EXTERNAL = {"publish", "send_message", "spend", "purchase", "accept_terms", "enter_credentials", "delete",
            "account_change", "post", "payout", "external_api_write"}

_lock = threading.RLock()


def _db():
    paths.ensure_data()
    con = sqlite3.connect(paths.STATE_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, ts REAL, kind TEXT, title TEXT,
                   payload TEXT, digest TEXT, status TEXT, decided REAL, note TEXT)""")
    return con


def stop_active():
    return paths.STOP_FILE.exists()


def audit(kind, detail):
    paths.ensure_data()
    with open(paths.AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, **detail}, default=str) + "\n")


def check(kind, title="", payload=None, autonomous=False):
    """Return {allowed, reason, approval_id?}. Autonomous callers are also blocked by STOP."""
    if autonomous and stop_active():
        audit("blocked_stop", {"action": kind})
        return {"allowed": False, "reason": "global STOP is active; autonomous work is paused"}
    if kind in INTERNAL:
        return {"allowed": True, "reason": "internal action"}
    if kind in EXTERNAL or kind not in INTERNAL:
        body = json.dumps(payload or {}, sort_keys=True, default=str)
        digest = hashlib.sha256((kind + "\n" + title + "\n" + body).encode()).hexdigest()
        ident = digest[:16]
        with _lock:
            con = _db()
            try:
                row = con.execute("SELECT status FROM approvals WHERE id=?", (ident,)).fetchone()
                if row is None:
                    con.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?)",
                                (ident, time.time(), kind, title[:300], body[:20000], digest, "pending", None, ""))
                    con.commit()
                    audit("approval_queued", {"id": ident, "kind": kind, "title": title})
                    return {"allowed": False, "reason": "external effect: queued for owner approval", "approval_id": ident}
                if row["status"] == "approved":
                    return {"allowed": True, "reason": "exact payload approved by owner", "approval_id": ident}
                return {"allowed": False, "reason": "approval is %s" % row["status"], "approval_id": ident}
            finally:
                con.close()


def pending():
    with _lock:
        con = _db()
        try:
            return [dict(r) for r in con.execute("SELECT * FROM approvals WHERE status='pending' ORDER BY ts")]
        finally:
            con.close()


def decide(ident, approve, note=""):
    with _lock:
        con = _db()
        try:
            cur = con.execute("UPDATE approvals SET status=?, decided=?, note=? WHERE id=? AND status='pending'",
                              ("approved" if approve else "denied", time.time(), note, ident))
            con.commit()
            audit("approval_decided", {"id": ident, "approved": bool(approve)})
            return cur.rowcount == 1
        finally:
            con.close()
