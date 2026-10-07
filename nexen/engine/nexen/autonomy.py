"""Background learning loop. Internal work only; the global STOP marker pauses it.

Each cycle: harvest the old watcher's queue, the vault control notes and recent agent chats into
Novel Learning, run one Recursive Learning pass, self-tune if enough labels exist, write status.
Nothing here publishes, sends, spends or edits V3 files.
"""
import json
import threading
import time
import traceback

from . import gate, paths

_state = {"running": False, "cycles": 0, "last": None, "paused_by_stop": False, "errors": []}
_thread = None
_stop = threading.Event()


def status():
    return dict(_state)


_last = {"world": 0.0, "orchestrate": 0.0, "briefs": 0.0}


def _intelligence(deep=False):
    """Spine upkeep: mine failures, sweep swaps, refresh world, run due internal routine blocks, rebuild briefs, run the learning orchestrator."""
    from . import api_spine
    from .brain import get_brain
    from .spine import failures
    from .spine.packs import AGENTS
    b = get_brain()
    out = {}
    out["failures"] = {k: v for k, v in failures.mine(b.spine).items() if k != "unclassified_sample"}
    out["swap"] = b.swap.sweep()
    now = time.time()
    if deep or now - _last["world"] > 12 * 3600:
        _last["world"] = now
        out["world"] = b.world.collect(["artificial intelligence", "tiktok", "youtube", "unemployment", "freelance"], gdelt_gap=6)
        out["world_facts"] = [b.app.novel.ingest(f)["op"] for f in b.world.facts()]
    ran = []
    for blk in b.schedule.due():
        if blk.get("internal") and not blk.get("blocked_by") and blk["id"] not in {"research", "infra-health", "quiet", "training"}:
            ran.append(api_spine.run_block(b, blk["id"]).get("ok"))
    out["blocks_run"] = ran
    if deep or now - _last["briefs"] > 24 * 3600:
        _last["briefs"] = now
        out["briefs"] = [b.packs.brief(a)["chars"] for a in AGENTS]
    if deep or now - _last["orchestrate"] > 6 * 3600:
        _last["orchestrate"] = now
        out["orchestrator"] = {k: v for k, v in b.orchestrator.run().items() if k in {"accepted", "steps"}}
    return out


def cycle(app, deep=False):
    """One bounded pass. Returns a receipt dict."""
    receipt = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": {}}
    if gate.stop_active():
        receipt["skipped"] = "global STOP is active"
        return receipt

    def step(name, fn):
        try:
            receipt["steps"][name] = fn()
        except Exception as e:
            receipt["steps"][name] = {"error": "%s: %s" % (type(e).__name__, e)}
            _state["errors"] = (_state["errors"] + [name + ": " + str(e)[:160]])[-10:]
            traceback.print_exc()

    step("brain_index", lambda: app.harvest_brain_index())
    step("vault", lambda: app.harvest_vault(max_files=12, max_passages=40))
    for agent in ("codex", "claude", "hermes", "antigravity"):
        step("agent:" + agent, lambda a=agent: app.harvest_agent(a, sessions=2, per_session=6))
    step("recursive", lambda: app.learn_recursive(seconds=45 if deep else 25))
    step("tune", lambda: app.tune())
    step("intelligence", lambda: _intelligence(deep))
    paths.ensure_data()
    (paths.DATA / "loop-status.json").write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    return receipt


def tick(app):
    """One loop iteration. Whatever happens inside, it returns; the loop thread never dies from a cycle."""
    try:
        _state["paused_by_stop"] = gate.stop_active()
        if not _state["paused_by_stop"]:
            _state["last"] = cycle(app)
            _state["cycles"] += 1
    except Exception as e:  # noqa: BLE001
        from . import reliability
        d = reliability.explain(e, "autonomy loop")
        reliability._record("autonomy-loop", e, d)
        _state["errors"] = (_state["errors"] + ["loop: %s -> %s" % (type(e).__name__, d["next_action"][:100])])[-10:]


def start(app, interval=900):
    global _thread
    if _thread and _thread.is_alive():
        return False

    def run():
        _state["running"] = True
        _stop.wait(20)  # let the server settle first
        while not _stop.is_set():
            tick(app)
            _stop.wait(interval)
        _state["running"] = False

    _thread = threading.Thread(target=run, name="v4-learning-loop", daemon=True)
    _thread.start()
    return True


def ensure_alive(app, interval=900):
    """Called by the health probe: restart the loop thread if it has died and nobody asked it to stop."""
    if _stop.is_set():
        return False
    if _thread is not None and not _thread.is_alive():
        return start(app, interval)
    return False


def stop():
    _stop.set()
