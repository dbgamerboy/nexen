"""Predetermined future failures: every catalog problem class crossed with every component and operating condition.

A forecast is a prediction, never an observation. It lives in its own table so it cannot inflate the observed
failure rates that feed premortem. Each row carries a probability (the class's smoothed rate times a context
multiplier), the early signal to watch, the prevention and the playbook that answers it. Rows are deterministic:
the same catalog and history produce the same ids, so regeneration is idempotent.
"""
import json
import sqlite3
import threading
import time

from .. import paths, textsim

COMPONENTS = {
    "swarm worker": "swarm worker queue job receipt handler ticket",
    "n8n workflow": "n8n workflow webhook node schedule trigger",
    "clip pipeline": "clip clipper ffmpeg caption render video",
    "social poster": "post tiktok instagram account platform cap rule publish",
    "V4 engine": "v4 engine server api cli spine learning",
    "MARVIN chat": "marvin chat voice brain model prompt",
    "ingest job": "ingest note vault index corpus scan file",
    "Ollama model": "ollama model gpu vram inference timeout",
    "PC2 share": "pc2 share smb network host",
    "update pipeline": "update package backup rollback restart exe",
    "learning gate": "novelty ledger recall recursive learning memory",
    "scheduler": "schedule routine block stop pause task due",
}
CONDITIONS = {
    "during an unattended overnight run": 1.3,
    "right after an update": 1.5,
    "while gaming mode holds the GPU": 1.4,
    "the moment STOP is lifted": 1.2,
    "with the F: drive unavailable": 1.6,
    "while Ollama serves another job": 1.4,
    "after a power loss": 1.5,
    "on the first run with real input": 1.7,
    "when two jobs overlap": 1.5,
    "after a context refresh": 1.1,
    "when a provider quota is near its cap": 1.3,
    "while the owner is away for 72 hours": 1.2,
    "with PC2 offline": 1.3,
    "after a model swap": 1.4,
}

SCHEMA = """CREATE TABLE IF NOT EXISTS forecasts(id TEXT PRIMARY KEY, ts TEXT, problem_id TEXT, component TEXT, condition TEXT,
probability REAL, impact INTEGER, text TEXT, early_signal TEXT, prevention TEXT, playbook TEXT, status TEXT, basis TEXT);
CREATE INDEX IF NOT EXISTS forecasts_problem ON forecasts(problem_id);"""


_conn, _lock = {}, threading.Lock()


def _db():
    """Forecasts live in their own file: predictions never share a database with observed failures."""
    path = str(paths.DATA / "forecast.db")
    with _lock:
        if path not in _conn:
            c = sqlite3.connect(path, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            _conn[path] = c
        return _conn[path], _lock


def _affinity(problem, comp_words):
    own = set(textsim.tokens(" ".join([problem["title"], problem["area"], " ".join(problem["triggers"])])))
    hit = len(own & set(comp_words.split()))
    return 1.6 if hit >= 2 else 1.25 if hit == 1 else 0.7


def build(spine):
    """Return the full forecast list (no writes)."""
    rows, ts = [], time.strftime("%Y-%m-%dT%H:%M:%S")
    for pid, p in spine.problems.items():
        rate = spine.rate(pid)
        symptom = p["symptoms"][0]
        for ci, (comp, words) in enumerate(COMPONENTS.items()):
            aff = _affinity(p, words)
            for ki, (cond, mult) in enumerate(CONDITIONS.items()):
                prob = max(0.01, min(0.95, round(rate * aff * mult, 3)))
                rows.append({
                    "id": "FC-%s-%02d-%02d" % (pid, ci, ki), "ts": ts, "problem_id": pid, "component": comp, "condition": cond,
                    "probability": prob, "impact": p["severity"],
                    "text": "%s %s: %s (%s)." % (comp[0].upper() + comp[1:], cond, symptom, p["title"]),
                    "early_signal": symptom, "prevention": (p["prevent"] or [""])[0],
                    "playbook": p["playbooks"][0]["id"], "status": "predicted",
                    "basis": json.dumps({"class_rate": rate, "affinity": aff, "condition_multiplier": mult, "evidence": p.get("evidence")})})
    return rows


def generate(spine, minimum=10000):
    rows = build(spine)
    db, lock = _db()
    with lock:
        db.execute("DELETE FROM forecasts")
        db.executemany(
            "INSERT OR REPLACE INTO forecasts(id,ts,problem_id,component,condition,probability,impact,text,early_signal,prevention,playbook,status,basis)"
            " VALUES(:id,:ts,:problem_id,:component,:condition,:probability,:impact,:text,:early_signal,:prevention,:playbook,:status,:basis)", rows)
        db.commit()
    out = paths.DATA / "spine"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "forecasts.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return {"generated": len(rows), "meets_minimum": len(rows) >= minimum, "classes": len(spine.problems),
            "components": len(COMPONENTS), "conditions": len(CONDITIONS), "file": str(out / "forecasts.jsonl"),
            "label": "predicted, not observed; excluded from observed failure rates"}


def top(spine, limit=10, component=None):
    q, a = "SELECT id,problem_id,component,condition,probability,impact,early_signal,prevention,playbook FROM forecasts", []
    if component:
        q += " WHERE component=?"
        a.append(component)
    db, lock = _db()
    with lock:
        rows = [dict(r) for r in db.execute(q + " ORDER BY probability*impact DESC LIMIT ?", a + [limit])]
    return rows


def lookup(spine, text, k=5):
    """Forecasts closest to a plan or an error text, ranked by expected loss."""
    d = spine.diagnose(text, k=2)
    top = d["matches"][0]["score"] if d["matches"] else 0
    pids = [m["id"] for m in d["matches"] if m["score"] >= 0.5 * top]  # a weak runner-up must not outrank the real match on expected loss
    if not pids:
        return []
    db, lock = _db()
    with lock:
        marks = ",".join("?" * len(pids))
        return [dict(r) for r in db.execute(
            "SELECT id,problem_id,component,condition,probability,impact,early_signal,prevention,playbook FROM forecasts "
            "WHERE problem_id IN (%s) ORDER BY probability*impact DESC LIMIT ?" % marks, pids + [k])]


def stats(spine):
    db, lock = _db()
    with lock:
        n = db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        by = [dict(r) for r in db.execute("SELECT problem_id, COUNT(*) n, ROUND(AVG(probability),3) p FROM forecasts GROUP BY problem_id ORDER BY p DESC LIMIT 8")]
    return {"forecasts": n, "highest_average_probability": by}


def self_check(spine, sample=600):
    """Do forecasts point back at their own class? Evenly spaced sample, top-3 diagnosis recovery."""
    rows = build(spine)
    step = max(1, len(rows) // sample)
    pick = rows[::step][:sample]
    hit = sum(1 for r in pick if r["problem_id"] in [m["id"] for m in spine.diagnose(r["text"], k=3)["matches"]])
    return {"sampled": len(pick), "top3_recovery": round(hit / max(1, len(pick)), 3)}
