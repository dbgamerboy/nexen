"""Learning orchestrator: trace -> learn -> eval gate, with Novel and Recursive Learning inside.

One cycle:
  1. analyze traces, report poor models, let the swap registry demote them
  2. discover skills: a task shape that keeps succeeding becomes a named recipe (and a playbook candidate)
  3. mine SFT, routing and failure pairs; export a shard for the LoRA / QLoRA pipeline
  4. write lessons into Novel Learning (so recall improves), then run one Recursive Learning pass on the thinnest gap
  5. re-run the held-out spine evaluation and the golden wall; accept the cycle only if neither regressed
Training itself is never started here: it needs the owner's STOP lifted and a free GPU. The cycle only reports whether
enough clean pairs exist and where the shard is.
"""
import json
import re
import time

from .. import gate, paths, textsim
from .traces import verified_success

MIN_SFT = 40


def signature(task):
    return " ".join(sorted(textsim.key_terms(task, 4)))


class Orchestrator:
    def __init__(self, app, brain):
        self.app, self.brain = app, brain

    def discover_skills(self, min_successes=3):
        rows = self.brain.traces.rows(limit=1500)
        groups = {}
        for r in rows:
            if verified_success(r):
                groups.setdefault((r["agent"], signature(r["task"])), []).append(r)
        found = []
        for (agent, sig), rs in groups.items():
            if len(rs) >= min_successes and sig:
                name = "episode:%s:%s" % (agent, sig.replace(" ", "-")[:40])
                self.app.ledger.upsert_skill(name, "Task shape that kept succeeding for %s (%d successes): %s" % (agent, len(rs), sig),
                                             {"agent": agent, "signature": sig, "example": rs[0]["task"][:200], "model": rs[0]["model"]}, True)
                found.append({"skill": name, "successes": len(rs)})
        return found

    def export_shard(self, mined):
        out = paths.DATA / "finetune"
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        sys_prompt = "You are MARVIN, the NEXEN operating assistant. Be direct. Cite receipts. Respect the rules engine and STOP."
        p = out / ("traces-sft-%s.jsonl" % stamp)
        with open(p, "w", encoding="utf-8") as fh:
            for s in mined["sft"]:
                fh.write(json.dumps({"source": "v4:trace:" + s["agent"], "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": s["prompt"]}, {"role": "assistant", "content": s["response"]}]}, ensure_ascii=False) + "\n")
        return str(p)

    def run(self, eval_gate=True):
        res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": {}}
        if gate.stop_active():
            res["note"] = "global STOP active: analysis and learning run, nothing autonomous is dispatched"
        analysis = self.brain.traces.analyze()
        res["steps"]["traces"] = {"n": analysis["traces"], "poor_models": analysis["poor_models"]}
        res["steps"]["swap"] = self.brain.swap.sweep()
        res["steps"]["skills"] = self.discover_skills()
        mined = self.brain.traces.mine()
        res["steps"]["pairs"] = {"sft": len(mined["sft"]), "failure": len(mined["failure"]), "routing": len(mined["routing"])}
        res["steps"]["train_ready"] = len(mined["sft"]) >= MIN_SFT
        if mined["sft"]:
            res["steps"]["shard"] = self.export_shard(mined)
        learned = 0
        for r in mined["routing"]:
            if r["n"] >= 3:
                out = self.app.novel.ingest({"text": "Model %s succeeded %d percent of %d %s tasks in recorded traces." % (r["model"], int(r["success"] * 100), r["n"], r["tier"]),
                                             "source_ids": ["receipt:traces:%s:%s" % (r["tier"], r["model"])], "domain": "learning"})
                learned += out["op"] in {"ADD", "UPDATE"}
        res["steps"]["lessons_learned"] = learned
        before = (self.brain.spine.evaluate()["full"]["top3"], self._golden())
        if not gate.stop_active():
            res["steps"]["recursive"] = self.app.learn_recursive(seconds=20)
        after = (self.brain.spine.evaluate()["full"]["top3"], self._golden())
        res["steps"]["eval"] = {"before": before, "after": after}
        res["accepted"] = (after[0] >= before[0]) and (after[1] >= before[1]) if eval_gate else True
        return res

    @staticmethod
    def _golden():
        from ..learning.golden import run_golden
        return run_golden()[0]
