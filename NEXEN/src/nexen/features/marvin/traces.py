"""Trace store: every agent episode, with enough to learn from it.

An episode is the prompt receipt, the model and adapter used, the complexity tier, latency, outcome and any feedback.
The analyzer turns traces into three kinds of training signal: SFT pairs (successful, well-scored episodes), routing
pairs (which model succeeded at which complexity tier) and failure pairs (for DPO). It also reports poor model and
agent combinations so the swap registry can act.
"""
import json
import hashlib
import re
import sqlite3
import stat
import threading
import time
from pathlib import Path

from nexen.core import paths

SCHEMA = """CREATE TABLE IF NOT EXISTS traces(id INTEGER PRIMARY KEY, ts REAL, agent TEXT, task TEXT, answer TEXT, tier TEXT, complexity REAL,
 model TEXT, adapter TEXT, seconds REAL, ok INTEGER, score REAL, receipt TEXT, tools TEXT, feedback TEXT);"""

_CODE = re.compile(r"```|\bdef\s|\bclass\s|\bimport\s|=>|#include", re.I)
_REASON = re.compile(r"\bexplain\b|\banalyze\b|\bcompare\b|\bwhy\b|\bstep[- ]by[- ]step\b|\btrade-?offs?\b|\bevaluate\b|\bplan\b", re.I)
_MULTI = re.compile(r"\bthen\b.*\bthen\b|\bfirst\b.*\bnext\b|\bstep\s*\d|\b\d+\.\s", re.I | re.S)
TIERS = [(0.15, "trivial", 512), (0.30, "simple", 1024), (0.50, "moderate", 2048), (0.75, "complex", 4096), (9.0, "very_complex", 8192)]
OUTCOME_SCHEMA = "nexen.v4.agent-outcome.v1"
PROOF_VERIFIER = "nexen.v4.local-artifact.v1"
FAILURE_STATUSES = {"model_failed", "tool_failed", "partial_actions", "verification_failed", "planning_failed"}
MAX_PROOF_BYTES = 16 * 1024 * 1024


def validate_local_artifact(proof, root, observed_paths):
    """Validate evidence returned by a trusted local acceptance checker, never model JSON.

    The caller admits root; the artifact must also occur in an actual successful
    tool result from this episode. Passed checks describe that job's acceptance,
    not public sales. No source/credential/provider operation is performed here.
    """
    if not isinstance(proof, dict) or root is None:
        raise ValueError("trusted proof and admitted root required")
    if not isinstance(proof.get("path"), str) or not isinstance(proof.get("sha256"), str):
        raise ValueError("artifact identity required")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", proof["sha256"]):
        raise ValueError("SHA-256 required")
    checks = proof.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip() or c.get("passed") is not True for c in checks):
        raise ValueError("named passed acceptance checks required")
    if not isinstance(proof.get("job_id"), str) or not proof["job_id"].strip() or not isinstance(proof.get("job_kind"), str) or not proof["job_kind"].strip():
        raise ValueError("job identity and kind required")
    root, artifact = Path(root), Path(proof["path"])
    if not root.is_absolute() or not artifact.is_absolute() or ".." in root.parts or ".." in artifact.parts:
        raise ValueError("absolute non-traversing proof paths required")
    root, artifact = root.absolute(), artifact.absolute()
    if artifact not in {Path(p).absolute() for p in observed_paths}:
        raise ValueError("artifact was not returned by this episode's tool")
    artifact.relative_to(root)
    for component in (artifact, *artifact.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("reparse proof refused")
    before = artifact.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PROOF_BYTES:
        raise ValueError("bounded ordinary artifact required")
    with artifact.open("rb") as stream:
        data = stream.read(MAX_PROOF_BYTES + 1)
    after = artifact.stat()
    if len(data) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("artifact changed during verification")
    digest = hashlib.sha256(data).hexdigest()
    if digest != proof["sha256"].lower():
        raise ValueError("artifact hash mismatch")
    return {"kind": "local_artifact", "validated": True, "validated_by": PROOF_VERIFIER,
            "path": str(artifact), "root": str(root), "sha256": digest, "bytes": len(data),
            "checks": checks, "job_id": proof["job_id"], "job_kind": proof["job_kind"]}


def episode_outcome(row):
    try:
        receipt = row.get("receipt") or {}
        receipt = json.loads(receipt) if isinstance(receipt, str) else receipt
        outcome = receipt.get("outcome") if isinstance(receipt, dict) else None
        if isinstance(outcome, dict) and outcome.get("schema") == OUTCOME_SCHEMA and outcome.get("status") in FAILURE_STATUSES | {"planning_only", "response_unverified", "verified_success"}:
            return outcome
    except (TypeError, ValueError):
        pass
    return {"status": "legacy_unverified", "verified": False}


def verified_success(row):
    outcome = episode_outcome(row)
    proof = outcome.get("proof") or {}
    return bool(row.get("ok") and outcome.get("status") == "verified_success" and outcome.get("verified") is True
                and isinstance(proof, dict) and proof.get("validated") is True and proof.get("validated_by") == PROOF_VERIFIER
                and re.fullmatch(r"[0-9a-f]{64}", str(proof.get("sha256", "")))
                and isinstance(proof.get("checks"), list) and proof["checks"]
                and all(isinstance(c, dict) and c.get("passed") is True and c.get("name") for c in proof["checks"]))


def complexity(query):
    """0..1 difficulty estimate from length, code, reasoning, multi-step and multi-part signals. Concept after OpenJarvis (Apache-2.0)."""
    q = query or ""
    n = len(q)
    length = 0.0 if n < 20 else 0.3 if n < 100 else 0.6 if n < 300 else 0.8 if n < 800 else 1.0
    score = 0.2 * length
    score += 0.25 * (0.7 if _CODE.search(q) else 0.0)
    r = 0.6 if _REASON.search(q) else 0.0
    if _MULTI.search(q):
        r = max(r, 0.8) if not r else 1.0
    score += 0.25 * r
    parts = q.count("?") + len(re.findall(r"^\s*(\d+[.)]|[-*])\s", q, re.M))
    score += 0.15 * (0.0 if parts <= 1 else 0.5 if parts <= 3 else 1.0)
    score += 0.15 * (0.7 if re.search(r"\b(write|draft|design|create|compose|generate)\b", q, re.I) else 0.0)
    score = round(min(1.0, score), 3)
    for cap, tier, tokens in TIERS:
        if score < cap:
            return {"score": score, "tier": tier, "max_tokens": tokens}


class TraceStore:
    def __init__(self, db_path=None):
        self.path = str(db_path or (paths.DATA / "traces.db"))
        if self.path != ":memory:":
            paths.ensure_data()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def record(self, agent, task, answer, model, ok, seconds=0.0, score=None, receipt=None, tools=None, adapter="base", feedback=None):
        c = complexity(task)
        with self.lock:
            cur = self.db.execute("INSERT INTO traces(ts,agent,task,answer,tier,complexity,model,adapter,seconds,ok,score,receipt,tools,feedback) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (time.time(), agent, task[:4000], (answer or "")[:6000], c["tier"], c["score"], model, adapter, seconds, int(bool(ok)), score,
                                   json.dumps(receipt or {}), json.dumps(tools or []), feedback))
            self.db.commit()
            return cur.lastrowid

    def feedback(self, trace_id, good, note=""):
        with self.lock:
            self.db.execute("UPDATE traces SET score=?, feedback=? WHERE id=?", (1.0 if good else 0.0, note[:300], trace_id))
            self.db.commit()

    def rows(self, agent=None, limit=500):
        sql, a = "SELECT * FROM traces", []
        if agent:
            sql += " WHERE agent=?"
            a.append(agent)
        sql += " ORDER BY id DESC LIMIT ?"
        a.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, a)]

    def analyze(self, min_n=3):
        rows = self.rows(limit=2000)
        eligible = [r for r in rows if verified_success(r) or episode_outcome(r)["status"] in FAILURE_STATUSES]
        by_model, by_agent = {}, {}
        for r in eligible:
            for key, d in ((r["model"], by_model), (r["agent"], by_agent)):
                s = d.setdefault(key, {"n": 0, "ok": 0, "seconds": 0.0, "score": [], "tiers": {}})
                s["n"] += 1
                s["ok"] += int(verified_success(r))
                s["seconds"] += r["seconds"] or 0
                if r["score"] is not None:
                    s["score"].append(r["score"])
                t = s["tiers"].setdefault(r["tier"], [0, 0])
                t[0] += 1
                t[1] += int(verified_success(r))
        def fold(d):
            out = {}
            for k, s in d.items():
                out[k] = {"n": s["n"], "success": round(s["ok"] / s["n"], 3), "avg_seconds": round(s["seconds"] / s["n"], 1),
                          "avg_score": round(sum(s["score"]) / len(s["score"]), 3) if s["score"] else None,
                          "by_tier": {t: round(v[1] / v[0], 2) for t, v in s["tiers"].items()}}
            return out
        models, agents = fold(by_model), fold(by_agent)
        poor = [{"model": m, "success": v["success"], "n": v["n"]} for m, v in models.items() if v["n"] >= min_n and v["success"] < 0.5]
        return {"traces": len(rows), "evaluated_traces": len(eligible), "unverified_traces": len(rows) - len(eligible),
                "success_basis": "verified local job evidence, not nonempty response text",
                "models": models, "agents": agents, "poor_models": poor}

    def mine(self, min_score=0.7):
        """Training signal from traces: SFT pairs, routing pairs, failure pairs."""
        rows = self.rows(limit=3000)
        sft = [{"agent": r["agent"], "prompt": r["task"], "response": r["answer"]} for r in rows if verified_success(r) and (r["score"] or 0) >= min_score and r["answer"]]
        bad = [{"agent": r["agent"], "prompt": r["task"], "rejected": r["answer"]} for r in rows
               if episode_outcome(r).get("response_origin") == "model"
               and (episode_outcome(r)["status"] in FAILURE_STATUSES or (verified_success(r) and r["score"] is not None and r["score"] < 0.3)) and r["answer"]]
        routing = {}
        for r in rows:
            if not (verified_success(r) or episode_outcome(r)["status"] in FAILURE_STATUSES):
                continue
            k = (r["tier"], r["model"])
            routing.setdefault(k, [0, 0])
            routing[k][0] += 1
            routing[k][1] += int(verified_success(r))
        return {"sft": sft, "failure": bad, "routing": [{"tier": t, "model": m, "n": v[0], "success": round(v[1] / v[0], 2)} for (t, m), v in routing.items()]}
