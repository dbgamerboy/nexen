"""Every memory pool, vector store and knowledge source behind one fan-out.

Adapters are time-boxed and independent: a dead store is reported as unavailable, never as empty and never as a crash.
Sources: V4 ledger (Novel Learning), spine playbooks and failures, the seven V3 memory pools (read-only child process),
vault control notes, Hermes, Codex, Claude Code, Antigravity, ChatGPT exports, MARVIN logs, world snapshots,
and Qdrant / Milvus when they are running.
"""
import json
import threading
import time
import urllib.request

from .. import paths, textsim
from ..connectors import base
from ..connectors.agents import REGISTRY as AGENTS
from ..connectors.nexen import REGISTRY as NEXEN

V3_POOLS = ["commerce", "music", "life", "game", "voice", "automation", "engineering"]


class Stores:
    def __init__(self, app, spine, world=None, embedder=None):
        self.app, self.spine, self.world, self.embedder = app, spine, world, embedder
        self.adapters = {
            "v4-ledger": self._ledger, "spine": self._spine, "failures": self._failures, "world": self._world,
            "v3-pools": self._v3_pool, "vault": self._conn("obsidian"), "marvin": self._conn("marvin"),
            "hermes": self._conn("hermes"), "codex": self._conn("codex"), "claude": self._conn("claude"),
            "antigravity": self._conn("antigravity"), "chatgpt": self._conn("chatgpt"), "tasks": self._conn("nexen"),
            "qdrant": self._qdrant,
        }

    # ------------------------------------------------------------------ adapters: each returns (hits, status)
    def _conn(self, name):
        c = {**AGENTS, **NEXEN}[name]

        def run(q, k, **kw):
            rows = c.search(q, k)
            return [{"store": name, "id": str(r.get("id", "")), "text": r.get("snippet", ""), "score": 0.3, "trust": 0.35} for r in rows], "ok"
        return run

    def _ledger(self, q, k, **kw):
        rows = self.app.novel.recall(q, k=k, domain=kw.get("domain"))
        return [{"store": "v4-ledger", "id": r["id"], "text": r["text"], "score": r["score"], "trust": r["trust"], "sources": r["source_ids"][:2]} for r in rows], "ok"

    def _spine(self, q, k, **kw):
        d = self.spine.diagnose(q, k=k)
        out = []
        for m in d["matches"]:
            p = self.spine.problems[m["id"]]
            out.append({"store": "spine", "id": m["id"], "text": "%s. Do: %s Verify: %s" % (p["title"], " ".join(p["playbooks"][0]["steps"][:3]), p["playbooks"][0]["verify"][0]),
                        "score": m["score"], "trust": 0.9})
        return out, "ok"

    def _failures(self, q, k, **kw):
        from .failures import similar
        return [{"store": "failures", "id": r.get("problem_id") or "unclassified", "text": r["text"], "score": 0.4, "trust": 0.7} for r in similar(self.spine, q, k)], "ok"

    def _world(self, q, k, **kw):
        if self.world is None:
            return [], "not-configured"
        return [{"store": "world", "id": r["id"], "text": r["text"], "score": r["score"], "trust": 0.5} for r in self.world.relevant(q, k)], "ok"

    def _v3_pool(self, q, k, **kw):
        """Run V3's own memory_runtime.context_for in a child process, read-only, with a deadline."""
        pool = kw.get("pool")
        src = ("import sys,json;sys.path.insert(0,r'%s');import os;os.chdir(r'%s');from memory_runtime import context_for;"
               "p=context_for(sys.argv[1],task_type='code',pool=(sys.argv[2] or None),max_chars=6000,limit=%d);"
               "print('@@'+json.dumps({'cit':p.get('citations',[]),'pool':p.get('pool')},default=str))" % (paths.V3_APP, paths.V3_APP, k))
        rc, out, err = base.run_cli([str(paths.PYTHON), "-X", "utf8", "-c", src, q[:1500], pool or ""], timeout=40)
        if rc != 0:
            return [], "error: " + base.redact((err or out)[-160:]).replace("\n", " ")
        try:
            data = json.loads([l for l in out.splitlines() if l.startswith("@@")][-1][2:])
        except (IndexError, ValueError):
            return [], "error: no packet"
        label = (data.get("pool") or {}).get("label") if isinstance(data.get("pool"), dict) else None
        return [{"store": "v3-pools" + (":" + pool if pool else ""), "id": str(c.get("source_id", c.get("id", ""))), "text": base.redact(str(c.get("text") or c.get("excerpt") or c.get("title", "")))[:900],
                 "score": 0.5, "trust": 0.6, "pool": label} for c in data["cit"]], "ok"

    def _qdrant(self, q, k, **kw):
        try:
            urllib.request.urlopen("http://127.0.0.1:6333/collections", timeout=2).read(50)
        except Exception as e:
            return [], "down (%s): collection enterprise_knowledge not served" % type(e).__name__
        vec = self.embedder.vector(q) if self.embedder else None
        if not vec:
            return [], "up but no embedding available (Ollama slow)"
        body = json.dumps({"vector": vec, "limit": k, "with_payload": True}).encode()
        req = urllib.request.Request("http://127.0.0.1:6333/collections/enterprise_knowledge/points/search", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                res = json.loads(r.read()).get("result", [])
        except Exception as e:
            return [], "error: %s" % type(e).__name__
        return [{"store": "qdrant", "id": str(h.get("id")), "text": str((h.get("payload") or {}).get("text_content", ""))[:900], "score": h.get("score", 0), "trust": 0.5} for h in res], "ok"

    # ------------------------------------------------------------------ fan-out
    def health(self):
        out = {}
        for name in self.adapters:
            out[name] = "configured"
        try:
            urllib.request.urlopen("http://127.0.0.1:6333/collections", timeout=2).read(10)
            out["qdrant"] = "up"
        except Exception:
            out["qdrant"] = "down"
        out["milvus"] = "no live endpoint found (V3 notes mention a local adapter; not running)"
        return out

    def fanout(self, query, stores=None, k=4, pool=None, domain=None, timeout=45):
        stores = stores or list(self.adapters)
        results, status = {}, {}

        def run(name):
            try:
                hits, st = self.adapters[name](query, k, pool=pool, domain=domain)
                results[name], status[name] = hits, st
            except Exception as e:
                results[name], status[name] = [], "error: %s: %s" % (type(e).__name__, str(e)[:100])
        threads = []
        for name in stores:
            if name in self.adapters:
                t = threading.Thread(target=run, args=(name,), daemon=True)
                t.start()
                threads.append((name, t))
        end = time.time() + timeout
        for name, t in threads:
            t.join(max(0.1, end - time.time()))
            if t.is_alive():
                status[name] = "timeout"
        merged, seen = [], set()
        for name in stores:
            for h in results.get(name, []):
                fp = textsim.fingerprint(h["text"][:300])
                if fp in seen or not h["text"].strip():
                    continue
                seen.add(fp)
                merged.append(h)
        merged.sort(key=lambda h: -(0.6 * float(h.get("score", 0)) + 0.4 * float(h.get("trust") or 0.3)))
        used = {n: len(results.get(n, [])) for n in stores}
        return {"hits": merged, "status": status, "used": used, "unavailable": [n for n, s in status.items() if s != "ok"]}
