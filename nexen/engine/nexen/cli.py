"""nexen: one CLI for NEXEN, MARVIN, Codex, Antigravity, Hermes, Claude Code, ChatGPT and the vault."""
import argparse
import json
import sys

from . import VERSION, gate, paths, registry
from .core import CONNECTORS, get_app


def out(obj, as_json=False):
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(obj, str):
        print(obj)
    elif isinstance(obj, list):
        for row in obj:
            if isinstance(row, dict):
                keys = [k for k in ("id", "mtime", "status", "title", "name", "snippet", "label") if k in row]
                print("  ".join(str(row[k])[:110] for k in keys) if keys else json.dumps(row, ensure_ascii=False, default=str)[:200])
            else:
                print(row)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print("%s:" % k)
                for line in json.dumps(v, indent=2, ensure_ascii=False, default=str).splitlines():
                    print("  " + line)
            else:
                print("%s: %s" % (k, v))
    else:
        print(obj)


def build_parser():
    p = argparse.ArgumentParser(prog="nexen", description="NEXEN command line (v%s)" % VERSION)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("status", help="health of every connector, learning stats, STOP state")
    sub.add_parser("modules", help="every registered NEXEN piece with health")
    sub.add_parser("selftest", help="run the V4 test suite")
    dr = sub.add_parser("doctor", help="check every subsystem; --fix repairs what is safe to repair"); dr.add_argument("--fix", action="store_true")
    sub.add_parser("who", help="print the assistant's identity: JARVIS = MARVIN")
    s = sub.add_parser("serve", help="start the V4 app server"); s.add_argument("--port", type=int, default=paths.PORT); s.add_argument("--no-loop", action="store_true")
    sub.add_parser("mcp", help="run as an MCP server over stdio")

    c = sub.add_parser("context", help="search every source and write a context pack")
    c.add_argument("topic"); c.add_argument("--sources", default=""); c.add_argument("-n", type=int, default=4); c.add_argument("--print", action="store_true")

    for name in CONNECTORS:
        cp = sub.add_parser(name, help="%s connector" % name)
        cp.add_argument("verb", nargs="?", default="status")
        cp.add_argument("arg", nargs="*")
        cp.add_argument("-n", type=int, default=10)
        cp.add_argument("--status", default=None)
        cp.add_argument("--timeout", type=int, default=300)

    l = sub.add_parser("learn", help="Novel Learning and Recursive Learning")
    l.add_argument("verb", choices=["novel", "recall", "harvest", "recursive", "gaps", "archive", "stats", "tune", "rollback", "held", "release", "feedback", "skills", "lessons", "frontier", "undo", "reaudit"])
    l.add_argument("arg", nargs="*"); l.add_argument("--source", action="append", default=[]); l.add_argument("--as-of")
    l.add_argument("--strategy", choices=["wide", "balanced", "deep"]); l.add_argument("--seconds", type=int, default=30)
    l.add_argument("--from", dest="frm", default="vault", help="harvest source: vault or a connector name"); l.add_argument("-n", type=int, default=5)

    a = sub.add_parser("approvals", help="owner approval queue for external effects")
    a.add_argument("verb", choices=["list", "approve", "deny"]); a.add_argument("id", nargs="?")

    t = sub.add_parser("track", help="timeline and board"); t.add_argument("verb", choices=["timeline", "board"], nargs="?", default="timeline"); t.add_argument("-n", type=int, default=25)
    h = sub.add_parser("handoff", help="write a handoff note into the vault's nexen folder"); h.add_argument("name"); h.add_argument("--text", default=""); h.add_argument("--file")
    g = sub.add_parser("log", help="append a SESSION-LOG entry"); g.add_argument("--did", required=True); g.add_argument("--receipts", default="none"); g.add_argument("--next", dest="nxt", required=True)
    from . import cli_spine
    cli_spine.register(sub)
    return p


def connector_cmd(args):
    c = CONNECTORS[args.cmd]
    v, rest = args.verb, " ".join(args.arg)
    if v == "status":
        return c.status()
    if v == "recent":
        return c.recent(args.n)
    if v == "read":
        return c.read(rest or ("events" if args.cmd == "marvin" else ""), args.n) if args.cmd != "obsidian" else c.read(rest)
    if v == "search":
        return c.search(rest, args.n)
    if v in {"send", "ask"} and hasattr(c, "send"):
        return c.send(rest, **({"timeout": args.timeout} if args.cmd in {"antigravity", "hermes", "claude"} else {}))
    if v == "packet" and args.cmd == "chatgpt":
        return c.packet(rest, "cli")
    if v == "import" and args.cmd == "chatgpt":
        return {"ok": True, "note": "use: nexen learn novel --source owner:chatgpt-score <text>; scorecard import stays in MARVIN's importer"}
    if args.cmd == "marvin":
        if v == "actions":
            return [{"id": a["id"], "label": a.get("label"), "risk": a.get("risk"), "lane": a.get("lane")} for a in c.actions()]
        if v == "reports":
            return c.reports()
    if args.cmd == "nexen":
        if v == "tasks":
            return c.tasks(status=args.status, query=rest or None, limit=args.n)
        if v == "history":
            return c.history(rest or 0)
        if v == "add":
            return c.add_task(rest)
    if args.cmd == "antigravity" and v == "artifact" and len(args.arg) == 2:
        return c.artifact(args.arg[0], args.arg[1])
    if args.cmd == "obsidian":
        if v == "log":
            return c.tail_log(args.n)
    return {"ok": False, "error": "unknown verb %r for %s" % (v, args.cmd)}


def learn_cmd(args):
    app = get_app()
    v, text = args.verb, " ".join(args.arg)
    if v == "novel":
        return app.novel.ingest({"text": text, "source_ids": args.source, "origin": "owner" if "owner:direct" in args.source else None})
    if v == "recall":
        return app.novel.recall(text, k=args.n, as_of=args.as_of)
    if v == "harvest":
        if args.frm == "vault":
            return app.harvest_vault()
        if args.frm == "brain-index":
            return app.harvest_brain_index()
        return app.harvest_agent(args.frm)
    if v == "recursive":
        return app.learn_recursive(questions=[text] if text else None, strategy=args.strategy, seconds=args.seconds)
    if v == "gaps":
        return app.novel.gaps()
    if v == "archive":
        return app.novel.archive()
    if v == "stats":
        return app.ledger.stats()
    if v == "tune":
        return app.tune()
    if v == "rollback":
        return app.tuner.rollback()
    if v == "held":
        return [{"id": r["id"], "title": r["text"][:100], "status": r["status"]} for r in
                (app.ledger.get(i["id"]) for i in app.ledger.db.execute("SELECT id FROM items WHERE status='held' ORDER BY created_at DESC LIMIT 50"))]
    if v == "release":
        return app.novel.release(args.arg[0])
    if v == "feedback":
        app.novel.feedback(args.arg[0], args.arg[1].lower() in {"good", "yes", "1", "up"})
        return {"ok": True}
    if v == "reaudit":
        return app.novel.reaudit_supersessions()
    if v == "undo":
        return app.novel.undo_supersede(args.arg[0])
    if v == "skills":
        return app.ledger.skills()
    if v == "lessons":
        return app.ledger.lessons(limit=args.n)
    if v == "frontier":
        return app.ledger.frontier(args.n)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = args.json
    if not args.cmd:
        parser.print_help()
        return 0
    try:
        if args.cmd == "status":
            out(get_app().status_all(), as_json)
        elif args.cmd == "modules":
            out([{"id": m["id"], "name": m["name"], "line": m["line"], "state": m["health"]["state"], "detail": m["health"]["detail"]} for m in registry.all_modules()], as_json)
        elif args.cmd == "selftest":
            import unittest
            suite = unittest.defaultTestLoader.discover(str(paths.APP / "tests"), top_level_dir=str(paths.APP))
            res = unittest.TextTestRunner(verbosity=1).run(suite)
            return 0 if res.wasSuccessful() else 1
        elif args.cmd == "doctor":
            from . import reliability
            r = reliability.doctor(fix=args.fix)
            out(r if as_json else "\n".join(["%s %s%s" % ("OK  " if c["ok"] else "FAIL", c["name"], (": " + c["detail"]) if c["detail"] else "") + (" [fixed]" if c["fixed"] else "") for c in r["checks"]]
                                               + ["", "%d checked, %d failed, fixed: %s" % (r["checked"], r["failed"], r["fixed"] or "none")]), as_json)
            return 0 if r["ok"] else 1
        elif args.cmd == "who":
            from . import identity
            out(identity.IDENTITY_STATEMENT, as_json)
        elif args.cmd == "serve":
            from .server import serve
            serve(args.port, loop=not args.no_loop)
        elif args.cmd == "mcp":
            from .mcp_server import run
            run()
        elif args.cmd == "context":
            res = get_app().context_pack(args.topic, [s for s in args.sources.split(",") if s] or None, args.n)
            out(res["text"] if args.print else {"pack": res["path"], "counts": res["counts"], "learned": res["learned"]}, as_json)
        elif args.cmd in CONNECTORS:
            out(connector_cmd(args), as_json)
        elif args.cmd in __import__("nexen.cli_spine", fromlist=["COMMANDS"]).COMMANDS:
            from . import cli_spine
            out(cli_spine.run(args), as_json)
        elif args.cmd == "learn":
            out(learn_cmd(args), as_json)
        elif args.cmd == "approvals":
            if args.verb == "list":
                out(gate.pending(), as_json)
            else:
                out({"ok": gate.decide(args.id, args.verb == "approve")}, as_json)
        elif args.cmd == "track":
            app = get_app()
            out(app.timeline(args.n) if args.verb == "timeline" else app.board(), as_json)
        elif args.cmd == "handoff":
            text = args.text
            if args.file:
                text = open(args.file, encoding="utf-8", errors="replace").read()
            out(CONNECTORS["obsidian"].write_handoff(args.name, text), as_json)
        elif args.cmd == "log":
            out(CONNECTORS["obsidian"].append_session_log(args.did, args.receipts, args.nxt), as_json)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # nothing ends in a traceback: diagnose, record, say what to do next
        from . import reliability
        d = reliability.explain(e, " ".join(sys.argv[1:]))
        reliability._record("cli:" + str(args.cmd), e, d)
        print("nexen error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        print("  likely problem: %s (%s)\n  next action: %s" % (d.get("title"), d.get("problem"), d["next_action"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
