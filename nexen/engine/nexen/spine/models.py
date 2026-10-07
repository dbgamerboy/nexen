"""Model router with failover and swappable LoRA / QLoRA adapters.

The slot (model.chat, model.code, ...) names the active candidate. A call that fails or returns nothing is recorded
against it, the next candidate in the slot is tried, and the swap registry demotes a candidate that keeps failing.
An adapter slot (adapter.marvin, ...) maps to an Ollama model tag once one has been trained and registered in
adapters.json; until then the slot holds "base" and nothing pretends a tuned model exists.
"""
import json
import time
import urllib.request

from .. import paths
from ..connectors import base
from ..connectors.agents import REGISTRY as AGENTS

ADAPTERS_FILE = "adapters.json"


def _adapters():
    p = paths.DATA / ADAPTERS_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def register_adapter(name, ollama_tag, base_model, eval_score=None, status="trained"):
    """Record a trained adapter: e.g. register_adapter('lora:marvin-v4-spine', 'marvin-v4:latest', 'qwen3-4b', 0.71)."""
    paths.ensure_data()
    data = _adapters()
    data[name] = {"ollama_tag": ollama_tag, "base": base_model, "eval": eval_score, "status": status, "registered": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (paths.DATA / ADAPTERS_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data[name]


def ollama_chat(model, prompt, system=None, timeout=120):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": msgs, "stream": False, "think": False, "options": {"num_ctx": 8192}}).encode()
    req = urllib.request.Request(paths.OLLAMA_URL + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"].strip()


class Models:
    def __init__(self, swap, caller=None):
        self.swap = swap
        self.caller = caller  # tests inject caller(candidate, prompt, system, timeout) -> text

    def adapter_tag(self, agent):
        try:
            active = self.swap.current("adapter." + agent)
        except KeyError:
            return None
        if active == "base":
            return None
        return (_adapters().get(active) or {}).get("ollama_tag")

    def _call(self, cand, prompt, system, timeout, agent):
        if self.caller:
            return self.caller(cand, prompt, system, timeout)
        kind, _, name = cand.partition(":")
        if kind == "strong":
            conn = AGENTS.get(name)
            if conn is None or not hasattr(conn, "send"):
                raise RuntimeError("no send channel for " + name)
            r = conn.send((system + "\n\n" if system else "") + prompt, timeout=timeout)
            if not r.get("ok"):
                raise RuntimeError(str(r.get("error") or r.get("reply"))[:120])
            return r["reply"].strip()
        if kind == "local":
            tag = self.adapter_tag(agent) if agent else None
            return ollama_chat(tag or name, prompt, system, timeout)
        raise RuntimeError("candidate %s is not callable" % cand)

    def consult(self, prompt, slot="model.chat", system=None, timeout=120, agent=None, max_tries=3, prefer_local=False):
        """Try the active candidate, then the rest of the slot in order. Returns text plus which candidate answered."""
        s = self.swap.slot(slot)
        order = [s["active"]] + [c for c in s["candidates"] if c != s["active"]]
        if prefer_local:
            order.sort(key=lambda c: 0 if c.startswith("local:") else 1)
        errors = []
        for cand in order[:max_tries]:
            if cand.startswith(("rule:", "lexical:")):
                continue
            t = time.time()
            try:
                text = self._call(cand, prompt, system, timeout, agent)
                ok = bool(text and len(text.strip()) > 1 and "error" not in text[:40].lower())
                self.swap.record(slot, 1.0 if ok else 0.0, ok, candidate=cand, note="%.1fs" % (time.time() - t))
                if ok:
                    return {"ok": True, "text": base.redact(text), "candidate": cand, "seconds": round(time.time() - t, 1), "tried": [e["candidate"] for e in errors] + [cand]}
                errors.append({"candidate": cand, "error": "empty or error-looking reply"})
            except Exception as e:
                self.swap.record(slot, 0.0, False, candidate=cand, note=type(e).__name__)
                errors.append({"candidate": cand, "error": "%s: %s" % (type(e).__name__, str(e)[:100])})
        return {"ok": False, "text": "", "errors": errors}
