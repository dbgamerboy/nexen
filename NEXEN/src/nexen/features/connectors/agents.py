"""Connectors for the AI agents on this PC. Reads are local and read-only.

Each connector offers: status(), recent(n), read(id, n), search(q, n) and, only where a real
non-interactive channel exists, send(prompt). ChatGPT has no local API: it is read from saved
exports and written as an outbox packet that the owner pastes; it is never marked sent.
"""
import json
import os
import shutil
import time
from pathlib import Path

from nexen.core import paths
from nexen.features.connectors import base

HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
CODEX = HOME / ".codex"
GEMINI = HOME / ".gemini" / "antigravity"
HERMES_DB = Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local"))) / "hermes" / "state.db"
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
OUTBOX = paths.DATA / "outbox"


def _msg_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


# ---------------------------------------------------------------------------- Codex
class Codex:
    name = "codex"

    @staticmethod
    def _index():
        out = []
        for row in base.stream_jsonl(CODEX / "session_index.jsonl"):
            if isinstance(row, dict) and row.get("id"):
                out.append({"id": row["id"], "title": row.get("thread_name", ""), "updated": row.get("updated_at", "")})
        return sorted(out, key=lambda r: r["updated"], reverse=True)

    @staticmethod
    def _rollout(session_id):
        root = CODEX / "sessions"
        if not root.is_dir():
            return None
        for p in root.rglob("rollout-*%s.jsonl" % session_id):
            return p
        return None

    def status(self):
        idx = self._index()
        return {"ok": CODEX.is_dir(), "sessions_indexed": len(idx),
                "latest": idx[0] if idx else None, "send": "none (Codex Desktop has no local CLI); handoffs go through the vault"}

    def recent(self, n=10):
        files = sorted((CODEX / "sessions").rglob("rollout-*.jsonl"), key=base.mtime, reverse=True)[:n] if (CODEX / "sessions").is_dir() else []
        titles = {r["id"]: r["title"] for r in self._index()}
        out = []
        for f in files:
            sid = f.stem[-36:]
            out.append({"id": sid, "title": titles.get(sid, ""), "path": str(f), "mtime": base.iso(base.mtime(f)), "bytes": f.stat().st_size})
        return out

    def read(self, session_id, n=20):
        f = self._rollout(session_id)
        if f is None:
            return {"ok": False, "error": "no rollout file for that id"}
        msgs = []
        for row in base.tail_jsonl(f, n=n * 6, max_bytes=3_000_000):
            p = row.get("payload") or {}
            if row.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in {"user", "assistant"}:
                text = _msg_text(p.get("content"))
                if text and not text.startswith("<"):
                    msgs.append({"role": p["role"], "ts": row.get("timestamp"), "text": base.redact(text)[:2500]})
        return {"ok": True, "id": session_id, "path": str(f), "messages": msgs[-n:]}

    def search(self, q, n=8, files=6, max_seconds=25):
        hits, start = [], time.time()
        for f in sorted((CODEX / "sessions").rglob("rollout-*.jsonl"), key=base.mtime, reverse=True)[:files] if (CODEX / "sessions").is_dir() else []:
            for row in base.stream_jsonl(f, max_bytes=40_000_000):
                p = row.get("payload") or {}
                if p.get("type") == "message" and p.get("role") in {"user", "assistant"}:
                    text = _msg_text(p.get("content"))
                    if q.lower() in text.lower() and not text.startswith("<"):
                        hits.append({"source": "codex", "id": f.stem[-36:], "role": p["role"], "ts": row.get("timestamp"),
                                     "snippet": base.redact(base.snippet(text, q))})
                        if len(hits) >= n:
                            return hits
                if time.time() - start > max_seconds:
                    return hits
        return hits


# ----------------------------------------------------------------------- Antigravity
class Antigravity:
    name = "antigravity"
    AGY = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"

    def _summaries(self):
        return base.ro_query(GEMINI / "conversation_summaries.db",
                             "SELECT conversation_id,title,preview,step_count,last_modified_time FROM conversation_summaries "
                             "ORDER BY last_modified_time DESC")

    def status(self):
        s = self._summaries()
        return {"ok": GEMINI.is_dir(), "conversations": len(s), "cli": str(self.AGY) if self.AGY.is_file() else None,
                "latest": s[0] if s else None, "send": "agy -p (non-interactive print)"}

    def recent(self, n=10):
        rows = self._summaries()[:n]
        if rows:
            return [{"id": r["conversation_id"], "title": r["title"], "preview": base.redact(r["preview"])[:200],
                     "steps": r["step_count"], "mtime": str(r["last_modified_time"])} for r in rows]
        brain = GEMINI / "brain"
        dirs = sorted([d for d in brain.iterdir() if d.is_dir()], key=base.mtime, reverse=True)[:n] if brain.is_dir() else []
        return [{"id": d.name, "title": "", "mtime": base.iso(base.mtime(d))} for d in dirs]

    def read(self, conv_id, n=20):
        d = GEMINI / "brain" / conv_id
        if not d.is_dir():
            return {"ok": False, "error": "no brain folder for that id"}
        artifacts = [{"name": p.name, "bytes": p.stat().st_size} for p in sorted(d.glob("*.md"))]
        log = d / ".system_generated" / "logs" / "transcript.jsonl"
        msgs = []
        for row in base.tail_jsonl(log, n=n * 4, max_bytes=2_000_000):
            if row.get("type") in {"USER_INPUT", "PLANNER_RESPONSE"} and row.get("content"):
                role = "user" if row.get("source", "").startswith("USER") else "assistant"
                msgs.append({"role": role, "ts": row.get("created_at"), "text": base.redact(str(row["content"]))[:2500]})
        return {"ok": True, "id": conv_id, "artifacts": artifacts, "messages": msgs[-n:]}

    def artifact(self, conv_id, name):
        p = GEMINI / "brain" / conv_id / name
        if p.parent != GEMINI / "brain" / conv_id or not p.is_file():
            return {"ok": False, "error": "unknown artifact"}
        return {"ok": True, "name": name, "text": base.redact(p.read_text(encoding="utf-8", errors="replace"))[:20000]}

    def search(self, q, n=8, max_seconds=20):
        hits, start = [], time.time()
        brain = GEMINI / "brain"
        for d in sorted([x for x in brain.iterdir() if x.is_dir()], key=base.mtime, reverse=True)[:12] if brain.is_dir() else []:
            for md in d.glob("*.md"):
                try:
                    text = md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if q.lower() in text.lower():
                    hits.append({"source": "antigravity", "id": d.name, "artifact": md.name, "snippet": base.redact(base.snippet(text, q))})
                    if len(hits) >= n:
                        return hits
            if time.time() - start > max_seconds:
                break
        return hits

    def send(self, prompt, timeout=300):
        if not self.AGY.is_file():
            return {"ok": False, "error": "agy.exe not found"}
        code, out, err = base.run_cli([str(self.AGY), "-p", prompt, "--print-timeout", "%ds" % timeout], timeout=timeout + 30)
        return {"ok": code == 0, "code": code, "reply": base.redact(out)[:8000], "error": base.redact(err)[:800]}


# ---------------------------------------------------------------------------- Hermes
class Hermes:
    name = "hermes"

    def status(self):
        exe = shutil.which("hermes")
        n = base.ro_query(HERMES_DB, "SELECT COUNT(*) c FROM messages")
        return {"ok": HERMES_DB.is_file(), "messages": n[0]["c"] if n else 0, "cli": exe, "send": "hermes -z (one-shot)"}

    def recent(self, n=10):
        cols = base.columns(HERMES_DB, "sessions")
        order = "started_at" if "started_at" in cols else ("created_at" if "created_at" in cols else "id")
        rows = base.ro_query(HERMES_DB, "SELECT id,source,display_name,%s AS ts FROM sessions ORDER BY %s DESC LIMIT ?" % (order, order), (n,))
        return [{"id": r["id"], "title": r.get("display_name") or r.get("source"), "source": r["source"], "mtime": base.iso(r["ts"])} for r in rows]

    def read(self, session_id, n=20):
        cols = base.columns(HERMES_DB, "messages")
        ts = "timestamp" if "timestamp" in cols else ("created_at" if "created_at" in cols else "id")
        rows = base.ro_query(HERMES_DB, "SELECT role,content,%s AS ts FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                                        "ORDER BY id DESC LIMIT ?" % ts, (session_id, n))
        return {"ok": bool(rows), "id": session_id,
                "messages": [{"role": r["role"], "ts": base.iso(r["ts"]) if isinstance(r["ts"], (int, float)) else r["ts"],
                              "text": base.redact(r["content"] or "")[:2500]} for r in reversed(rows)]}

    def search(self, q, n=8):
        rows = base.ro_query(HERMES_DB, "SELECT m.session_id,m.role,m.content FROM messages m WHERE m.role IN ('user','assistant') "
                                        "AND m.content LIKE ? ORDER BY m.id DESC LIMIT ?", ("%" + q + "%", n))
        return [{"source": "hermes", "id": r["session_id"], "role": r["role"], "snippet": base.redact(base.snippet(r["content"], q))} for r in rows]

    def send(self, prompt, timeout=240):
        exe = shutil.which("hermes")
        if not exe:
            return {"ok": False, "error": "hermes.exe not on PATH"}
        code, out, err = base.run_cli([exe, "-z", prompt], timeout=timeout)
        return {"ok": code == 0, "code": code, "reply": base.redact(out)[:8000], "error": base.redact(err)[:800]}


# ----------------------------------------------------------------------- Claude Code
class ClaudeCode:
    name = "claude"

    def _files(self):
        if not CLAUDE_PROJECTS.is_dir():
            return []
        return sorted(CLAUDE_PROJECTS.glob("*/*.jsonl"), key=base.mtime, reverse=True)

    def status(self):
        f = self._files()
        return {"ok": CLAUDE_PROJECTS.is_dir(), "sessions": len(f), "cli": shutil.which("claude"), "send": "claude -p (one-shot print)"}

    def recent(self, n=10):
        return [{"id": f.stem, "title": f.parent.name[-48:], "mtime": base.iso(base.mtime(f)), "bytes": f.stat().st_size} for f in self._files()[:n]]

    def read(self, session_id, n=20):
        for f in self._files():
            if f.stem == session_id:
                msgs = []
                for row in base.tail_jsonl(f, n=n * 6, max_bytes=3_000_000):
                    if row.get("type") in {"user", "assistant"}:
                        m = row.get("message") or {}
                        text = _msg_text(m.get("content"))
                        if text and not text.lstrip().startswith("<"):
                            msgs.append({"role": row["type"], "ts": row.get("timestamp"), "text": base.redact(text)[:2500]})
                return {"ok": True, "id": session_id, "messages": msgs[-n:]}
        return {"ok": False, "error": "unknown session"}

    def search(self, q, n=8, files=8, max_seconds=20):
        hits, start = [], time.time()
        for f in self._files()[:files]:
            for row in base.stream_jsonl(f, max_bytes=30_000_000):
                if row.get("type") in {"user", "assistant"}:
                    text = _msg_text((row.get("message") or {}).get("content"))
                    if q.lower() in text.lower() and not text.lstrip().startswith("<"):
                        hits.append({"source": "claude", "id": f.stem, "role": row["type"], "snippet": base.redact(base.snippet(text, q))})
                        if len(hits) >= n:
                            return hits
                if time.time() - start > max_seconds:
                    return hits
        return hits

    def send(self, prompt, timeout=300):
        exe = shutil.which("claude")
        if not exe:
            return {"ok": False, "error": "claude.exe not on PATH"}
        code, out, err = base.run_cli([exe, "-p", prompt], timeout=timeout)
        return {"ok": code == 0, "code": code, "reply": base.redact(out)[:8000], "error": base.redact(err)[:800]}


# ----------------------------------------------------------------------------- ChatGPT
class ChatGPT:
    """No API and no browser automation here. Saved exports in, outbox packets out."""
    name = "chatgpt"
    EXPORT_DIRS = [HOME / "Downloads", paths.H_NEXEN / "exports", paths.H_NEXEN / "ingest"]

    def _exports(self):
        found = []
        for d in self.EXPORT_DIRS:
            if d.is_dir():
                for p in d.glob("*.json"):
                    if any(k in p.name.lower() for k in ("chatgpt", "conversation", "handoff", "money -", "nexen")):
                        found.append(p)
        return sorted(found, key=base.mtime, reverse=True)

    def status(self):
        return {"ok": True, "exports": len(self._exports()), "outbox": str(OUTBOX / "chatgpt"),
                "send": "NOT AVAILABLE: packets are written to the outbox and pasted by the owner; a prepared packet is not a reply"}

    def recent(self, n=10):
        return [{"id": p.name, "title": p.name, "path": str(p), "mtime": base.iso(base.mtime(p)), "bytes": p.stat().st_size} for p in self._exports()[:n]]

    def read(self, name, n=20):
        for p in self._exports():
            if p.name == name:
                try:
                    data = json.loads(p.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    return {"ok": False, "error": "unreadable export"}
                text = json.dumps(data, ensure_ascii=False)[:6000]
                return {"ok": True, "id": name, "messages": [{"role": "export", "text": base.redact(text)}]}
        return {"ok": False, "error": "unknown export"}

    def search(self, q, n=8):
        hits = []
        for p in self._exports()[:30]:
            try:
                text = p.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            if q.lower() in text.lower():
                hits.append({"source": "chatgpt", "id": p.name, "snippet": base.redact(base.snippet(text, q))})
                if len(hits) >= n:
                    break
        return hits

    def packet(self, prompt, title="packet"):
        folder = OUTBOX / "chatgpt"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title)[:40]
        p = folder / ("%s-%s.md" % (stamp, safe))
        p.write_text("<!-- STATUS: NOT SENT. Paste into ChatGPT, then save its reply with: nexen chatgpt import <file> -->\n\n"
                     + base.redact(prompt), encoding="utf-8")
        return {"ok": True, "status": "prepared, not sent", "path": str(p)}


REGISTRY = {c.name: c() for c in (Codex, Antigravity, Hermes, ClaudeCode, ChatGPT)}
