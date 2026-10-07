"""Bounded agent loop: goal -> (model chooses a tool) -> observe -> ... -> final answer.

Every prompt goes through the knowledge pack assembler, so each step carries the agent's stores, the spine's premortem,
the rules and the live warnings. Tools are internal and read/learn only; anything external is refused by the gate.
With no model reachable it falls back to the deterministic spine plan, and says so. Each run leaves a trace, a lesson in
Novel Learning and an outcome on the playbook it used, which is how the loop improves.
"""
import json
import re
import time

from nexen.core import gate, paths
from nexen.features.marvin.traces import OUTCOME_SCHEMA, complexity, validate_local_artifact

MAX_STEPS = 6
TOOLS = {
    "search": "search all sources for a topic: {topic}",
    "recall": "recall learned facts: {query}",
    "diagnose": "match an error or symptom to the problem catalog: {text}",
    "premortem": "forecast what could go wrong with a plan: {plan}",
    "rules_check": "check an action against the rules: {action: {type, platform, account, workflow, ...}}",
    "schedule": "show today's routine and what is due",
    "world": "world signals for a topic: {topic}",
    "learn": "store a sourced fact: {text, source_ids}",
    "recursive": "run one bounded research pass: {question}",
    "ticket": "write a work packet for Codex, Claude or Antigravity: {objective, files, checks}",
}


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


class Agent:
    def __init__(self, brain, name="marvin"):
        self.brain, self.name = brain, name

    # ---------------------------------------------------------------- tools
    def tool(self, name, args):
        from nexen.core import reliability
        r = reliability.run_guarded("agent-tool:" + str(name), self._tool, name, args, retries=1)
        return r["result"] if r["ok"] else {"error": r["error"], "next_action": r["next_action"], "problem": r["problem"]}

    def _tool(self, name, args):
        b, app = self.brain, self.brain.app
        gate_ok = gate.check({"learn": "learn", "ticket": "handoff"}.get(name, "read"), "agent tool " + name)
        if not gate_ok["allowed"]:
            return {"refused": gate_ok["reason"]}
        if name == "search":
            return app.context_pack(args["topic"], save=False)["counts"]
        if name == "recall":
            return app.novel.recall(args["query"], k=4)
        if name == "diagnose":
            return b.spine.diagnose(args["text"])
        if name == "premortem":
            return b.spine.premortem(args["plan"])
        if name == "rules_check":
            return b.rules.check(args["action"])
        if name == "schedule":
            return {"due": b.schedule.due(), "top": b.schedule.plan()["priority_order"][:4]}
        if name == "world":
            return b.world.relevant(args.get("topic", ""), 4) or b.world.summary()["topics"][:3]
        if name == "learn":
            return app.novel.ingest({"text": args["text"], "source_ids": args.get("source_ids", [])})
        if name == "recursive":
            return app.learn_recursive(questions=[args["question"]] if args.get("question") else None, seconds=20)
        if name == "ticket":
            return self.ticket(args.get("objective", ""), args.get("files", []), args.get("checks", []))
        return {"error": "unknown tool " + name}

    def ticket(self, objective, files, checks):
        """A work packet in the owner's packet schema. Written, never dispatched."""
        pid = "V4-%s" % time.strftime("%Y%m%d-%H%M%S")
        packet = {"packet_version": 1, "task_id": "", "job_id": pid, "priority": "normal", "objective": objective[:500], "current_decisions": [],
                  "source_citations": [], "coverage_and_missing_inputs": [], "base_revision": "", "file_ownership": files, "interfaces_and_dependencies": [],
                  "acceptance_checks": checks or ["Full test suite passes", "Real-input run output inspected"], "allowed_actions": ["read", "edit owned files", "run tests"],
                  "required_human_inputs": [], "provider_preference": ["claude-opus-5-5 plan", "gpt-6-astra code", "benchmarked local"],
                  "resource_budget": {"wall_time_minutes": 30, "max_attempts": 2, "max_external_spend": 0},
                  "stop_conditions": ["global STOP appears", "tests fail twice"], "result_contract": ["patch", "tests", "artifacts", "changed assumptions", "next step"]}
        out = paths.DATA / "tickets"
        out.mkdir(parents=True, exist_ok=True)
        (out / (pid + ".json")).write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return {"packet": str(out / (pid + ".json")), "status": "prepared, not dispatched"}

    # ---------------------------------------------------------------- the loop
    def run(self, goal, use_model=True, max_steps=MAX_STEPS, verify_job=None, proof_root=None):
        """Keep answers useful; qualify execution only through an admitted local checker.

        verify_job(goal, successful_tool_observations, answer) is trusted Python
        supplied by a qualified handler, not a serialized model/API field. It
        returns a local artifact path/SHA, job id/kind and named acceptance checks.
        proof_root is independently supplied by that handler. Default answers
        and fallback plans are unverified, not successful coding/revenue jobs.
        """
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("nonempty goal required")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= MAX_STEPS:
            raise ValueError("max_steps must be between 1 and %d" % MAX_STEPS)
        b = self.brain
        c = complexity(goal)
        start = time.time()
        steps, answer, model_used = [], None, None
        observations, failures, observed_paths = [], [], []
        model_status = "not_attempted"
        tool_attempted, tool_succeeded = 0, 0
        if use_model:
            tool_help = "\n".join("- %s: %s" % (k, v) for k, v in TOOLS.items())
            transcript = ""
            for i in range(max_steps):
                extra = ("Respond with ONE JSON object only. Either {\"tool\": name, \"args\": {...}} to use a tool, or {\"final\": \"answer\"}.\nTools:\n%s\n%s" % (tool_help, transcript))
                try:
                    r = b.packs.ask(self.name, goal, extra=extra, timeout=120)
                    if not isinstance(r, dict):
                        raise ValueError("invalid model response")
                except Exception as exc:
                    failures.append("model:" + type(exc).__name__)
                    model_status = "failed"
                    steps.append({"step": i, "error": failures[-1]})
                    break
                if not r.get("ok"):
                    errors = r.get("errors") or []
                    if isinstance(errors, list) and errors and isinstance(errors[-1], dict):
                        model_used = errors[-1].get("candidate") or model_used
                    failures.append("model:unavailable")
                    model_status = "failed"
                    steps.append({"step": i, "error": failures[-1]})
                    break
                model_used = r.get("candidate") or model_used
                # Receiving text is not independent proof that a particular
                # provider succeeded: some adapters return fallback text.
                model_status = "fallback_response" if r.get("fallback") else "response_received"
                text = r.get("text") or ""
                if not isinstance(text, str) or not text.strip():
                    failures.append("model:empty_response")
                    model_status = "failed"
                    break
                act = _json(text)
                if not act:
                    answer = text
                    break
                if "final" in act:
                    answer = str(act["final"]) if act["final"] is not None else ""
                    if not answer.strip():
                        failures.append("model:empty_final")
                        model_status = "failed"
                        answer = None
                    break
                tool_attempted += 1
                name, args = str(act.get("tool")), act.get("args", {})
                try:
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                    obs = self.tool(name, args)
                    refused = isinstance(obs, dict) and (obs.get("refused") or obs.get("error") or obs.get("ok") is False)
                except Exception as exc:
                    obs, refused = {"error": "tool:" + type(exc).__name__}, True
                steps.append({"step": i, "tool": name, "status": "failed" if refused else "returned", "observation": json.dumps(obs, default=str)[:300]})
                if refused:
                    failures.append("tool:" + name)
                    break
                tool_succeeded += 1
                observations.append({"tool": name, "result": obs})
                if isinstance(obs, dict):
                    if isinstance(obs.get("packet"), str):
                        observed_paths.append(obs["packet"])
                    artifact = obs.get("artifact")
                    if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                        observed_paths.append(artifact["path"])
                transcript += "\nStep %d: %s -> %s" % (i, json.dumps(act)[:200], json.dumps(obs, default=str)[:600])
            else:
                failures.append("model:step_limit")
        deterministic = answer is None
        if deterministic:
            try:
                res = b.spine.resolve(goal)
                if res["kind"] == "known":
                    s = res["solution"]
                    answer = "Known problem %s (%s). Do: %s. Verify: %s. Gate: %s." % (s["problem"], s["title"], " | ".join(s["steps"][:4]), s["verify"][0], res["premortem"]["go"])
                else:
                    p = res["candidate"]["plan"]
                    answer = "Novel problem; candidate plan %s: %s. Verify: %s." % (res["candidate"]["id"], " | ".join(p["steps"][:5]), p["verify"][0])
            except Exception as exc:
                answer = "No verified execution result. The planning fallback is unavailable."
                failures.append("planning:" + type(exc).__name__)
            model_used = model_used or "deterministic-spine"
        if failures:
            status = "partial_actions" if tool_succeeded else "tool_failed" if any(f.startswith("tool:") for f in failures) else "model_failed" if any(f.startswith("model:") for f in failures) else "planning_failed"
        else:
            status = "planning_only" if deterministic else "response_unverified"
        proof = None
        if verify_job is not None and not failures and not deterministic and tool_succeeded:
            try:
                proof = validate_local_artifact(verify_job(goal, observations, answer), proof_root, observed_paths)
                status = "verified_success"
            except Exception as exc:
                failures.append("verification:" + type(exc).__name__)
                status = "verification_failed"
        outcome = {"schema": OUTCOME_SCHEMA, "status": status, "verified": status == "verified_success",
                   "response_origin": "deterministic_fallback" if deterministic else "model",
                   "model_status": model_status, "provider_success": None,
                   "tool_status": "partial" if tool_succeeded and tool_succeeded != tool_attempted else "failed" if tool_attempted and not tool_succeeded else "returned" if tool_succeeded else "not_attempted",
                   "tool_attempted": tool_attempted, "tool_succeeded": tool_succeeded,
                   "proof": proof, "failure_codes": failures}
        secs = time.time() - start
        tid = b.traces.record(self.name, goal, answer, model_used or "none", outcome["verified"], secs, None, {"tier": c["tier"], "outcome": outcome}, [s.get("tool") for s in steps if s.get("tool")])
        # learn: the episode becomes memory only through the novelty gate and only with a receipt-style source id
        if outcome["verified"]:
            b.app.novel.ingest({"text": "Verified %s job %s for %s produced artifact SHA-256 %s." % (proof["job_kind"], proof["job_id"], self.name, proof["sha256"]), "source_ids": ["receipt:trace:%d" % tid], "domain": "learning"})
        return {"answer": answer, "model": model_used, "deterministic": deterministic, "steps": steps, "trace": tid, "complexity": c, "seconds": round(secs, 1), "ok": outcome["verified"], "outcome": outcome}
