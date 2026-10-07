"""Local HTTP app for NEXEN. Binds 127.0.0.1 only. Every POST needs the X-Nexen-Action: v4 header."""
import json
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import VERSION, autonomy, gate, paths, registry, updater
from .connectors import base
from .core import CONNECTORS, get_app

MAX_BODY = 1_000_000


def all_buttons():
    out = []
    for m in registry.all_modules(with_probe=False):
        for b in m.get("buttons", []):
            out.append({**b, "module": m["id"], "group": b.get("group") or m["name"]})
    for b in registry.bizops_buttons():
        out.append({**b, "module": "bizops"})
    try:
        for b in registry.marvin_buttons():
            out.append({**b, "module": "marvin"})
    except Exception:
        pass
    return out


def view(target):
    app = get_app()
    if target == "marvin:talk":
        return CONNECTORS["marvin"].read("talk")
    if target == "vault:log":
        return {"lines": CONNECTORS["obsidian"].tail_log(60)}
    if target == "learning:gaps":
        return app.novel.gaps()
    if target == "learning:archive":
        return app.novel.archive()
    if target == "bizops:inventory":
        try:
            data = json.loads((paths.BIZ_INVENTORY / "PROGRAM-INVENTORY.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {"error": "inventory not readable", "path": str(paths.BIZ_INVENTORY)}
        decisions = {}
        try:
            decisions = json.loads(Path(r"H:\NEXEN-VideoStudio\_engine\button-box-owner-review.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        rows = [{"name": e.get("name"), "group": e.get("group"), "status": e.get("status"), "purpose": (e.get("purpose") or "")[:140], "path": e.get("path")}
                for e in data.get("entries", []) if isinstance(e, dict)]
        return {"count": len(rows), "owner_decisions_recorded": len(decisions), "entries": rows}
    if target.startswith("workflows:"):
        section = target.split(":", 1)[1]
        try:
            sections = json.loads((paths.BIZ_OPS / "app" / "workflow_sections.json").read_text(encoding="utf-8-sig"))["sections"]
        except (OSError, ValueError, KeyError):
            return {"error": "workflow sections unreadable"}
        sec = next((s for s in sections if s["name"] == section), None)
        if not sec:
            return {"error": "unknown section"}
        wf_dir = paths.H_NEXEN / "n8n-organized"
        matches = []
        if wf_dir.is_dir():
            for p in wf_dir.rglob("*.json"):
                name = p.name.lower()
                if any(k.lower() in name for k in sec["keywords"]):
                    matches.append(str(p.relative_to(wf_dir)))
                if len(matches) >= 40:
                    break
        return {"section": section, "matches": matches,
                "note": "keyword matches on file names; review, not proven" if matches else sec.get("placeholder")}
    if target.startswith("file:"):
        p = Path(target[5:])
        if not registry.is_trusted(p) or not p.is_file() or p.stat().st_size > 2_000_000:
            return {"error": "file is outside trusted roots or too large"}
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        try:
            return json.loads(text)
        except ValueError:
            return {"text": base.redact(text[:20000])}
    return {"error": "unknown view target"}


class Handler(BaseHTTPRequestHandler):
    server_version = "NexenV4/" + VERSION

    def log_message(self, fmt, *args):
        pass

    # helpers
    def _json(self, obj, code=200):
        try:
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the client went away; the engine keeps serving everyone else

    def _fault(self, exc, where):
        """A handler crashed: diagnose it, record it, answer with JSON that says what to do next. The server stays up."""
        from . import reliability
        d = reliability.explain(exc, where)
        reliability._record(where, exc, d)
        return self._json({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "problem": d.get("problem"), "title": d.get("title"),
                           "next_action": d["next_action"], "degraded": True}, 500)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in {"127.0.0.1", "localhost"}

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path.startswith("/api/"):
                return self._json(self.api_get(u.path, q))
            return self.static(u.path)
        except KeyError as e:
            return self._json({"error": str(e)}, 404)
        except Exception as e:
            return self._fault(e, "GET " + u.path)

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Nexen-Action") != "v4":
            return self._json({"error": "missing X-Nexen-Action: v4 or bad host"}, 403)
        try:
            body = self._body()
            return self._json(self.api_post(urlparse(self.path).path, body))
        except (ValueError, KeyError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            return self._fault(e, "POST " + urlparse(self.path).path)

    # static
    def static(self, path):
        rel = "index.html" if path in {"", "/"} else path.lstrip("/")
        p = (paths.UI / rel).resolve()
        if paths.UI.resolve() not in p.parents or not p.is_file():
            return self._json({"error": "not found"}, 404)
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(str(p))[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # api
    def api_get(self, path, q):
        app = get_app()
        n = int(q.get("n", 10))
        if path == "/api/health":
            autonomy.ensure_alive(app)  # a dead learning loop is restarted by the next health probe
            return {"ok": True, "version": VERSION, "stamp": updater.stamp(), "stop": gate.stop_active()}
        if path == "/api/doctor":
            from . import reliability
            return reliability.doctor(fix=q.get("fix") == "1")
        if path == "/api/status":
            return {**app.status_all(), "loop": autonomy.status()}
        if path == "/api/modules":
            return registry.all_modules()
        if path == "/api/action-runs":
            from . import actions
            return actions.recent()
        if path == "/api/buttons":
            return all_buttons()
        if path == "/api/census":
            return registry.f_census()
        if path == "/api/timeline":
            return app.timeline(n)
        if path == "/api/board":
            return app.board()
        if path == "/api/approvals":
            return gate.pending()
        if path == "/api/update":
            return updater.status()
        if path == "/api/view":
            return view(q.get("target", ""))
        m = re.fullmatch(r"/api/learning/(\w+)", path)
        if m:
            what = m.group(1)
            table = {"stats": app.ledger.stats, "gaps": app.novel.gaps, "archive": app.novel.archive, "skills": app.ledger.skills,
                     "lessons": lambda: app.ledger.lessons(limit=n), "frontier": lambda: app.ledger.frontier(n), "events": lambda: app.ledger.recent_events(n),
                     "held": lambda: [dict(id=r["id"], text=r["text"][:200], domain=r["domain"]) for r in
                                      app.ledger.db.execute("SELECT id,text,domain FROM items WHERE status='held' ORDER BY created_at DESC LIMIT 50")],
                     "recent": lambda: [dict(id=r["id"], text=r["text"][:260], domain=r["domain"], trust=r["trust"], status=r["status"]) for r in
                                        app.ledger.db.execute("SELECT id,text,domain,trust,status FROM items WHERE status IN ('admitted','superseded') ORDER BY created_at DESC LIMIT ?", (n,))],
                     "loop": autonomy.status}
            if what in table:
                return table[what]()
            raise KeyError("unknown learning view")
        m = re.fullmatch(r"/api/connector/(\w+)/(\w+)", path)
        if m:
            c = app.conn(m.group(1))
            verb, arg = m.group(2), q.get("q", "")
            if verb == "status":
                return c.status()
            if verb == "recent":
                return c.recent(n)
            if verb == "search":
                return c.search(arg, n)
            if verb == "read":
                return c.read(arg, n) if m.group(1) != "obsidian" else c.read(arg)
            if verb == "tasks" and m.group(1) == "nexen":
                return c.tasks(status=q.get("status"), query=arg or None, limit=n)
            raise KeyError("unknown connector verb")
        from . import api_spine
        r = api_spine.get(path, q)
        if r is not api_spine.NOT_HANDLED:
            return r
        raise KeyError("unknown endpoint")

    def api_post(self, path, b):
        app = get_app()
        from . import api_spine
        r = api_spine.post(path, b)
        if r is not api_spine.NOT_HANDLED:
            return r
        if path == "/api/learning/novel":
            gate_ok = gate.check("learn", "novel ingest")
            if not gate_ok["allowed"]:
                return gate_ok
            return app.novel.ingest({"text": b.get("text", ""), "source_ids": b.get("source_ids") or [], "title": b.get("title", ""),
                                     "origin": "owner" if b.get("owner") else None})
        if path == "/api/learning/recall":
            return app.novel.recall(b.get("query", ""), k=int(b.get("k", 5)), as_of=b.get("as_of"))
        if path == "/api/learning/recursive":
            qs = [b["question"]] if b.get("question") else None
            return app.learn_recursive(questions=qs, strategy=b.get("strategy"), seconds=int(b.get("seconds", 25)))
        if path == "/api/learning/harvest":
            src = b.get("from", "vault")
            return app.harvest_vault() if src == "vault" else (app.harvest_brain_index() if src == "brain-index" else app.harvest_agent(src))
        if path == "/api/learning/cycle":
            return autonomy.cycle(app, deep=True)
        if path == "/api/learning/tune":
            return app.tune()
        if path == "/api/learning/rollback":
            return app.tuner.rollback()
        if path == "/api/learning/feedback":
            app.novel.feedback(b["id"], bool(b.get("good")), b.get("note", ""))
            return {"ok": True}
        if path == "/api/learning/release":
            return app.novel.release(b["id"])
        if path == "/api/context":
            r = app.context_pack(b.get("topic", ""), b.get("sources") or None, int(b.get("n", 4)))
            return {"path": r["path"], "text": r["text"], "counts": r["counts"]}
        m = re.fullmatch(r"/api/connector/(\w+)/send", path)
        if m:
            c = app.conn(m.group(1))
            if m.group(1) == "chatgpt":
                return c.packet(b.get("prompt", ""), b.get("title", "packet"))
            if not hasattr(c, "send"):
                raise KeyError("this connector has no send channel")
            return c.send(b.get("prompt", ""))
        if path == "/api/launch":
            # only targets that exist on a registered button can be launched
            for btn in all_buttons():
                if btn.get("kind") == b.get("kind") and btn.get("target") == b.get("target") and btn["kind"] in {"url", "script", "folder", "file"}:
                    return registry.launch(btn["kind"], btn["target"])
            return {"ok": False, "error": "target is not on a registered button"}
        if path == "/api/marvin-action":
            from . import actions
            return actions.request(b.get("id", ""), b.get("inputs") or {}, source="ui", confirmed=bool(b.get("confirmed")))
        m = re.fullmatch(r"/api/approvals/(\w+)/(approve|deny)", path)
        if m:
            return {"ok": gate.decide(m.group(1), m.group(2) == "approve", b.get("note", ""))}
        if path == "/api/update/apply":
            return updater.apply(b["name"])
        if path == "/api/task":
            return CONNECTORS["nexen"].add_task(b.get("text", ""))
        raise KeyError("unknown endpoint")


def serve(port=None, loop=True):
    port = port or paths.PORT
    paths.ensure_data()
    app = get_app()
    if loop:
        autonomy.start(app)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("NEXEN %s on http://127.0.0.1:%d (learning loop %s)" % (VERSION, port, "on" if loop else "off"), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        autonomy.stop()
        httpd.server_close()
