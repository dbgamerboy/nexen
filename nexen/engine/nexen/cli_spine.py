"""CLI verbs for the intellect spine, rules, swap registry, world model, schedule, research and the self-improving core."""
import json

from . import gate, paths

def _loads(text):
    """Parse a JSON argument. cmd.exe strips double quotes, so also accept @file and {key:value} with bare words."""
    import re
    text = (text or "").strip()
    if text.startswith("@"):
        text = open(text[1:], encoding="utf-8-sig").read()
    try:
        return json.loads(text)
    except ValueError:
        fixed = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text.replace("'", '"'))
        fixed = re.sub(r':\s*(?!(?:true|false|null)\b)([A-Za-z_][\w.\-]*)\s*(?=[,}])', r': "\1"', fixed)
        return json.loads(fixed)


COMMANDS = {"spine", "rules", "swap", "world", "decide", "ask", "prompt", "brief", "schedule", "research", "agent", "selfcode", "orchestrate", "workflow"}


def register(sub):
    def add(name, help_, verbs=None, agent=False):
        p = sub.add_parser(name, help=help_)
        if verbs:
            p.add_argument("verb", choices=verbs)
        if agent:
            p.add_argument("agent")
        p.add_argument("arg", nargs="*")
        return p
    add("spine", "problem catalog, diagnosis, premortem, live indicators, failures, flaws", ["diagnose", "resolve", "premortem", "indicators", "catalog", "outcome", "failures", "flaws", "eval", "stats", "export", "solution", "forecast", "headstart"])
    add("rules", "rules engine: what any workflow may and may not do", ["status", "check", "set", "use", "run", "matrix", "account"])
    add("swap", "swap registry: models, adapters, methods, hustles, stores, accounts", ["list", "health", "apply", "revert", "sweep", "record", "history", "add", "adapter"])
    add("world", "world model: public signals with honest labels", ["collect", "summary", "facts", "ingest"])
    d = add("decide", "decision fusion over every source"); d.add_argument("--consult", action="store_true"); d.add_argument("--agent", default="marvin"); d.add_argument("--action", default="")
    add("ask", "assemble the full prompt for an agent and ask through the active model", agent=True)
    add("prompt", "show the assembled prompt and its receipt without calling a model", agent=True)
    b = add("brief", "build the small local-model knowledge brief for an agent (or all)")
    s = add("schedule", "the routine", ["plan", "due", "move", "add", "remove", "pause", "resume", "weight", "gaming", "done", "md"]); s.add_argument("--lane", default="research"); s.add_argument("--minutes", type=int, default=30)
    r = add("research", "view learned research, run YouTube research, draft workflows", ["list", "youtube", "draft", "drafts", "models"]); r.add_argument("--domain"); r.add_argument("--origin"); r.add_argument("-n", type=int, default=20)
    ag = add("agent", "run the bounded self-improving agent loop"); ag.add_argument("--name", default="marvin"); ag.add_argument("--no-model", action="store_true")
    sc = add("selfcode", "propose a patch through the tested update path"); sc.add_argument("--files", default=""); sc.add_argument("--auto", action="store_true")
    add("orchestrate", "run one trace -> learn -> eval-gate cycle")
    w = add("workflow", "workflow drafts built from research under the rules", ["draft", "list"]); w.add_argument("--platform", default="tiktok"); w.add_argument("--account", default=None); w.add_argument("--spend", type=float, default=0.0)


def run(args):
    from .brain import get_brain
    from .spine import decide as D, failures, finetune, flaws, research, workflowgen
    b = get_brain()
    c, v, text = args.cmd, getattr(args, "verb", None), " ".join(getattr(args, "arg", []))
    if c == "spine":
        if v == "diagnose":
            return b.spine.diagnose(text)
        if v == "resolve":
            return b.spine.resolve(text)
        if v == "solution":
            return b.spine.solution(text)
        if v == "premortem":
            return b.spine.premortem(text, indicators=b.live_indicators())
        if v == "indicators":
            return b.live_indicators(ttl=0)
        if v == "catalog":
            return [{"id": p["id"], "area": p["area"], "sev": p["severity"], "title": p["title"], "rate": b.spine.rate(p["id"])} for p in b.spine.problems.values()]
        if v == "outcome":
            pid, ok = args.arg[0], args.arg[1].lower() in {"ok", "yes", "success", "1", "true"}
            return b.spine.record_outcome(pid, ok, note=" ".join(args.arg[2:]))
        if v == "failures":
            return failures.mine(b.spine)
        if v == "flaws":
            return flaws.scan([paths.APP / "engine"] + ([paths.V3_APP] if "v3" in text else []))
        if v == "eval":
            return b.spine.evaluate()
        if v == "stats":
            return b.spine.stats()
        if v == "export":
            return finetune.export(b.spine)
        if v == "forecast":
            from .spine import forecast
            sub = args.arg[0] if args.arg else "stats"
            if sub == "generate":
                return {**forecast.generate(b.spine), "self_check": forecast.self_check(b.spine)}
            if sub == "top":
                return forecast.top(b.spine, limit=int(args.arg[1]) if len(args.arg) > 1 else 10)
            if sub == "lookup":
                return forecast.lookup(b.spine, " ".join(args.arg[1:]))
            return forecast.stats(b.spine)
        if v == "headstart":
            from .learning import headstart
            sub = args.arg[0] if args.arg else "all"
            if sub in ("fetch", "all"):
                rep = headstart.fetch(float(args.arg[1]) if len(args.arg) > 1 else 1.0, only=args.arg[2] if len(args.arg) > 2 else None)
                if sub == "fetch":
                    return rep
            res = headstart.ingest(b.app, b.spine)
            return {"fetch": rep if sub == "all" else None, "ingest": res}
    if c == "rules":
        if v == "status":
            return b.rules.status()
        if v == "check":
            return b.rules.check(_loads(text))
        if v == "set":
            return b.rules.set(args.arg[0], _loads(args.arg[1]))
        if v == "use":
            b.rules.record_use(args.arg[0], args.arg[1] if len(args.arg) > 1 else "post")
            return {"ok": True, "posts_today": b.rules.posts_today(args.arg[0])}
        if v == "run":
            return b.rules.record_run(args.arg[0], args.arg[1], float(args.arg[2]), baseline=float(args.arg[3]) if len(args.arg) > 3 else None)
        if v == "matrix":
            return b.rules.scenario_matrix()
        if v == "account":
            return b.rules.upsert_account(_loads(text)) or {"ok": True}
    if c == "swap":
        if v == "list":
            return [{"slot": s["id"], "active": s["active"], "candidates": s["candidates"]} for s in b.swap.slots()]
        if v == "health":
            return [b.swap.health(s["id"]) for s in b.swap.slots()] if not text else b.swap.health(text)
        if v == "apply":
            return b.swap.apply(args.arg[0], args.arg[1], reason="owner")
        if v == "revert":
            return b.swap.revert(text)
        if v == "sweep":
            return b.swap.sweep()
        if v == "record":
            b.swap.record(args.arg[0], float(args.arg[1]), ok=float(args.arg[1]) > 0)
            return {"ok": True}
        if v == "history":
            return b.swap.history_rows()
        if v == "add":
            return b.swap.add_candidate(args.arg[0], args.arg[1])
        if v == "adapter":
            from .spine.models import register_adapter
            return register_adapter(args.arg[0], args.arg[1], args.arg[2], float(args.arg[3]) if len(args.arg) > 3 else None)
    if c == "world":
        if v == "collect":
            return b.world.collect([t for t in text.split(",") if t] or None)
        if v == "summary":
            return b.world.summary()
        if v == "facts":
            return b.world.facts()
        if v == "ingest":
            return [b.app.novel.ingest(f)["op"] for f in b.world.facts()]
    if c == "decide":
        return D.decide(b, text, agent=args.agent, consult=args.consult, action=_loads(args.action) if args.action else None)
    if c == "ask":
        return b.packs.ask(args.agent, text)
    if c == "prompt":
        return b.packs.prompt(args.agent, text)
    if c == "brief":
        from .spine.packs import AGENTS
        return [b.packs.brief(a) for a in AGENTS] if text in {"", "all"} else b.packs.brief(text)
    if c == "schedule":
        s = b.schedule
        if v == "plan":
            return s.plan()
        if v == "due":
            return s.due()
        if v == "move":
            return s.move(args.arg[0], args.arg[1] if len(args.arg) > 1 else None, int(args.arg[2]) if len(args.arg) > 2 else None)
        if v == "add":
            return s.add(args.arg[0], args.arg[1], args.minutes, args.lane, " ".join(args.arg[2:]) or args.arg[0])
        if v == "remove":
            return s.remove(args.arg[0]) or {"ok": True}
        if v in {"pause", "resume"}:
            return s.pause_lane(args.arg[0], v == "pause") or {"paused": s.state["paused_lanes"]}
        if v == "weight":
            return s.set_weight(args.arg[0], args.arg[1]) or {"ok": True}
        if v == "gaming":
            return s.set_gaming(args.arg[0].lower() in {"on", "1", "true", "yes"}) or {"gaming": s.state["gaming"]}
        if v == "done":
            return s.mark_done(args.arg[0]) or {"ok": True}
        if v == "md":
            return s.render_markdown()
    if c == "research":
        if v == "list":
            return research.items(b.app, text, domain=args.domain, origin=args.origin, limit=args.n)
        if v == "youtube":
            return research.youtube(b.app, text)
        if v == "draft":
            it = research.items(b.app, text, limit=1)
            return workflowgen.draft(it[0]["text"] if it else text, [s["id"] for s in it[0]["sources"]] if it else [], b.rules)
        if v == "drafts":
            return workflowgen.list_drafts()
        if v == "models":
            return {"swap": [{"slot": s["id"], "active": s["active"]} for s in b.swap.slots() if s["id"].startswith(("model", "adapter"))]}
    if c == "agent":
        return b.agent(args.name).run(text, use_model=not args.no_model)
    if c == "selfcode":
        from .marvin import selfcode
        return selfcode.propose(b, text, files=[f for f in args.files.split(",") if f], auto=args.auto)
    if c == "orchestrate":
        return b.orchestrator.run()
    if c == "workflow":
        if v == "list":
            return workflowgen.list_drafts()
        return workflowgen.draft(text, [], b.rules, platform=args.platform, account=args.account, spend=args.spend)
    return {"ok": False, "error": "unknown verb"}
