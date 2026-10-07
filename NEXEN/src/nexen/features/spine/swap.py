"""Swap registry: anything we can anticipate substituting is a named slot with ordered candidates,
a health rule and a safe default. Models, LoRA adapters, methods, hustles, providers, vector stores, knowledge
packs, research sources, workflow variants, accounts and schedule blocks are all slots.

Performing poorly (rolling score under the slot's floor, a failure streak, or a bad health flag) recommends the best
other candidate by UCB. Internal slots swap automatically. Slots that touch the outside world (hustle, account,
schedule) only recommend; the change goes through the rules engine and the owner gate. Every swap is logged, has a
cooldown, and ``revert`` restores the previous candidate.
"""
import json
import math
import sqlite3
import threading
import time

from nexen.core import gate, paths

INTERNAL = {"model", "adapter", "method", "provider", "store", "pack", "source", "variant", "dataset"}

# slot id -> (kind, candidates in preference order, policy)
SLOTS = {
    # models (owner decision 2026-10-03: strong first, local fallback 7B-9B quantized)
    "model.chat": ("model", ["strong:antigravity", "strong:claude", "local:marvin-brain:latest", "local:hermes3:8b-llama3.1-q4_K_M", "local:nexen-master-v3:latest"], {"floor": 0.55, "window": 8, "streak": 3}),
    "model.code": ("model", ["strong:claude", "strong:antigravity", "local:qwen2.5-coder:7b", "local:nexen-coder-v3:latest", "local:trm:latest"], {"floor": 0.6, "window": 8, "streak": 3}),
    "model.vision": ("model", ["local:marvin-vision:latest", "local:maternion/fara:latest"], {"floor": 0.5, "window": 6, "streak": 3}),
    "model.embed": ("model", ["local:embeddinggemma:latest", "local:nexen-embedding-cpu:latest", "lexical:tfidf"], {"floor": 0.5, "window": 6, "streak": 3}),
    "model.router": ("model", ["rule:nexen_decide", "local:openjev"], {"floor": 0.6, "window": 8, "streak": 3}),
    "provider.route": ("provider", ["antigravity", "claude", "hermes:freellmapi/auto", "local:ollama"], {"floor": 0.6, "window": 6, "streak": 2}),
    # LoRA / QLoRA adapters: one slot per agent; "base" is always the safe fallback
    "adapter.marvin": ("adapter", ["base", "lora:marvin-v4-spine", "qlora:marvin-master"], {"floor": 0.6, "window": 6, "streak": 2}),
    "adapter.coder": ("adapter", ["base", "lora:coder-spine"], {"floor": 0.6, "window": 6, "streak": 2}),
    "adapter.research": ("adapter", ["base", "lora:research-world"], {"floor": 0.6, "window": 6, "streak": 2}),
    "adapter.swarm": ("adapter", ["base", "lora:swarm-router"], {"floor": 0.6, "window": 6, "streak": 2}),
    "adapter.content": ("adapter", ["base", "lora:content-quality"], {"floor": 0.6, "window": 6, "streak": 2}),
    # methods per lane
    "method.clipping": ("method", ["baseline-ffmpeg", "whop-clipper", "smart-captions", "business-operations"], {"floor": 0.6, "window": 5, "streak": 2}),
    "method.posting": ("method", ["native-scheduler", "postiz", "manual-owner"], {"floor": 0.7, "window": 5, "streak": 2}),
    "method.scraping": ("method", ["scrapling", "yt-dlp-subtitles", "rss", "manual"], {"floor": 0.6, "window": 5, "streak": 3}),
    "method.research": ("method", ["recursive-local", "world-snapshot", "youtube-transcripts", "strong-model-brief"], {"floor": 0.5, "window": 5, "streak": 3}),
    "method.image": ("method", ["comfyui-sdxl", "chatgpt-stills", "stock-owned"], {"floor": 0.5, "window": 5, "streak": 2}),
    # hustles (money first; order = owner's current focus; external, so recommend only)
    "hustle.primary": ("hustle", ["services-upwork-fiverr", "owned-inventory-dropship", "affiliate", "paid-clipping", "youtube-faceless", "ai-persona"], {"floor": 10.0, "window": 7, "streak": 5, "unit": "usd_per_hour"}),
    # infrastructure
    "store.vector": ("store", ["qdrant", "milvus-lite", "v4-ledger", "obsidian-text"], {"floor": 0.5, "window": 6, "streak": 3}),
    "pack.marvin": ("pack", ["marvin-core-v1"], {"floor": 0.5, "window": 6, "streak": 3}),
    "source.world": ("source", ["gdelt", "hackernews", "wikipedia-pageviews", "rss-headlines", "mastodon-trends"], {"floor": 0.4, "window": 4, "streak": 2}),
    "dataset.finetune": ("dataset", ["marvin-dataset-balanced", "marvin-dataset-full", "v4-spine-shard"], {"floor": 0.5, "window": 3, "streak": 2}),
    "variant.workflow": ("variant", ["A", "B"], {"floor": 0.5, "window": 6, "streak": 3}),
    "account.test": ("account", ["E", "YT-LAB", "YT-SHORTS"], {"floor": 0.4, "window": 5, "streak": 3}),
    "schedule.block": ("schedule", ["default-week"], {"floor": 0.4, "window": 5, "streak": 3}),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY, kind TEXT, active TEXT, previous TEXT, candidates TEXT, policy TEXT, swapped_at REAL);
CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY, ts REAL, slot TEXT, candidate TEXT, value REAL, ok INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, ts REAL, slot TEXT, old TEXT, new TEXT, reason TEXT, auto INTEGER);
"""
COOLDOWN = 1800


class Swap:
    def __init__(self, db_path=None, clock=None):
        self.path = str(db_path or (paths.DATA / "swap.db"))
        self.clock = clock or time.time
        if self.path != ":memory:":
            paths.ensure_data()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            for sid, (kind, cands, pol) in SLOTS.items():
                if not self.db.execute("SELECT 1 FROM slots WHERE id=?", (sid,)).fetchone():
                    self.db.execute("INSERT INTO slots VALUES(?,?,?,?,?,?,?)", (sid, kind, cands[0], None, json.dumps(cands), json.dumps(pol), 0))
            self.db.commit()

    def slot(self, sid):
        with self.lock:
            r = self.db.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        if r is None:
            raise KeyError(sid)
        d = dict(r)
        d["candidates"], d["policy"] = json.loads(d["candidates"]), json.loads(d["policy"])
        return d

    def current(self, sid):
        return self.slot(sid)["active"]

    def slots(self):
        with self.lock:
            ids = [r["id"] for r in self.db.execute("SELECT id FROM slots ORDER BY id")]
        return [self.slot(i) for i in ids]

    def add_candidate(self, sid, candidate, position=None):
        s = self.slot(sid)
        if candidate not in s["candidates"]:
            c = list(s["candidates"])
            c.insert(len(c) if position is None else position, candidate)
            with self.lock:
                self.db.execute("UPDATE slots SET candidates=? WHERE id=?", (json.dumps(c), sid))
                self.db.commit()
        return self.slot(sid)

    def record(self, sid, value, ok=True, candidate=None, note=""):
        s = self.slot(sid)
        with self.lock:
            self.db.execute("INSERT INTO metrics(ts,slot,candidate,value,ok,note) VALUES(?,?,?,?,?,?)", (self.clock(), sid, candidate or s["active"], float(value), int(bool(ok)), note[:200]))
            self.db.commit()

    def _recent(self, sid, cand, n):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT value,ok FROM metrics WHERE slot=? AND candidate=? ORDER BY id DESC LIMIT ?", (sid, cand, n))]

    def health(self, sid):
        s = self.slot(sid)
        pol = s["policy"]
        rows = self._recent(sid, s["active"], pol["window"])
        if not rows:
            return {"slot": sid, "active": s["active"], "state": "no-data", "mean": None, "streak": 0}
        mean = sum(r["value"] for r in rows) / len(rows)
        streak = 0
        for r in rows:
            if r["ok"]:
                break
            streak += 1
        poor = (len(rows) >= min(3, pol["window"]) and mean < pol["floor"]) or streak >= pol["streak"]
        return {"slot": sid, "active": s["active"], "state": "poor" if poor else "ok", "mean": round(mean, 3), "streak": streak, "floor": pol["floor"], "n": len(rows)}

    def _ucb(self, sid, cand, total):
        rows = self._recent(sid, cand, 20)
        if not rows:
            return 1.5  # untried candidates get explored
        mean = sum(r["value"] for r in rows) / len(rows)
        scale = max(1.0, self.slot(sid)["policy"]["floor"] * 2)
        return mean / scale + math.sqrt(2 * math.log(total + 1) / len(rows))

    def recommend(self, sid):
        """If the active candidate is performing poorly, name the best replacement and whether it may swap by itself."""
        s, h = self.slot(sid), self.health(sid)
        if h["state"] != "poor":
            return {"slot": sid, "swap": False, "health": h}
        if self.clock() - (s["swapped_at"] or 0) < COOLDOWN:
            return {"slot": sid, "swap": False, "health": h, "reason": "cooldown"}
        others = [c for c in s["candidates"] if c != s["active"]]
        if not others:
            return {"slot": sid, "swap": False, "health": h, "reason": "no other candidate"}
        total = sum(len(self._recent(sid, c, 20)) for c in s["candidates"])
        best = max(others, key=lambda c: self._ucb(sid, c, total))
        return {"slot": sid, "swap": True, "to": best, "from": s["active"], "health": h, "auto_allowed": s["kind"] in INTERNAL}

    def apply(self, sid, candidate, reason="manual", auto=False):
        s = self.slot(sid)
        if candidate not in s["candidates"]:
            raise ValueError("%s is not a candidate for %s" % (candidate, sid))
        if s["kind"] not in INTERNAL and auto:
            chk = gate.check("account_change", "swap %s -> %s" % (sid, candidate), {"slot": sid, "to": candidate})
            if not chk["allowed"]:
                return {"ok": False, "queued_for_owner": chk.get("approval_id"), "reason": chk["reason"]}
        with self.lock:
            self.db.execute("UPDATE slots SET active=?, previous=?, swapped_at=? WHERE id=?", (candidate, s["active"], self.clock(), sid))
            self.db.execute("INSERT INTO history(ts,slot,old,new,reason,auto) VALUES(?,?,?,?,?,?)", (self.clock(), sid, s["active"], candidate, reason[:200], int(auto)))
            self.db.commit()
        gate.audit("swap", {"slot": sid, "from": s["active"], "to": candidate, "reason": reason, "auto": auto})
        return {"ok": True, "slot": sid, "from": s["active"], "to": candidate}

    def revert(self, sid):
        s = self.slot(sid)
        if not s["previous"]:
            return {"ok": False, "reason": "no previous candidate"}
        return self.apply(sid, s["previous"], reason="revert")

    def sweep(self):
        """Evaluate every slot. Internal slots swap on their own; the rest are returned as recommendations."""
        done, advice = [], []
        for s in self.slots():
            rec = self.recommend(s["id"])
            if rec.get("swap"):
                if rec["auto_allowed"]:
                    done.append(self.apply(s["id"], rec["to"], reason="auto: %s poor (mean %s)" % (rec["from"], rec["health"]["mean"]), auto=True))
                else:
                    advice.append(rec)
        return {"swapped": done, "recommended": advice}

    def history_rows(self, n=30):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (n,))]
