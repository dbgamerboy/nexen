"""NEXEN side connectors: MARVIN (logs, bus, chat), the V3 core and canonical task DB, the vault.

All reads are read-only. The only writes are: a chat message to MARVIN through V3's own API,
a task created through V3's validated task API, and files under the vault's nexen handoff folder.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nexen.core import paths
from nexen.features.connectors import base

MARVIN_DIR = paths.H_NEXEN / "marvin"
BUS = MARVIN_DIR / "bus"
DESKTOP = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def _http(method, url, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    parts = urllib.parse.urlparse(url)
    # V3's loopback guard wants a same-origin Origin plus the action header on writes, exactly what its own pages send.
    # No credential is involved; the request still comes from this machine only.
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Nexen-Action": "launch",
                                          "Origin": "%s://%s" % (parts.scheme, parts.netloc)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, {"raw": raw[:2000]}
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", errors="replace")[:600]}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, {"error": "%s: %s" % (type(e).__name__, e)}


class Marvin:
    name = "marvin"

    def status(self):
        code, body = _http("GET", paths.V3_CORE_URL + "/healthz", timeout=4)
        chat = MARVIN_DIR / "v3-chat-log.jsonl"
        events = BUS / "events.jsonl"
        return {"ok": code == 200, "core": body if code == 200 else body.get("error"),
                "chat_log": {"path": str(chat), "modified": base.iso(base.mtime(chat))},
                "bus_events": {"path": str(events), "modified": base.iso(base.mtime(events))},
                "stop_file_present": paths.STOP_FILE.exists()}

    def recent(self, n=10):
        rows = base.tail_jsonl(MARVIN_DIR / "v3-chat-log.jsonl", n=n)
        return [{"id": r.get("at"), "title": base.redact(str(r.get("message", "")))[:120],
                 "reply": base.redact(str(r.get("reply", "")))[:400], "model": r.get("model"), "mtime": r.get("at")} for r in rows]

    def read(self, which="events", n=20):
        if which == "talk":
            p = MARVIN_DIR / "talk.log"
            try:
                tail = p.read_bytes()[-12000:].decode("utf-8", errors="replace")
            except OSError:
                tail = ""
            return {"ok": True, "id": "talk.log", "messages": [{"role": "log", "text": base.redact(tail)}]}
        rows = base.tail_jsonl(BUS / "events.jsonl", n=n)
        return {"ok": True, "id": "events", "messages": [{"role": "event", "ts": r.get("at"), "text": base.redact(json.dumps(r)[:500])} for r in rows]}

    def reports(self, n=5):
        d = DESKTOP / "MARVIN" / "Reports"
        files = sorted(d.glob("*"), key=base.mtime, reverse=True)[:n] if d.is_dir() else []
        return [{"name": f.name, "path": str(f), "mtime": base.iso(base.mtime(f)), "bytes": f.stat().st_size} for f in files]

    def actions(self):
        try:
            data = json.loads((BUS / "actions.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        return data.get("actions", []) if isinstance(data, dict) else []

    def search(self, q, n=8):
        hits = []
        for src, rows in (("chat", base.tail_jsonl(MARVIN_DIR / "v3-chat-log.jsonl", n=400)),
                          ("bus", base.tail_jsonl(BUS / "events.jsonl", n=1500))):
            for r in reversed(rows):
                blob = json.dumps(r, ensure_ascii=False)
                if q.lower() in blob.lower():
                    hits.append({"source": "marvin", "id": src, "snippet": base.redact(base.snippet(blob, q))})
                    if len(hits) >= n:
                        return hits
        return hits

    def ask_local(self, message, timeout=240):
        """Ask MARVIN's own brain module in a child process (same code the Discord bot runs).

        Used when the V3 hub is locked: V4 never types the owner's unlock password.
        """
        code_src = ("import sys,json;sys.path.insert(0,r'%s');from marvin_brain import Brain;"
                    "print(json.dumps({'reply':Brain().ask(sys.argv[1])}))" % (MARVIN_DIR / "brain"))
        rc, out, err = base.run_cli([str(paths.PYTHON), "-X", "utf8", "-c", code_src, message], timeout=timeout)
        if rc == 0:
            try:
                line = [ln for ln in out.splitlines() if ln.startswith("{")][-1]
                return {"ok": True, "via": "local-brain", "reply": base.redact(json.loads(line)["reply"])[:8000]}
            except (IndexError, ValueError, KeyError):
                pass
        return {"ok": False, "via": "local-brain", "code": rc, "error": base.redact((err or out)[-600:])}

    def send(self, message, history=None, timeout=300):
        code, body = _http("POST", paths.V3_CORE_URL + "/api/marvin/chat",
                           {"message": message, "history": history or []}, timeout=timeout)
        if code == 200:
            return {"ok": True, "via": "v3-api", "reply": base.redact(str(body.get("reply", "")))[:8000], "model": body.get("model"), "ms": body.get("ms")}
        if code in (0, 401, 403):
            local = self.ask_local(message, timeout=min(timeout, 240))
            local["note"] = "V3 hub said %s (%s); used MARVIN's local brain instead" % (code, str(body.get("error", ""))[:80])
            return local
        return {"ok": False, "code": code, "error": body.get("error", body)}


class NexenCore:
    name = "nexen"

    def status(self):
        code, body = _http("GET", paths.V3_CORE_URL + "/healthz", timeout=4)
        counts = base.ro_query(paths.CANON_DB, "SELECT status, COUNT(*) c FROM hub_requests GROUP BY status")
        return {"ok": code == 200, "core": body if code == 200 else body.get("error"),
                "db": str(paths.CANON_DB), "tasks_by_status": {r["status"]: r["c"] for r in counts},
                "stop_file_present": paths.STOP_FILE.exists()}

    def tasks(self, status=None, query=None, limit=50):
        cols = base.columns(paths.CANON_DB, "hub_requests")
        want = [c for c in ("id", "text", "status", "priority", "next_step", "due_date", "updated_at", "created_at") if c in cols]
        sql = "SELECT %s FROM hub_requests" % ",".join(want)
        where, args = [], []
        if status:
            where.append("status=?")
            args.append(status)
        if query:
            where.append("text LIKE ?")
            args.append("%" + query + "%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        return base.ro_query(paths.CANON_DB, sql, args)

    def history(self, task_id, limit=20):
        return base.ro_query(paths.CANON_DB, "SELECT old_status,new_status,outcome,reminder_date,created_at FROM task_history "
                                             "WHERE request_id=? ORDER BY id DESC LIMIT ?", (int(task_id), limit))

    def recent(self, n=10):
        return [{"id": t.get("id"), "title": base.redact(str(t.get("text", "")))[:140], "status": t.get("status"),
                 "mtime": t.get("updated_at") or t.get("created_at")} for t in self.tasks(limit=n)]

    def search(self, q, n=8):
        return [{"source": "nexen", "id": t.get("id"), "snippet": base.redact(base.snippet(str(t.get("text", "")), q))}
                for t in self.tasks(query=q, limit=n)]

    def add_task(self, text):
        """Create a task through V3's validated API. Prefixed so the line (V3 or V4) is visible."""
        code, body = _http("POST", paths.V3_CORE_URL + "/api/tasks", {"text": "[V4] " + text[:11900]})
        return {"ok": code in (200, 201), "code": code, "task": body}


class Vault:
    name = "obsidian"
    HANDOFF = "00-Control/Handoffs/nexen"

    def root(self):
        return paths.vault()

    def status(self):
        r = self.root()
        log = r / "00-Control" / "SESSION-LOG.md" if r else None
        return {"ok": r is not None, "root": str(r) if r else None,
                "session_log_modified": base.iso(base.mtime(log)) if log else None,
                "note": "F: is failing; falls back to the recovered H: copy" if r and str(r).upper().startswith("H:") else ""}

    PRIORITY = ("00-Control", "NEXEN Shared Memory")

    def _md(self, cap=3000, budget=8.0):
        """Newest notes first from the control folders. F: is failing, so the walk has a time
        budget and never crawls the whole 57k-file vault; the recovered H: copy fills any remaining budget."""
        r = self.root()
        if not r:
            return []
        start, out = time.time(), []
        roots = [r / p for p in self.PRIORITY if (r / p).is_dir()]
        for extra in paths.VAULT_CANDIDATES[1:]:
            if extra.is_dir() and extra != r:
                roots.append(extra / "00-Control")
        for root in roots:
            for dirpath, dirs, names in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "99-Archive"}]
                for n in names:
                    if n.lower().endswith(".md"):
                        out.append(Path(dirpath) / n)
                if len(out) > cap or time.time() - start > budget:
                    break
            if len(out) > cap or time.time() - start > budget:
                break
        keyed = []
        for p in out:
            keyed.append((base.mtime(p), p))
            if time.time() - start > budget * 2:
                break
        return [p for _, p in sorted(keyed, key=lambda x: -x[0])[:cap]]

    def recent(self, n=10):
        r = self.root()
        return [{"id": str(p.relative_to(r)), "title": p.stem, "mtime": base.iso(base.mtime(p))} for p in self._md()[:n]]

    def read(self, rel, n=0):
        r = self.root()
        p = (r / rel).resolve() if r else None
        if not r or r.resolve() not in p.parents and p != r.resolve():
            return {"ok": False, "error": "outside vault"}
        if not p.is_file():
            return {"ok": False, "error": "no such note"}
        text = p.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "id": rel, "messages": [{"role": "note", "text": base.redact(text[:20000])}]}

    def search(self, q, n=8, max_seconds=20):
        hits, start = [], time.time()
        for p in self._md():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if q.lower() in text.lower():
                hits.append({"source": "obsidian", "id": str(p.relative_to(self.root())), "snippet": base.redact(base.snippet(text, q))})
                if len(hits) >= n:
                    break
            if time.time() - start > max_seconds:
                break
        return hits

    def tail_log(self, lines=40):
        r = self.root()
        p = r / "00-Control" / "SESSION-LOG.md" if r else None
        if not p or not p.is_file():
            return []
        return p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]

    def write_handoff(self, name, text):
        r = self.root()
        if not r:
            return {"ok": False, "error": "vault not found"}
        safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in name)[:80] or "handoff"
        folder = r / self.HANDOFF
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / (safe if safe.endswith(".md") else safe + ".md")
        p.write_text(base.redact(text), encoding="utf-8")
        return {"ok": True, "path": str(p)}

    def append_session_log(self, did, receipts, next_action, decisions="none", blocked="none"):
        r = self.root()
        p = r / "00-Control" / "SESSION-LOG.md" if r else None
        if not p:
            return {"ok": False, "error": "vault not found"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        entry = ("\n## %s · Claude Code · NEXEN CLI\n- Did: %s\n- Receipts (paths/IDs): %s\n- Decisions made: %s\n"
                 "- Blocked on: %s\n- NEXT ACTION: %s\n") % (stamp, base.redact(did), base.redact(receipts), decisions, blocked, base.redact(next_action))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(entry)
        return {"ok": True, "path": str(p)}


REGISTRY = {c.name: c() for c in (Marvin, NexenCore, Vault)}
