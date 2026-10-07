"""Self-tuning of the gate. This is the recursive part that edits the learner itself.

It stays safe because every change is: whitelisted (five numeric parameters), bounded,
validated on replayed labeled decisions, blocked by the golden regression wall,
logged in param_history, and reversible with ``rollback``.
Labels come from owner feedback and from the world: a fact later corroborated is good,
a fact later contradicted is bad. No label means no tuning.
"""
from nexen.features.learning.golden import run_golden
from nexen.features.learning.ledger import PARAM_BOUNDS

STEPS = (0.01, 0.03, 0.06)


def sim_admit(p, d):
    if d["best_sim"] >= p["dup_threshold"] or d["quality"] < p["quality_min"]:
        return False
    if d["best_sim"] >= p["update_threshold"]:
        return True
    return d["novelty"] >= p["novelty_min"]


def objective(p, decisions):
    """Mean utility: a bad admit costs more than a missed good item."""
    if not decisions:
        return 0.0
    total = 0.0
    for d in decisions:
        admit = sim_admit(p, d)
        if admit:
            total += 1.0 if d["label"] == 1 else -1.5
        else:
            total += -0.7 if d["label"] == 1 else 0.2
    return total / len(decisions)


def usable(decisions, p):
    out = []
    for d in decisions:
        if d["op"] in {"ADD", "UPDATE", "HOLD"} or (d["op"] == "NOOP" and d["best_sim"] < p["dup_threshold"]):
            out.append(d)
    return out


class SelfTuner:
    def __init__(self, ledger):
        self.ledger = ledger

    def tune(self, min_labels=12, min_gain=0.01):
        params = self.ledger.params()
        data = usable(self.ledger.labeled_decisions(), params)
        report = {"labels": len(data), "changed": [], "skipped": None}
        if len(data) < min_labels:
            report["skipped"] = "need %d labeled decisions, have %d" % (min_labels, len(data))
            return report
        base_pass, total, _ = run_golden(params)
        current = dict(params)
        score = objective(current, data)
        report["before"] = round(score, 4)
        improved = True
        rounds = 0
        while improved and rounds < 4:
            improved, rounds = False, rounds + 1
            for name, (lo, hi) in PARAM_BOUNDS.items():
                for step in STEPS:
                    for sign in (-1, 1):
                        trial = dict(current)
                        trial[name] = max(lo, min(hi, current[name] + sign * step))
                        if trial[name] == current[name] or trial["update_threshold"] >= trial["dup_threshold"] - 0.05:
                            continue
                        s = objective(trial, data)
                        if s >= score + min_gain:
                            passed, _, _ = run_golden(trial)
                            if passed >= base_pass:
                                current, score, improved = trial, s, True
        for name, value in current.items():
            if abs(value - params[name]) > 1e-9:
                self.ledger.set_param(name, value, "self-tune: replay objective %.3f -> %.3f" % (report["before"], score))
                report["changed"].append({"param": name, "old": params[name], "new": round(value, 4)})
        report["after"] = round(score, 4)
        self.ledger.event("self_tune", None, report)
        return report

    def rollback(self, steps=1):
        with self.ledger.lock:
            rows = [dict(r) for r in self.ledger.db.execute(
                "SELECT * FROM param_history WHERE reason LIKE 'self-tune%' ORDER BY id DESC LIMIT ?", (steps * 5,))]
        undone = []
        seen = set()
        for r in rows:
            if r["name"] in seen or r["old"] is None:
                continue
            seen.add(r["name"])
            self.ledger.set_param(r["name"], r["old"], "rollback of history %d" % r["id"])
            undone.append({"param": r["name"], "restored": r["old"]})
        return undone
