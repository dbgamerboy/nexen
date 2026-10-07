"""The one facade the CLI, HTTP server, MCP server and UI all call."""
import json
import threading
import time
from pathlib import Path

from . import VERSION, gate, paths, registry, textsim
from .connectors import agents, base, nexen
from .learning.ledger import Ledger
from .learning.meta import SelfTuner
from .learning.novel import NovelLearner
from .learning.recursive import LocalCorpusProvider, RecursiveLearner

_app = None
_app_lock = threading.Lock()

CONNECTORS = {**agents.REGISTRY, **nexen.REGISTRY}


def get_app():
    global _app
    with _app_lock:
        if _app is None:
            paths.ensure_data()
            _app = App(Ledger(paths.LEARNING_DB))
        return _app


class App:
    def __init__(self, ledger):
        self.ledger = ledger
        self.novel = NovelLearner(ledger)
        self.recursive = RecursiveLearner(self.novel)
        self.tuner = SelfTuner(ledger)

    # connectors -------------------------------------------------------------------
    def conn(self, name):
        if name not in CONNECTORS:
            raise KeyError("unknown connector %r; choose from %s" % (name, ", ".join(sorted(CONNECTORS))))
        return CONNECTORS[name]

    def status_all(self):
        out, threads = {}, []

        def run(name, c):
            try:
                out[name] = c.status()
            except Exception as e:
                out[name] = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        for name, c in CONNECTORS.items():
            t = threading.Thread(target=run, args=(name, c), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(8)
        return {"version": VERSION, "stop_active": gate.stop_active(), "connectors": out,
                "learning": self.ledger.stats(), "approvals_pending": len(gate.pending()),
                "time": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # context packs --------------------------------------------------------------------
    def context_pack(self, topic, sources=None, n=4, save=True):
        sources = sources or [s for s in CONNECTORS if s not in {"marvin"}] + ["marvin"]
        found, threads = {}, []

        def run(name):
            try:
                found[name] = CONNECTORS[name].search(topic, n)
            except Exception as e:
                found[name] = [{"source": name, "error": "%s: %s" % (type(e).__name__, e)}]
        for s in sources:
            if s in CONNECTORS and hasattr(CONNECTORS[s], "search"):
                t = threading.Thread(target=run, args=(s,), daemon=True)
                t.start()
                threads.append(t)
        for t in threads:
            t.join(40)
        recalled = self.novel.recall(topic, k=n)
        lines = ["# NEXEN context pack", "", "Topic: %s" % topic, "Built: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
                 "Credential shapes and LAN addresses are redacted. Chat hits are unverified claims; learned items carry trust scores.", ""]
        if recalled:
            lines.append("## Learned (V4 ledger)")
            for r in recalled:
                lines.append("- [%s trust %.2f, %d source(s)] %s" % (r["id"], r["trust"] or 0, r["evidence_n"], r["text"][:400].replace("\n", " ")))
            lines.append("")
        for name in sources:
            hits = found.get(name) or []
            lines.append("## %s (%d)" % (name, len(hits)))
            for h in hits:
                if "error" in h:
                    lines.append("- unavailable: %s" % h["error"])
                else:
                    lines.append("- `%s` %s" % (h.get("id", ""), (h.get("snippet") or "").replace("\n", " ")))
            lines.append("")
        text = "\n".join(lines)
        path = None
        if save:
            folder = paths.DATA / "packs"
            folder.mkdir(parents=True, exist_ok=True)
            slug = "".join(c if c.isalnum() else "-" for c in topic.lower())[:40].strip("-") or "pack"
            path = folder / ("%s-%s.md" % (time.strftime("%Y%m%d-%H%M%S"), slug))
            path.write_text(text, encoding="utf-8")
        return {"path": str(path) if path else None, "text": text,
                "counts": {k: len(v) for k, v in found.items()}, "learned": len(recalled)}

    # harvesting into Novel Learning --------------------------------------------------------
    def harvest_agent(self, name, sessions=3, per_session=12, min_chars=140):
        c = self.conn(name)
        cands = []
        for rec in c.recent(sessions):
            data = c.read(rec["id"], n=40) if name != "marvin" else {"messages": []}
            for m in data.get("messages", []):
                if m.get("role") == "assistant":
                    for _, body in textsim.paragraphs(m["text"], min_chars=min_chars):
                        cands.append({"text": body, "source_ids": ["chat:%s:%s" % (name, rec["id"])], "origin": "harvest",
                                      "observed_at": str(m.get("ts") or "")[:19] or None})
        return self._ingest_many([c_ for c_ in cands[: sessions * per_session] if c_.get("observed_at") != ""], "harvest:" + name)

    def harvest_vault(self, max_files=25, max_passages=60):
        v = paths.vault()
        if not v:
            return {"ok": False, "error": "no vault"}
        files = nexen.REGISTRY["obsidian"]._md(cap=3000)
        prefer = [f for f in files if any(k in str(f) for k in ("Handoffs", "SESSION-LOG", "Current Decisions", "learned"))]
        cands, touched = [], 0
        for f in prefer[:max_files]:
            try:
                raw = f.read_bytes()[:300_000]
            except OSError:
                continue
            import hashlib
            sha = hashlib.sha256(raw).hexdigest()[:10]
            seen = self.ledger.seen(str(f))
            if seen and seen["sha"] == sha:
                continue
            touched += 1
            made = 0
            for heading, body in textsim.paragraphs(raw.decode("utf-8", errors="replace")):
                cands.append({"text": base.redact(body), "title": heading,
                              "source_ids": ["file:%s#%s@%s" % (f.name, (heading or "top")[:30].replace(" ", "_"), sha)], "origin": "vault"})
                made += 1
                if len(cands) >= max_passages:
                    break
            self.ledger.mark_seen(str(f), sha, base.mtime(f), made)
            if len(cands) >= max_passages:
                break
        res = self._ingest_many(cands, "harvest:vault")
        res["files_read"] = touched
        return res

    def harvest_brain_index(self, max_files=30, max_passages=80):
        """Feed the old continuous-learning watcher's queue into the real gate.

        H:/NEXEN/tools/continuous_learning_watcher.py only logs file metadata to
        Marvin_Brain_Index.json as ready_for_marvin_review. It never reads or judges content.
        V4 reads that index (never edits it) and runs each file's passages through Novel Learning.
        """
        index = Path(r"H:\NEXEN_MEMORY\Marvin_Brain_Index.json")
        try:
            chunks = json.loads(index.read_text(encoding="utf-8-sig")).get("knowledge_chunks", [])
        except (OSError, ValueError):
            return {"ok": False, "error": "Marvin_Brain_Index.json not readable", "path": str(index)}
        import hashlib
        cands, files = [], 0
        for ch in chunks:
            fp = Path(ch.get("file_path", ""))
            if ch.get("status") != "ready_for_marvin_review" or fp.suffix.lower() not in {".md", ".txt"} or not fp.is_file():
                continue
            raw = fp.read_bytes()[:300_000]
            sha = hashlib.sha256(raw).hexdigest()[:10]
            seen = self.ledger.seen(str(fp))
            if seen and seen["sha"] == sha:
                continue
            files += 1
            for heading, body in textsim.paragraphs(raw.decode("utf-8", errors="replace")):
                cands.append({"text": base.redact(body), "title": heading, "origin": "brain-index",
                              "source_ids": ["file:%s#%s@%s" % (fp.name, (heading or "top")[:30].replace(" ", "_"), sha)]})
            self.ledger.mark_seen(str(fp), sha, base.mtime(fp), len(cands))
            if files >= max_files or len(cands) >= max_passages:
                break
        res = self._ingest_many(cands[:max_passages], "harvest:brain-index")
        res["files_read"] = files
        return res

    def _ingest_many(self, cands, label):
        counts = {}
        for cand in cands:
            r = self.novel.ingest(cand)
            counts[r["op"]] = counts.get(r["op"], 0) + 1
        self.ledger.event("harvest", None, {"label": label, "counts": counts})
        return {"ok": True, "label": label, "candidates": len(cands), "ops": counts}

    # recursive learning -------------------------------------------------------------------------
    def recursive_provider(self, roots=None):
        if roots is None:
            v = paths.vault()
            # healthy H: folders first; the failing F: vault last so its slow reads cannot starve the budget
            roots = [p for p in (paths.KNOWLEDGE / "learned", paths.KNOWLEDGE / "study-notes", paths.DATA / "datasets" / "corpus", paths.HANDOFFS,
                                 v / "00-Control" / "Handoffs" if v else None) if p and Path(p).is_dir()]
        return LocalCorpusProvider(roots, max_files=500)

    def learn_recursive(self, questions=None, strategy=None, seconds=30, roots=None):
        check = gate.check("learn", "recursive run")
        if not check["allowed"]:
            return {"ok": False, **check}
        return self.recursive.run(questions=questions, strategy=strategy, max_seconds=seconds, provider=self.recursive_provider(roots))

    def tune(self):
        return self.tuner.tune()

    # tracking ----------------------------------------------------------------------------------------
    def timeline(self, n=40):
        items = []
        v = paths.vault()
        if v:
            log = v / "00-Control" / "SESSION-LOG.md"
            try:
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("## "):
                        items.append({"kind": "session", "when": line[3:60], "title": line[3:].strip()[:160], "source": "SESSION-LOG"})
            except OSError:
                pass
        led = paths.KNOWLEDGE / "KNOWLEDGE-LEDGER.jsonl"
        for row in base.tail_jsonl(led, n=n, max_bytes=400_000):
            items.append({"kind": "knowledge", "when": row.get("t"), "title": "[%s] %s" % (row.get("agent"), row.get("title")),
                          "source": "KNOWLEDGE-LEDGER", "topic": row.get("topic")})
        for t in nexen.REGISTRY["nexen"].tasks(limit=n):
            items.append({"kind": "task", "when": t.get("created_at"), "title": "#%s [%s] %s" % (t.get("id"), t.get("status"), str(t.get("text", ""))[:120]),
                          "source": "canonical tasks"})
        for e in self.ledger.recent_events(limit=n):
            items.append({"kind": "learning", "when": e["ts"], "title": "%s %s" % (e["kind"], (e["detail"] or "")[:100]), "source": "V4 ledger"})
        items.sort(key=lambda r: str(r.get("when") or ""), reverse=True)
        return items[: n * 2]

    def board(self):
        by = {r["status"]: r["c"] for r in base.ro_query(paths.CANON_DB, "SELECT status, COUNT(*) c FROM hub_requests GROUP BY status")}
        return {"tasks": by, "total": sum(by.values()), "open": sum(v for k, v in by.items() if k != "done")}


# Every public App method that touches the outside world or a store is wrapped: it retries transient faults, records and
# diagnoses real ones, and returns a structured result (or a safe default) instead of raising into a loop or a handler.
from . import reliability as _rel  # noqa: E402

for _name, _default in (("status_all", None), ("context_pack", None), ("harvest_agent", None), ("harvest_vault", None), ("harvest_brain_index", None),
                        ("learn_recursive", None), ("tune", None), ("timeline", []), ("board", {})):
    setattr(App, _name, _rel.resilient("App." + _name, default=_default)(getattr(App, _name)))
