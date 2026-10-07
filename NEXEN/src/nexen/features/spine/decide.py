"""Decision fusion: every decision uses every source, and says which ones it used.

Inputs: the problem catalog (predetermined playbooks), learned facts (Novel Learning, including daily research),
historic failures, the live indicators, the world model, the rules engine, the swap state, the per-agent knowledge pack,
and optionally the active model (fine-tuned adapter when one is registered). The result is a recommendation with a
single next action, the risks, the gates, the confidence and its evidence. With no model consulted it says "no model
consulted"; it never fills the gap with invented reasoning.
"""
import json
import time

from nexen.core import gate


def decide(brain, question, agent="marvin", consult=False, action=None):
    t0 = time.time()
    spine, rules = brain.spine, brain.rules
    ctx = brain.packs.context(agent, question, k=4)
    resolved = spine.resolve(question, recall=[h for h in ctx["hits"] if h["store"] == "v4-ledger"][:3],
                             failures=[h for h in ctx["hits"] if h["store"] == "failures"][:3])
    from nexen.features.spine import indicators
    live = indicators.live(timeout=10)
    pm = spine.premortem(question + " " + (" ".join(resolved["solution"]["steps"]) if resolved["kind"] == "known" else " ".join(resolved["candidate"]["plan"]["steps"])), indicators=live)
    verdict = rules.check(action, autonomous=True) if action else None
    # evidence list with provenance
    evidence = [{"store": h["store"], "id": h["id"], "trust": h.get("trust"), "text": h["text"][:200]} for h in ctx["hits"][:8]]
    # recommendation: deterministic synthesis first
    if resolved["kind"] == "known":
        sol = resolved["solution"]
        rec = "Follow playbook %s (%s, variant %s): %s" % (sol["problem"], sol["title"], sol["variant"], "; ".join(sol["steps"][:4]))
        verify = sol["verify"]
        match_conf = resolved["diagnosis"]["top_score"]
    else:
        plan = resolved["candidate"]["plan"]
        rec = "No catalog match. Candidate plan %s: %s" % (resolved["candidate"]["id"], "; ".join(plan["steps"][:5]))
        verify = plan["verify"]
        match_conf = resolved["diagnosis"]["top_score"] * 0.6
    gates = list(pm["gates"])
    if verdict and verdict["status"] != "allow":
        gates.append("rules: " + verdict["status"] + " " + "; ".join(verdict["blocks"][:2] or verdict["approvals"][:1]))
    bad_live = [i for i in live if i["state"] == "bad"]
    trust_avg = sum((h.get("trust") or 0.3) for h in ctx["hits"][:5]) / max(1, min(5, len(ctx["hits"])))
    conf = round(min(0.95, 0.45 * min(1.0, match_conf / 0.6) + 0.25 * min(1.0, len(ctx["hits"]) / 6) + 0.30 * trust_avg - 0.10 * len(bad_live) - (0.1 if gates else 0)), 2)
    next_action = ("Stop: global STOP is on; prepare drafts and queue the exact action for the owner." if gate.stop_active() and any(g.startswith("POL") for g in gates)
                   else (verify[0] if not pm["risks"] else "Apply the first mitigation: " + (pm["risks"][0]["prevent"][0] if pm["risks"][0]["prevent"] else "check state first")))
    out = {"question": question, "agent": agent, "recommendation": rec, "next_action": next_action, "confidence": max(0.05, conf),
           "kind": resolved["kind"], "risks": pm["risks"][:4], "gates": gates, "go": pm["go"], "live_warnings": [i["detail"] for i in live if i["state"] != "ok"],
           "evidence": evidence, "unavailable_stores": ctx["unavailable"], "verify": verify[:3], "rules": verdict,
           "models": {"chat": brain.swap.current("model.chat"), "adapter": brain.swap.current("adapter." + agent) if agent in {"marvin", "coder", "research", "swarm", "content"} else "base"},
           "model_consulted": False, "seconds": None}
    if consult:
        prompt = ("Given this evidence and the deterministic recommendation, give the single best decision in under 120 words. Keep every gate. "
                  "Question: %s\nRecommendation: %s\nRisks: %s\nGates: %s\nEvidence: %s" % (question, rec, json.dumps([r["title"] for r in pm["risks"][:3]]), gates, json.dumps(evidence[:5])))
        r = brain.packs.ask(agent, prompt, timeout=150)
        out["model_consulted"] = r["ok"]
        out["model"] = {"candidate": r.get("candidate"), "text": r.get("text", "")[:900], "errors": r.get("errors")}
    else:
        out["model_note"] = "no model consulted; recommendation is the deterministic synthesis of the sources above"
    out["seconds"] = round(time.time() - t0, 1)
    with spine.lock:
        spine.db.execute("INSERT INTO decisions(ts,question,record,outcome) VALUES(?,?,?,NULL)", (time.strftime("%Y-%m-%dT%H:%M:%S"), question[:300], json.dumps({k: out[k] for k in ("recommendation", "confidence", "kind", "gates", "go")})))
        spine.db.commit()
    return out
