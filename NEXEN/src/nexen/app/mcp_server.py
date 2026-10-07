"""Minimal MCP server over stdio (newline-delimited JSON-RPC 2.0).

Register once with Claude Code, Codex or Antigravity and every agent can search all sources,
recall learned knowledge, ingest findings, read tasks and hand work to MARVIN or the vault.
Internal actions only; external effects stay behind the owner approval gate.
"""
import json
import sys

from nexen import VERSION
from nexen.core import gate
from nexen.core import CONNECTORS, get_app

TOOLS = [
    ("nexen_status", "Health of every NEXEN connector, learning stats, STOP state.", {}, []),
    ("nexen_context", "Search Codex, Antigravity, Hermes, Claude, ChatGPT exports, MARVIN logs, tasks and the vault for a topic; returns a redacted context pack.",
     {"topic": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}}, ["topic"]),
    ("nexen_recall", "Recall learned facts (Novel Learning ledger) ranked by relevance, trust and recency. Optional as_of for past beliefs.",
     {"query": {"type": "string"}, "k": {"type": "integer"}, "as_of": {"type": "string"}}, ["query"]),
    ("nexen_learn", "Offer a fact to Novel Learning. Needs source ids like file:path, receipt:id, url:..., test:...; no source means it is held.",
     {"text": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}}}, ["text"]),
    ("nexen_research", "Run one Recursive Learning pass over local notes for a question.", {"question": {"type": "string"}}, []),
    ("nexen_tasks", "Read canonical NEXEN tasks (read-only).", {"status": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}}, []),
    ("nexen_read", "Read from a connector: recent or read an id.",
     {"connector": {"type": "string"}, "verb": {"type": "string", "enum": ["recent", "read", "search"]}, "arg": {"type": "string"}, "n": {"type": "integer"}}, ["connector", "verb"]),
    ("nexen_ask", "Send a one-shot prompt to marvin, hermes, antigravity or claude. ChatGPT only gets an outbox packet.",
     {"connector": {"type": "string"}, "prompt": {"type": "string"}}, ["connector", "prompt"]),
    ("nexen_handoff", "Write a handoff note into the vault's nexen folder.", {"name": {"type": "string"}, "text": {"type": "string"}}, ["name", "text"]),
    ("nexen_approvals", "List pending owner approvals for external effects.", {}, []),
    ("nexen_decide", "Decision fusion over the problem catalog, learned facts, failures, world signals, rules and live indicators. Returns recommendation, next action, risks, gates, confidence, evidence.",
     {"question": {"type": "string"}, "agent": {"type": "string"}, "consult": {"type": "boolean"}}, ["question"]),
    ("nexen_diagnose", "Match an error or symptom to the predetermined problem catalog and return the best playbook, or a composed candidate for a novel problem.", {"text": {"type": "string"}}, ["text"]),
    ("nexen_premortem", "Forecast what could go wrong with a plan, with probabilities, prevention and gates.", {"plan": {"type": "string"}}, ["plan"]),
    ("nexen_rules_check", "Check an action (post, spend, clip, account_create, experiment) against the rules engine; returns verdict and lawful alternatives.", {"action": {"type": "object"}}, ["action"]),
    ("nexen_prompt", "Assemble the full knowledge-pack prompt for an agent (marvin, coder, clipper, dropship, research, benefits, content, infra, swarm; jarvis is accepted as an alias of marvin) with its receipt.", {"agent": {"type": "string"}, "task": {"type": "string"}}, ["agent", "task"]),
    ("nexen_schedule", "Today's routine, what is due, and priority order.", {}, []),
    ("nexen_world", "World-model summary with what each signal measures.", {}, []),
    ("nexen_modules", "List standalone modules MARVIN can run, flagging which ones have outbound code and need owner approval.", {}, []),
    ("nexen_module_run", "Run one listed module in an isolated subprocess. Outbound modules are queued for owner approval and never run from here.",
     {"name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}, "timeout": {"type": "integer"}}, ["name"]),
]


def call(name, a):
    app = get_app()
    if name == "nexen_status":
        return app.status_all()
    if name == "nexen_modules":
        from nexen.features.modules import modbridge
        return modbridge.catalog()
    if name == "nexen_module_run":
        from nexen.features.modules import modbridge
        return modbridge.run(a["name"], a.get("args"), timeout=int(a.get("timeout", 20)))
    if name == "nexen_context":
        r = app.context_pack(a["topic"], a.get("sources"))
        return {"pack_path": r["path"], "text": r["text"][:12000]}
    if name == "nexen_recall":
        return app.novel.recall(a["query"], k=int(a.get("k", 5)), as_of=a.get("as_of"))
    if name == "nexen_learn":
        return app.novel.ingest({"text": a["text"], "source_ids": a.get("source_ids") or []})
    if name == "nexen_research":
        return app.learn_recursive(questions=[a["question"]] if a.get("question") else None)
    if name == "nexen_tasks":
        return CONNECTORS["nexen"].tasks(status=a.get("status"), query=a.get("query"), limit=int(a.get("limit", 30)))
    if name == "nexen_read":
        c = app.conn(a["connector"])
        v, arg, n = a["verb"], a.get("arg", ""), int(a.get("n", 10))
        return c.recent(n) if v == "recent" else (c.search(arg, n) if v == "search" else c.read(arg, n))
    if name == "nexen_ask":
        c = app.conn(a["connector"])
        if a["connector"] == "chatgpt":
            return c.packet(a["prompt"], "mcp")
        if not hasattr(c, "send"):
            return {"ok": False, "error": "no send channel for " + a["connector"]}
        return c.send(a["prompt"])
    if name == "nexen_handoff":
        return CONNECTORS["obsidian"].write_handoff(a["name"], a["text"])
    if name == "nexen_approvals":
        return gate.pending()
    if name in {"nexen_decide", "nexen_diagnose", "nexen_premortem", "nexen_rules_check", "nexen_prompt", "nexen_schedule", "nexen_world"}:
        from nexen.features.marvin.brain import get_brain
        from nexen.features.spine import decide as D
        b = get_brain()
        if name == "nexen_decide":
            return D.decide(b, a["question"], agent=a.get("agent", "marvin"), consult=bool(a.get("consult")))
        if name == "nexen_diagnose":
            return b.spine.resolve(a["text"])
        if name == "nexen_premortem":
            return b.spine.premortem(a["plan"], indicators=b.live_indicators())
        if name == "nexen_rules_check":
            return b.rules.check(a["action"])
        if name == "nexen_prompt":
            return b.packs.prompt(a["agent"], a["task"])
        if name == "nexen_schedule":
            return {"due": b.schedule.due(), "plan": b.schedule.plan()}
        return b.world.summary()
    raise KeyError(name)


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def run():
    schema = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "required": r}} for n, d, p, r in TOOLS]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                                                            "capabilities": {"tools": {}}, "serverInfo": {"name": "nexen", "version": VERSION}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": schema}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                res = call(p.get("name"), p.get("arguments") or {})
                _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, default=str)[:60000]}]}})
            except Exception as e:
                from nexen.core import reliability
                d = reliability.explain(e, str(p.get("name")))
                reliability._record("mcp:" + str(p.get("name")), e, d)
                _send({"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [{"type": "text", "text": "%s: %s | likely problem: %s | next action: %s" % (type(e).__name__, e, d.get("title"), d["next_action"])}]}})
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})
