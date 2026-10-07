"""Spine engine: diagnose, choose the best playbook, compose new solutions, forecast risk.

Predetermined: the catalog in problems.py answers known problem classes instantly, with no model.
Learning: each playbook variant keeps a success record; Thompson sampling picks the variant that has
worked best, so workflows optimize themselves. Novel problems get a composed candidate plan built from
analogous playbooks, learned facts and historic failures; a candidate that succeeds twice without a
failure is promoted into the catalog as a verified entry.
"""
import json
import math
import random
import re
import sqlite3
import threading
import time

from nexen.core import paths
from nexen.shared.utils import textsim
from nexen.features.spine.problems import CATALOG

CONFIDENT = 0.30
SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY, ts TEXT, problem_id TEXT, variant TEXT, success INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS occurrences(id INTEGER PRIMARY KEY, ts TEXT, problem_id TEXT, fp TEXT UNIQUE, source TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS failures(id INTEGER PRIMARY KEY, ts TEXT, fp TEXT UNIQUE, source TEXT, text TEXT, problem_id TEXT, score REAL);
CREATE TABLE IF NOT EXISTS novel(id TEXT PRIMARY KEY, ts TEXT, signature TEXT, query TEXT, plan TEXT, status TEXT, successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, promoted_as TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts TEXT, question TEXT, record TEXT, outcome INTEGER);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Spine:
    def __init__(self, db_path=None, ledger=None, rng=None):
        self.path = str(db_path or (paths.DATA / "spine.db"))
        if self.path != ":memory:":
            paths.ensure_data()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()
        self.ledger = ledger
        self.rng = rng or random.Random()
        self.problems = {p["id"]: p for p in CATALOG}
        self._load_promoted()
        self._index()

    # ----------------------------------------------------------------- catalog index
    def _load_promoted(self):
        with self.lock:
            for r in self.db.execute("SELECT promoted_as, plan, query FROM novel WHERE status='promoted'"):
                plan = json.loads(r["plan"])
                self.problems[r["promoted_as"]] = {
                    "id": r["promoted_as"], "area": plan.get("area", "novel"), "title": plan["title"], "severity": plan.get("severity", 3),
                    "signals": [], "symptoms": [r["query"]], "triggers": plan.get("triggers", []), "causes": plan.get("hypotheses", []),
                    "prevent": [], "playbooks": [{"id": r["promoted_as"] + "-A", "steps": plan["steps"], "verify": plan["verify"],
                                                   "rollback": plan["rollback"], "ext": plan.get("ext", False)}],
                    "base_rate": 0.2, "evidence": "promoted"}

    @staticmethod
    def _tok(text):
        """Tokens with a crude suffix stemmer so lock/locked/locking and time/timed/timeout meet."""
        out = []
        for t in textsim.tokens(text):
            for suf in ("ing", "ed", "es", "ly", "s"):
                if len(t) > len(suf) + 3 and t.endswith(suf):
                    t = t[: -len(suf)]
                    break
            out.append(t)
        return out

    def _index(self, leave_out=None, language_only=False):
        """Precompute regexes and idf over the catalog. `leave_out` = (problem id, symptom) for the held-out eval.

        Each problem is matched against: its symptoms, a context document (title, causes, triggers, prevention) and,
        unless `language_only`, a signal document made of its error-pattern words.
        """
        self.rx, self.docs, df = {}, {}, {}
        for pid, p in self.problems.items():
            self.rx[pid] = [re.compile(s, re.I) for s in p["signals"]]
            syms = [s for s in p["symptoms"] if not (leave_out and leave_out == (pid, s))]
            docs = [self._tok(p["title"] + " " + s) for s in syms]
            docs.append(self._tok(" ".join([p["title"]] + p["causes"] + p["triggers"] + p["prevent"])))
            if not language_only and p["signals"]:
                docs.append(self._tok(" ".join(re.sub(r"[\\\[\]\(\)\.\*\+\?\|\^\$\{\}]", " ", s) for s in p["signals"])))
            self.docs[pid] = docs
            for t in set(t for d in docs for t in d):
                df[t] = df.get(t, 0) + 1
        self.df, self.n_docs = df, max(1, len(self.problems))

    # ----------------------------------------------------------------- diagnosis
    def _counts(self, pid):
        with self.lock:
            occ = self.db.execute("SELECT COUNT(*) c FROM occurrences WHERE problem_id=?", (pid,)).fetchone()["c"]
            ok = self.db.execute("SELECT COUNT(*) c FROM outcomes WHERE problem_id=? AND success=1", (pid,)).fetchone()["c"]
            bad = self.db.execute("SELECT COUNT(*) c FROM outcomes WHERE problem_id=? AND success=0", (pid,)).fetchone()["c"]
        return occ, ok, bad

    def diagnose(self, text, k=3):
        text = text or ""
        toks = self._tok(text)
        scored = []
        for pid, p in self.problems.items():
            hits = sum(1 for rx in self.rx[pid] if rx.search(text))
            sig = min(hits, 3) / 3.0
            sym = max((textsim.tfidf_cosine(toks, d, self.df, self.n_docs) for d in self.docs[pid]), default=0.0)
            score = max(0.6 * sig + 0.4 * sym, sym)
            if score > 0:
                score += 0.03 * math.log1p(self._counts(pid)[0])
            scored.append((score, pid, hits))
        scored.sort(key=lambda x: -x[0])
        out = [{"id": pid, "title": self.problems[pid]["title"], "area": self.problems[pid]["area"], "score": round(s, 3),
                "signal_hits": h, "severity": self.problems[pid]["severity"]} for s, pid, h in scored[:k] if s > 0.05]
        top = out[0]["score"] if out else 0.0
        return {"matches": out, "confident": top >= CONFIDENT, "top_score": top, "novel": top < CONFIDENT}

    # ----------------------------------------------------------------- playbooks that optimize themselves
    def pick_variant(self, pid, explore=True):
        p = self.problems[pid]
        best, best_draw = None, -1.0
        for v in p["playbooks"]:
            with self.lock:
                ok = self.db.execute("SELECT COUNT(*) c FROM outcomes WHERE variant=? AND success=1", (v["id"],)).fetchone()["c"]
                bad = self.db.execute("SELECT COUNT(*) c FROM outcomes WHERE variant=? AND success=0", (v["id"],)).fetchone()["c"]
            draw = self.rng.betavariate(1 + ok, 1 + bad) if explore else (1 + ok) / (2 + ok + bad)
            if draw > best_draw:
                best, best_draw = v, draw
        return best

    def solution(self, pid, explore=True):
        p = self.problems[pid]
        v = self.pick_variant(pid, explore)
        return {"problem": pid, "title": p["title"], "severity": p["severity"], "variant": v["id"], "steps": v["steps"], "verify": v["verify"],
                "rollback": v["rollback"], "external_effects": v["ext"], "causes": p["causes"], "prevent": p["prevent"], "evidence": p["evidence"]}

    def record_outcome(self, ident, success, variant=None, note=""):
        """ident is a catalog problem id or a candidate id (N-...). Candidate success counts toward promotion."""
        if ident.startswith("N-"):
            return self._novel_outcome(ident, success)
        if ident not in self.problems:
            raise KeyError(ident)
        variant = variant or self.problems[ident]["playbooks"][0]["id"]
        with self.lock:
            self.db.execute("INSERT INTO outcomes(ts,problem_id,variant,success,note) VALUES(?,?,?,?,?)", (_now(), ident, variant, int(bool(success)), note[:300]))
            self.db.commit()
        return {"ok": True, "problem": ident, "variant": variant, "success": bool(success)}

    # ----------------------------------------------------------------- novel solutions
    def compose_novel(self, text, context="", recall=None, failures=None, consult=None):
        """Build a candidate plan for a problem the catalog does not cover. Every step cites where it came from."""
        d = self.diagnose(text, k=3)
        gates = [m["id"] for m in self.premortem(text)["risks"] if m["id"].startswith("POL-")]
        steps, causes, cite = [], [], []
        if gates:
            steps.append("Gate first: %s need the owner; prepare drafts only and queue the exact action." % ", ".join(gates))
            cite.append({"kind": "policy", "ids": gates})
        steps.append("Reproduce or observe the problem and save the exact input and output as evidence.")
        for m in d["matches"]:
            p = self.problems[m["id"]]
            causes += p["causes"][:1]
            steps += [s for s in p["playbooks"][0]["steps"][:2] if s not in steps]
            cite.append({"kind": "analogous-playbook", "id": m["id"], "score": m["score"]})
        for r in (recall or [])[:3]:
            cite.append({"kind": "learned", "id": r["id"], "trust": r.get("trust")})
            causes.append("Learned note %s: %s" % (r["id"], r["text"][:140].replace("\n", " ")))
        for f in (failures or [])[:3]:
            cite.append({"kind": "historic-failure", "text": f["text"][:140]})
            steps.append("Avoid repeating: %s" % f["text"][:140].replace("\n", " "))
        steps += ["Apply the smallest change that addresses the cause.", "Run the full test suite and the real-input check."]
        plan = {"title": "Candidate for: " + text[:80], "hypotheses": causes[:5] or ["Unknown: gather evidence first"], "steps": steps[:12],
                "verify": ["The original symptom is gone on the same input", "The full suite passes", "A regression test captures this case"],
                "rollback": ["Restore the backup or revert the last change"], "ext": bool(gates), "citations": cite, "area": d["matches"][0]["area"] if d["matches"] else "novel",
                "severity": d["matches"][0]["severity"] if d["matches"] else 3, "triggers": textsim.key_terms(text, 4)}
        model_note = None
        if consult is not None:
            try:
                model_note = consult(text, plan)
            except Exception as e:  # a model outage never blocks the deterministic plan
                model_note = {"error": "%s: %s" % (type(e).__name__, e)}
        sig = textsim.fingerprint(" ".join(sorted(textsim.key_terms(text, 6))))[:12]
        with self.lock:
            row = self.db.execute("SELECT id,status,promoted_as FROM novel WHERE signature=?", (sig,)).fetchone()
            if row:
                ident, status, promoted = row["id"], row["status"], row["promoted_as"]
            else:
                ident, status, promoted = "N-" + sig, "candidate", None
                self.db.execute("INSERT INTO novel(id,ts,signature,query,plan,status) VALUES(?,?,?,?,?,'candidate')", (ident, _now(), sig, text[:400], json.dumps(plan)))
                self.db.commit()
        return {"id": ident, "status": status, "promoted_as": promoted, "plan": plan, "model": model_note, "novel": True}

    def _novel_outcome(self, ident, success):
        col = "successes" if success else "failures"
        with self.lock:
            row = self.db.execute("SELECT * FROM novel WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise KeyError(ident)
            self.db.execute("UPDATE novel SET %s=%s+1 WHERE id=?" % (col, col), (ident,))
            self.db.commit()
            row = self.db.execute("SELECT * FROM novel WHERE id=?", (ident,)).fetchone()
        promoted = None
        if row["status"] == "candidate" and row["successes"] >= 2 and row["failures"] == 0:
            plan = json.loads(row["plan"])
            if plan.get("verify") and plan.get("steps"):
                promoted = "NOV-%s" % row["signature"][:6].upper()
                with self.lock:
                    self.db.execute("UPDATE novel SET status='promoted', promoted_as=? WHERE id=?", (promoted, ident))
                    self.db.commit()
                self._load_promoted()
                self._index()
        return {"ok": True, "candidate": ident, "successes": row["successes"], "failures": row["failures"], "promoted_as": promoted}

    def resolve(self, text, context="", recall=None, failures=None, consult=None):
        """One call for the autonomous loop: known problem -> predetermined playbook; unknown -> composed candidate."""
        d = self.diagnose(text)
        if d["confident"]:
            sol = self.solution(d["matches"][0]["id"])
            return {"kind": "known", "diagnosis": d, "solution": sol, "premortem": self.premortem(text + " " + " ".join(sol["steps"]))}
        nov = self.compose_novel(text, context, recall, failures, consult)
        return {"kind": "novel", "diagnosis": d, "candidate": nov}

    # ----------------------------------------------------------------- real-time risk
    def rate(self, pid):
        """Estimated chance this problem class hits a run: smoothed history over the catalog's prior."""
        p = self.problems[pid]
        occ, ok, bad = self._counts(pid)
        n, f = occ + ok + bad, occ + bad
        return round((f + 4 * p.get("base_rate", 0.1)) / (n + 4), 3)

    def premortem(self, plan_text, indicators=None):
        """Which problem classes is this plan likely to hit, how likely, and what prevents each."""
        low = " " + " ".join(textsim.normalize(plan_text).split()) + " "
        risks = []
        for pid, p in self.problems.items():
            hit = [t for t in p["triggers"] if (" " + textsim.normalize(t) + " ") in low]
            if not hit:
                continue
            prob = self.rate(pid)
            risks.append({"id": pid, "title": p["title"], "area": p["area"], "trigger_words": hit[:4], "probability": prob,
                          "severity": p["severity"], "expected_cost": round(prob * p["severity"], 3), "prevent": p["prevent"][:2],
                          "playbook": p["playbooks"][0]["steps"][:2]})
        risks.sort(key=lambda r: -r["expected_cost"])
        live = []
        for ind in indicators or []:
            if ind.get("state") in {"warn", "bad"}:
                live.append(ind)
        blocked = [r for r in risks if r["id"] == "INF-001"] or [i for i in live if i.get("problem") == "INF-001"]
        gated = [r["id"] for r in risks if r["id"].startswith("POL-")]
        go = "blocked by STOP" if blocked else ("needs owner approval" if gated else ("proceed with mitigations" if risks else "proceed"))
        return {"risks": risks[:8], "live": live, "gates": gated, "go": go}

    def stats(self):
        with self.lock:
            return {"problems": len(self.problems), "areas": sorted({p["area"] for p in self.problems.values()}),
                    "outcomes": self.db.execute("SELECT COUNT(*) c FROM outcomes").fetchone()["c"],
                    "occurrences": self.db.execute("SELECT COUNT(*) c FROM occurrences").fetchone()["c"],
                    "failures_mined": self.db.execute("SELECT COUNT(*) c FROM failures").fetchone()["c"],
                    "novel_candidates": self.db.execute("SELECT COUNT(*) c FROM novel WHERE status='candidate'").fetchone()["c"],
                    "promoted": self.db.execute("SELECT COUNT(*) c FROM novel WHERE status='promoted'").fetchone()["c"]}

    # ----------------------------------------------------------------- held-out evaluation
    def evaluate(self):
        """Leave one symptom out per problem and ask whether diagnosis still ranks the right problem.

        `language_only` removes error-pattern regexes and signal words, so it measures paraphrase matching alone (strict).
        `full` keeps the predetermined signals, which is how real error text is diagnosed in production.
        """
        report = {}
        for mode in ("language_only", "full"):
            top1 = top3 = total = 0
            misses = []
            for pid, p in list(self.problems.items()):
                if len(p["symptoms"]) < 2:
                    continue
                for s in p["symptoms"]:
                    self._index(leave_out=(pid, s), language_only=(mode == "language_only"))
                    if mode == "language_only":
                        saved, self.rx[pid] = self.rx[pid], []
                        for other in self.rx:
                            self.rx[other] = []
                    ids = [m["id"] for m in self.diagnose(s, k=3)["matches"]]
                    total += 1
                    top1 += 1 if ids[:1] == [pid] else 0
                    top3 += 1 if pid in ids else 0
                    if pid not in ids:
                        misses.append({"problem": pid, "symptom": s, "got": ids})
            report[mode] = {"cases": total, "top1": round(top1 / total, 3) if total else 0, "top3": round(top3 / total, 3) if total else 0,
                            "misses": misses[:12]}
        self._index()
        return report
