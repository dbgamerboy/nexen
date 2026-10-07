"""HTTP surface for the intelligence layer, including the n8n gateway.

/api/n8n/marvin is the one door n8n uses: {"op": ..., ...} in, {"ok", "result", "receipt"} out. MARVIN becomes a node
in any workflow: ask him, check an action against the rules, resolve a problem, fetch what is due, run an internal
routine block, learn a fact, draft a workflow from research. External effects are never executed here; they come back
as gates.
"""
import json
import time

from nexen.core import gate, paths
from nexen.features.marvin.brain import get_brain

NOT_HANDLED = object()


def _matrix_page(offset=0, limit=200, status=None):
    p = paths.DATA / "scenario-matrix.json"
    if not p.exists():
        get_brain().rules.config_path = paths.DATA / "rules.json"
        get_brain().rules.scenario_matrix()
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = [r for r in data["rows"] if not status or r["status"] == status]
    return {"summary": data["summary"], "rows": rows[offset:offset + limit], "total": len(rows)}


def run_block(brain, block_id):
    """Run an INTERNAL routine block. External blocks only produce prepared packets for the owner."""
    from nexen.features.spine import failures, finetune
    b = brain.schedule.block(block_id)
    if b is None:
        return {"ok": False, "error": "unknown block"}
    if gate.stop_active() and b.get("internal"):
        return {"ok": False, "skipped": "global STOP: internal block not run", "block": block_id}
    out = {"block": block_id, "lane": b["lane"], "actor": b["actor"]}
    if block_id == "morning-plan":
        md = brain.schedule.render_markdown()
        out["plan"] = md[:1500]
        out["handoff"] = brain.app.conn("obsidian").write_handoff("daily-routine-%s" % time.strftime("%Y%m%d"), md)
    elif block_id == "research":
        out["learning"] = brain.app.learn_recursive(seconds=40)
        out["world"] = brain.world.collect(["artificial intelligence", "tiktok", "youtube", "unemployment", "freelance"], gdelt_gap=6)
        out["facts"] = [brain.app.novel.ingest(f)["op"] for f in brain.world.facts()]
    elif block_id == "infra-health":
        out["swap"] = brain.swap.sweep()
        out["failures"] = {k: v for k, v in failures.mine(brain.spine).items() if k != "unclassified_sample"}
        out["indicators"] = [i for i in brain.live_indicators(ttl=0) if i["state"] != "ok"]
        out["briefs"] = [brain.packs.brief(a)["chars"] for a in __import__("nexen.spine.packs", fromlist=["AGENTS"]).AGENTS]
    elif block_id == "swarm":
        out["tickets"] = [brain.agent("swarm").ticket("Pick the next disjoint packet from the open canonical tickets and prepare it", [], [])]
        out["note"] = "packets prepared, not dispatched; one canary first"
    elif block_id == "training":
        out["orchestrator"] = brain.orchestrator.run()
        out["shard"] = finetune.export(brain.spine)["files"]
        out["note"] = "training is not started here; it needs STOP lifted and a free GPU"
    elif block_id == "quiet":
        out["learning_cycle"] = brain.orchestrator.run()
    else:
        out["note"] = "owner-facing block: packets are prepared by the agents; nothing is sent or posted from here"
        out["tasks"] = brain.schedule.lane_tasks().get(b["lane"], [])
        # Preparing an owner-facing block does not execute its workflow. Keep it
        # due until its actual completion path records the work.
        return {"ok": True, **out, "state": "prepared", "executed": False,
                "schedule_marked_done": False}
    brain.schedule.mark_done(block_id)
    return {"ok": True, **out, "state": "completed-internal-block",
            "executed": True, "schedule_marked_done": True}


def n8n(brain, body):
    op = body.get("op")
    t0 = time.time()
    ops = {
        "ask": lambda: brain.packs.ask(body.get("agent", "marvin"), body["task"]),
        "prompt": lambda: brain.packs.prompt(body.get("agent", "marvin"), body["task"]),
        "decide": lambda: __import__("nexen.spine.decide", fromlist=["decide"]).decide(brain, body["question"], agent=body.get("agent", "marvin"), consult=bool(body.get("consult")), action=body.get("action")),
        "rules_check": lambda: brain.rules.check(body["action"], autonomous=True),
        "resolve": lambda: brain.spine.resolve(body["text"]),
        "premortem": lambda: brain.spine.premortem(body["plan"], indicators=brain.live_indicators()),
        "due": lambda: brain.schedule.due(),
        "run_block": lambda: run_block(brain, body["block"]),
        "learn": lambda: brain.app.novel.ingest({"text": body["text"], "source_ids": body.get("source_ids", [])}),
        "recall": lambda: brain.app.novel.recall(body["query"], k=int(body.get("k", 5))),
        "draft_workflow": lambda: _draft_workflow(brain, body),
        "outcome": lambda: brain.spine.record_outcome(body["id"], bool(body.get("success")), note=body.get("note", "")),
        "status": lambda: {"stop": gate.stop_active(), "indicators": brain.live_indicators(), "due": brain.schedule.due()},
    }
    if op not in ops:
        return {"ok": False, "error": "unknown op", "ops": sorted(ops)}
    from nexen.core import reliability
    r = reliability.run_guarded("n8n:" + str(op), ops[op], retries=1)
    if not r["ok"]:
        if r["error"].startswith("KeyError"):
            return {"ok": False, "error": "missing field %s" % r["error"].split(": ", 1)[-1], "op": op}
        return {"ok": False, "op": op, "error": r["error"], "problem": r["problem"], "next_action": r["next_action"], "degraded": True}
    # An explicit child failure remains a failure at the workflow boundary.
    # A successfully evaluated rules verdict can still be "blocked": that is
    # a valid decision, not a transport/operation error.
    result = r["result"]
    ok = not (isinstance(result, dict) and result.get("ok") is False)
    outcome = "failed" if not ok else (
        "prepared" if isinstance(result, dict) and result.get("state") == "prepared"
        else "evaluated")
    elapsed = round(time.time() - t0, 1)
    gate.audit("n8n_op", {"op": op, "seconds": elapsed, "ok": ok,
                          "outcome": outcome})
    return {"ok": ok, "op": op, "result": result,
            "receipt": {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "seconds": elapsed, "stop": gate.stop_active(),
                        "attempts": r["attempts"], "outcome": outcome,
                        "execution_verified": False}}


GET_PATHS = {"/api/spine/stats", "/api/spine/eval", "/api/spine/indicators", "/api/spine/catalog", "/api/rules/status", "/api/rules/matrix", "/api/swap", "/api/world/summary",
             "/api/schedule/plan", "/api/schedule/due", "/api/schedule/md", "/api/research", "/api/workflows/drafts", "/api/packs", "/api/packs/receipts", "/api/traces", "/api/stores/health"}
POST_PATHS = {"/api/n8n/marvin", "/api/spine/diagnose", "/api/spine/resolve", "/api/spine/premortem", "/api/spine/outcome", "/api/decide", "/api/ask", "/api/prompt", "/api/rules/check",
              "/api/rules/set", "/api/rules/use", "/api/rules/run", "/api/swap/apply", "/api/swap/revert", "/api/swap/sweep", "/api/world/collect", "/api/schedule/move",
              "/api/schedule/pause", "/api/schedule/weight", "/api/schedule/gaming", "/api/schedule/run", "/api/research/youtube", "/api/research/draft", "/api/agent/run", "/api/orchestrate"}


def _draft_workflow(brain, body):
    """Preserve the requested draft scope across both API entry points."""
    from nexen.features.spine.workflowgen import draft
    return draft(body["text"], body.get("source_ids", []), brain.rules,
                 platform=body.get("platform", "tiktok"), account=body.get("account"),
                 daily_posts=body.get("daily_posts", 1), spend=body.get("spend", 0.0),
                 name=body.get("name"))


def get(path, q):
    if path not in GET_PATHS:
        return NOT_HANDLED
    b = get_brain()
    n = int(q.get("n", 20))
    table = {
        "/api/spine/stats": b.spine.stats,
        "/api/spine/eval": b.spine.evaluate,
        "/api/spine/indicators": lambda: b.live_indicators(ttl=0),
        "/api/spine/catalog": lambda: [{"id": p["id"], "area": p["area"], "severity": p["severity"], "title": p["title"], "rate": b.spine.rate(p["id"]),
                                         "steps": p["playbooks"][0]["steps"], "verify": p["playbooks"][0]["verify"], "prevent": p["prevent"], "external": p["playbooks"][0]["ext"]} for p in b.spine.problems.values()],
        "/api/rules/status": b.rules.status,
        "/api/rules/matrix": lambda: _matrix_page(int(q.get("offset", 0)), int(q.get("limit", 200)), q.get("status")),
        "/api/swap": lambda: {"slots": [{**s, "health": b.swap.health(s["id"])} for s in b.swap.slots()], "history": b.swap.history_rows(15)},
        "/api/world/summary": b.world.summary,
        "/api/schedule/plan": b.schedule.plan,
        "/api/schedule/due": b.schedule.due,
        "/api/schedule/md": lambda: {"markdown": b.schedule.render_markdown()},
        "/api/research": lambda: __import__("nexen.spine.research", fromlist=["items"]).items(b.app, q.get("q", ""), q.get("domain"), q.get("origin"), n),
        "/api/workflows/drafts": lambda: __import__("nexen.spine.workflowgen", fromlist=["list_drafts"]).list_drafts(),
        "/api/packs": b.packs.agents,
        "/api/packs/receipts": lambda: b.packs.receipts(n),
        "/api/traces": lambda: {"analysis": b.traces.analyze(), "recent": [{k: r[k] for k in ("id", "agent", "tier", "model", "ok", "seconds")} | {"task": r["task"][:100]} for r in b.traces.rows(limit=n)]},
        "/api/stores/health": b.stores.health,
    }
    if path in table:
        return table[path]()
    return NOT_HANDLED


def post(path, body):
    if path not in POST_PATHS:
        return NOT_HANDLED
    b = get_brain()
    from nexen.features.spine import research as R
    if path == "/api/n8n/marvin":
        return n8n(b, body)
    table = {
        "/api/spine/diagnose": lambda: b.spine.diagnose(body["text"]),
        "/api/spine/resolve": lambda: b.spine.resolve(body["text"]),
        "/api/spine/premortem": lambda: b.spine.premortem(body["plan"], indicators=b.live_indicators()),
        "/api/spine/outcome": lambda: b.spine.record_outcome(body["id"], bool(body.get("success")), note=body.get("note", "")),
        "/api/decide": lambda: __import__("nexen.spine.decide", fromlist=["decide"]).decide(b, body["question"], agent=body.get("agent", "marvin"), consult=bool(body.get("consult")), action=body.get("action")),
        "/api/ask": lambda: b.packs.ask(body.get("agent", "marvin"), body["task"]),
        "/api/prompt": lambda: b.packs.prompt(body.get("agent", "marvin"), body["task"]),
        "/api/rules/check": lambda: b.rules.check(body["action"]),
        "/api/rules/set": lambda: b.rules.set(body["path"], body["value"]),
        "/api/rules/use": lambda: (b.rules.record_use(body["account"], body.get("kind", "post")), {"posts_today": b.rules.posts_today(body["account"])})[1],
        "/api/rules/run": lambda: b.rules.record_run(body["workflow"], body["account"], float(body["metric"]), baseline=body.get("baseline")),
        "/api/swap/apply": lambda: b.swap.apply(body["slot"], body["candidate"], reason="owner"),
        "/api/swap/revert": lambda: b.swap.revert(body["slot"]),
        "/api/swap/sweep": b.swap.sweep,
        "/api/world/collect": lambda: b.world.collect(body.get("topics")),
        "/api/schedule/move": lambda: b.schedule.move(body["id"], body.get("start"), body.get("minutes")),
        "/api/schedule/pause": lambda: (b.schedule.pause_lane(body["lane"], body.get("on", True)), b.schedule.plan()["paused_lanes"])[1],
        "/api/schedule/weight": lambda: (b.schedule.set_weight(body["lane"], body["weight"]), b.schedule.plan()["priority_order"])[1],
        "/api/schedule/gaming": lambda: (b.schedule.set_gaming(body.get("on", True)), b.schedule.state["gaming"])[1],
        "/api/schedule/run": lambda: run_block(b, body["id"]),
        "/api/research/youtube": lambda: R.youtube(b.app, body["query"], videos=int(body.get("videos", 2))),
        "/api/research/draft": lambda: _draft_workflow(b, body),
        "/api/agent/run": lambda: b.agent(body.get("agent", "marvin")).run(body["goal"], use_model=body.get("model", True)),
        "/api/orchestrate": b.orchestrator.run,
    }
    if path in table:
        return table[path]()
    return NOT_HANDLED
