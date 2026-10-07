"""SQLite store behind both learners: items, bitemporal validity, audit events,
decision log for replay, lessons, skills, frontier, tunable parameters.

Writes go only to V4's own database. Item text stays local.
"""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .. import textsim

DEFAULT_PARAMS = {
    "dup_threshold": 0.90,      # at or above: same fact, reinforce instead of store
    "update_threshold": 0.55,   # at or above: same subject, treat as update or conflict
    "novelty_min": 0.35,        # 1 - best similarity must reach this to add
    "quality_min": 0.30,        # below: hold, do not admit
    "trust_margin": 0.20,       # trust advantage a conflicting newcomer needs to supersede
}
PARAM_BOUNDS = {
    "dup_threshold": (0.80, 0.97),
    "update_threshold": (0.40, 0.75),
    "novelty_min": (0.20, 0.60),
    "quality_min": (0.15, 0.55),
    "trust_margin": (0.05, 0.40),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, title TEXT, text TEXT NOT NULL,
  domain TEXT, tags TEXT, source_ids TEXT, evidence_n INTEGER DEFAULT 1,
  trust REAL, novelty REAL, quality REAL, status TEXT NOT NULL,
  valid_from TEXT, valid_to TEXT, observed_at TEXT, supersedes TEXT,
  origin TEXT, depth INTEGER DEFAULT 0, uses INTEGER DEFAULT 0, created_at TEXT NOT NULL, meta TEXT);
CREATE INDEX IF NOT EXISTS idx_items_fp ON items(fingerprint);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status, domain);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, body, tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS items_vocab USING fts5vocab(items_fts, 'row');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, item_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts TEXT, item_id TEXT, op TEXT,
  novelty REAL, best_sim REAL, quality REAL, trust REAL, label INTEGER, label_src TEXT);
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, context TEXT,
  strategy TEXT, outcome TEXT, score REAL, uses INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, description TEXT, procedure TEXT,
  successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, version INTEGER DEFAULT 1, last_used TEXT);
CREATE TABLE IF NOT EXISTS frontier(id INTEGER PRIMARY KEY, ts TEXT, question TEXT UNIQUE, parent TEXT,
  domain TEXT, priority REAL, depth INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS params(name TEXT PRIMARY KEY, value REAL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS param_history(id INTEGER PRIMARY KEY, ts TEXT, name TEXT, old REAL, new REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS strategies(name TEXT PRIMARY KEY, pulls INTEGER DEFAULT 0, reward REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sources_seen(path TEXT PRIMARY KEY, sha TEXT, mtime REAL, items INTEGER, ts TEXT);
"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class Ledger:
    def __init__(self, path=":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            for k, v in DEFAULT_PARAMS.items():
                self.db.execute("INSERT OR IGNORE INTO params VALUES(?,?,?)", (k, v, now()))
            self.db.commit()

    # parameters ---------------------------------------------------------------
    def params(self):
        with self.lock:
            return {r["name"]: r["value"] for r in self.db.execute("SELECT name,value FROM params")}

    def set_param(self, name, value, reason="manual"):
        lo, hi = PARAM_BOUNDS[name]
        value = max(lo, min(hi, float(value)))
        with self.lock:
            old = self.params().get(name)
            self.db.execute("INSERT OR REPLACE INTO params VALUES(?,?,?)", (name, value, now()))
            self.db.execute("INSERT INTO param_history(ts,name,old,new,reason) VALUES(?,?,?,?,?)",
                            (now(), name, old, value, reason))
            self.db.commit()
        return value

    # items --------------------------------------------------------------------
    def insert_item(self, item):
        rec = dict(item)
        rec.setdefault("id", "L-" + uuid.uuid4().hex[:12])
        rec.setdefault("created_at", now())
        rec.setdefault("valid_from", rec["created_at"])
        rec.setdefault("observed_at", rec["created_at"])
        rec.setdefault("evidence_n", max(1, len(rec.get("source_ids") or [])))
        with self.lock:
            self.db.execute(
                "INSERT INTO items(id,fingerprint,title,text,domain,tags,source_ids,evidence_n,trust,novelty,quality,"
                "status,valid_from,valid_to,observed_at,supersedes,origin,depth,created_at,meta) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["id"], rec["fingerprint"], rec.get("title", ""), rec["text"], rec.get("domain", "general"),
                 json.dumps(rec.get("tags") or []), json.dumps(rec.get("source_ids") or []), rec["evidence_n"],
                 rec.get("trust"), rec.get("novelty"), rec.get("quality"), rec["status"], rec["valid_from"],
                 rec.get("valid_to"), rec["observed_at"], rec.get("supersedes"), rec.get("origin", "novel"),
                 rec.get("depth", 0), rec["created_at"], json.dumps(rec.get("meta") or {})))
            if rec["status"] == "admitted":
                self.db.execute("INSERT INTO items_fts(id,body) VALUES(?,?)",
                                (rec["id"], (rec.get("title", "") + " " + rec["text"])))
            self.db.commit()
        return rec["id"]

    def get(self, item_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._row(row)

    @staticmethod
    def _row(row):
        if row is None:
            return None
        d = dict(row)
        for k in ("tags", "source_ids", "meta"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else ([] if k != "meta" else {})
            except ValueError:
                d[k] = [] if k != "meta" else {}
        return d

    def find_fingerprint(self, fp):
        with self.lock:
            row = self.db.execute("SELECT * FROM items WHERE fingerprint=? AND status IN ('admitted','held') "
                                  "ORDER BY created_at DESC LIMIT 1", (fp,)).fetchone()
        return self._row(row)

    def add_sources(self, item_id, new_sources):
        item = self.get(item_id)
        merged = list(dict.fromkeys((item["source_ids"] or []) + list(new_sources)))
        added = len(merged) - len(item["source_ids"] or [])
        with self.lock:
            self.db.execute("UPDATE items SET source_ids=?, evidence_n=? WHERE id=?",
                            (json.dumps(merged), len(merged), item_id))
            self.db.commit()
        return added

    def set_trust(self, item_id, trust):
        with self.lock:
            self.db.execute("UPDATE items SET trust=? WHERE id=?", (trust, item_id))
            self.db.commit()

    def supersede(self, old_id, when=None):
        with self.lock:
            self.db.execute("UPDATE items SET status='superseded', valid_to=? WHERE id=?", (when or now(), old_id))
            self.db.execute("DELETE FROM items_fts WHERE id=?", (old_id,))
            self.db.commit()

    def restore(self, item_id):
        item = self.get(item_id)
        if item is None or item["status"] != "superseded":
            return False
        with self.lock:
            self.db.execute("UPDATE items SET status='admitted', valid_to=NULL WHERE id=?", (item_id,))
            self.db.execute("INSERT INTO items_fts(id,body) VALUES(?,?)", (item_id, (item["title"] or "") + " " + item["text"]))
            self.db.commit()
        return True

    def reject(self, item_id, reason="rejected"):
        with self.lock:
            self.db.execute("UPDATE items SET status='rejected' WHERE id=?", (item_id,))
            self.db.execute("DELETE FROM items_fts WHERE id=?", (item_id,))
            self.db.commit()
        self.event("reject", item_id, {"reason": reason})

    def neighbors(self, text, k=8, include_held=False):
        """Candidate similar admitted items by BM25 over the item's most informative tokens."""
        toks = list(dict.fromkeys(textsim.tokens(text)))[:24]
        if not toks:
            return []
        query = " OR ".join('"%s"' % t.replace('"', "") for t in toks)
        with self.lock:
            try:
                ids = [r["id"] for r in self.db.execute(
                    "SELECT id FROM items_fts WHERE items_fts MATCH ? ORDER BY bm25(items_fts) LIMIT ?",
                    (query, k * 3))]
            except sqlite3.OperationalError:
                ids = []
            rows = [self.db.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone() for i in ids]
        return [self._row(r) for r in rows if r is not None][: k * 3]

    def doc_freq(self, toks):
        out = {}
        with self.lock:
            for t in set(toks):
                row = self.db.execute("SELECT doc FROM items_vocab WHERE term=?", (t,)).fetchone()
                out[t] = row["doc"] if row else 0
        return out

    def count(self, status="admitted"):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM items WHERE status=?", (status,)).fetchone()["c"]

    def valid_items(self, domain=None, as_of=None, limit=500):
        as_of = as_of or now()
        sql = ("SELECT * FROM items WHERE status IN ('admitted','superseded') AND valid_from<=? "
               "AND (valid_to IS NULL OR valid_to>?)")
        args = [as_of, as_of]
        if domain:
            sql += " AND domain=?"
            args.append(domain)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            return [self._row(r) for r in self.db.execute(sql, args)]

    def touch(self, item_id):
        with self.lock:
            self.db.execute("UPDATE items SET uses=uses+1 WHERE id=?", (item_id,))
            self.db.commit()

    # audit and decisions ------------------------------------------------------
    def event(self, kind, item_id=None, detail=None):
        with self.lock:
            self.db.execute("INSERT INTO events(ts,kind,item_id,detail) VALUES(?,?,?,?)",
                            (now(), kind, item_id, json.dumps(detail or {}, default=str)))
            self.db.commit()

    def log_decision(self, item_id, op, novelty, best_sim, quality, trust):
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO decisions(ts,item_id,op,novelty,best_sim,quality,trust) VALUES(?,?,?,?,?,?,?)",
                (now(), item_id, op, novelty, best_sim, quality, trust))
            self.db.commit()
            return cur.lastrowid

    def label_decision(self, item_id, label, src):
        with self.lock:
            self.db.execute("UPDATE decisions SET label=?, label_src=? WHERE item_id=?", (int(label), src, item_id))
            self.db.commit()

    def labeled_decisions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM decisions WHERE label IS NOT NULL AND op IN ('ADD','UPDATE','HOLD','NOOP','REINFORCE')")]

    def recent_events(self, limit=50, kind=None):
        sql = "SELECT * FROM events"
        args = []
        if kind:
            sql += " WHERE kind=?"
            args.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    # lessons, skills, frontier, strategies -------------------------------------
    def add_lesson(self, kind, context, strategy, outcome, score):
        with self.lock:
            self.db.execute("INSERT INTO lessons(ts,kind,context,strategy,outcome,score) VALUES(?,?,?,?,?,?)",
                            (now(), kind, context[:500], strategy, outcome[:800], score))
            self.db.commit()

    def lessons(self, strategy=None, limit=20):
        sql, args = "SELECT * FROM lessons", []
        if strategy:
            sql += " WHERE strategy=?"
            args.append(strategy)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def upsert_skill(self, name, description, procedure, success):
        with self.lock:
            row = self.db.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone()
            if row is None:
                self.db.execute("INSERT INTO skills(name,description,procedure,successes,failures,last_used) VALUES(?,?,?,?,?,?)",
                                (name, description, json.dumps(procedure), int(success), int(not success), now()))
            else:
                col = "successes" if success else "failures"
                self.db.execute("UPDATE skills SET %s=%s+1,last_used=?,procedure=?,version=version+(procedure!=?) WHERE name=?" % (col, col),
                                (now(), json.dumps(procedure), json.dumps(procedure), name))
            self.db.commit()

    def skills(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM skills ORDER BY successes DESC, name")]

    def push_frontier(self, question, parent, domain, priority, depth):
        with self.lock:
            try:
                self.db.execute("INSERT INTO frontier(ts,question,parent,domain,priority,depth,status) VALUES(?,?,?,?,?,?,'open')",
                                (now(), question[:400], parent, domain, priority, depth))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def pop_frontier(self, limit=5, max_depth=3):
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT * FROM frontier WHERE status='open' AND depth<=? ORDER BY priority DESC, id LIMIT ?",
                (max_depth, limit))]
            for r in rows:
                self.db.execute("UPDATE frontier SET status='taken' WHERE id=?", (r["id"],))
            self.db.commit()
        return rows

    def close_frontier(self, question, status):
        with self.lock:
            self.db.execute("UPDATE frontier SET status=? WHERE question=?", (status, question[:400]))
            self.db.commit()

    def frontier(self, limit=50):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM frontier ORDER BY id DESC LIMIT ?", (limit,))]

    def strategy_stats(self):
        with self.lock:
            return {r["name"]: (r["pulls"], r["reward"]) for r in self.db.execute("SELECT * FROM strategies")}

    def strategy_update(self, name, reward):
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO strategies(name) VALUES(?)", (name,))
            self.db.execute("UPDATE strategies SET pulls=pulls+1, reward=reward+? WHERE name=?", (float(reward), name))
            self.db.commit()

    # source tracking ------------------------------------------------------------
    def seen(self, path):
        with self.lock:
            return self.db.execute("SELECT * FROM sources_seen WHERE path=?", (path,)).fetchone()

    def mark_seen(self, path, sha, mtime, items):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO sources_seen VALUES(?,?,?,?,?)", (path, sha, mtime, items, now()))
            self.db.commit()

    def stats(self):
        with self.lock:
            by_status = {r["status"]: r["c"] for r in self.db.execute("SELECT status,COUNT(*) c FROM items GROUP BY status")}
            by_domain = {r["domain"]: r["c"] for r in self.db.execute(
                "SELECT domain,COUNT(*) c FROM items WHERE status='admitted' GROUP BY domain")}
            ops = {r["op"]: r["c"] for r in self.db.execute("SELECT op,COUNT(*) c FROM decisions GROUP BY op")}
            out = {"items": by_status, "domains": by_domain, "ops": ops,
                   "lessons": self.db.execute("SELECT COUNT(*) c FROM lessons").fetchone()["c"],
                   "skills": self.db.execute("SELECT COUNT(*) c FROM skills").fetchone()["c"],
                   "frontier_open": self.db.execute("SELECT COUNT(*) c FROM frontier WHERE status='open'").fetchone()["c"],
                   "labeled": self.db.execute("SELECT COUNT(*) c FROM decisions WHERE label IS NOT NULL").fetchone()["c"]}
        out["params"] = self.params()
        return out

    def close(self):
        with self.lock:
            self.db.close()
