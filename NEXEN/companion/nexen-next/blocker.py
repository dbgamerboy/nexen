"""Shared 'next blocker' logic. Every NEXEN program calls this so the same blocker shows everywhere.
CLI:  python blocker.py        -> prints the owner's next blocker and what Claude, Codex and Antigravity last reported."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
LOG = r"F:\NEXEN_MEMORY\00-Control\SESSION-LOG.md"
LOG_ALT = r"H:\NEXEN\obsidian\NEXEN-Recovered-20261005\00-Control\SESSION-LOG.md"
PACKET = r"H:\NEXEN\handoffs\packet-20261005"

# key, title, what Open does ("tab:X" = app tab, else a path or URL)
ORDER = [
    ("q", "Answer Q1 to Q6", "tab:Questions Q1-Q6"),
    ("fiverr", "Finish and publish the Fiverr gig", "https://www.fiverr.com/"),
    ("tiktok", "Cancel TikTok posts P03 and P05", "https://www.tiktok.com/tiktokstudio/content"),
    ("key", "Rotate the Ollama cloud key", "https://ollama.com/settings/keys"),
    ("train", "Run MARVIN training", "tab:MARVIN training"),
    ("agent", "Start ONE lead agent on Curviana (PROMPT A)", os.path.join(PACKET, "06-PLAN-PROMPTS-AND-CLIENTS.txt")),
    ("f", "F: drive disk check (close agents, restart)", os.path.join(PACKET, "05-STATE-SNAPSHOT.txt")),
    ("pc2", "PC2 launch (optional)", r"%USERPROFILE%\Desktop\MARVIN\Reports\PC2-DO-THIS-NOW.txt"),
    ("assoc", "Amazon Associates and persona handles", "tab:Questions Q1-Q6"),
    ("life", "Housing and unemployment details (Q19, Q20)", os.path.join(PACKET, "02-QUESTIONS-ALL-OF-THEM.txt")),
]


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {"done": {}, "answers": {}}


def next_blocker(state=None):
    """(key, title, target) of the first unticked step, or None."""
    done = (state or load_state()).get("done", {})
    return next(((k, t, o) for k, t, o in ORDER if not done.get(k)), None)


def _read_log():
    for p in (LOG, LOG_ALT):
        try:
            with open(p, "rb") as f:
                f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 400_000))
                return f.read().decode("utf-8", "replace"), p
        except OSError: continue
    return "", None


def agent_of(header):
    parts = [p for p in header.replace("—", "·").split("·")]
    h = (parts[1] if len(parts) >= 3 else header).lower()   # author field only, titles may name other agents
    if "antigravity" in h: return "Antigravity"
    if "codex" in h or "astra" in h: return "Codex"
    if "claude" in h: return "Claude"
    return None


def agents_latest():
    """Latest SESSION-LOG entry per agent: title, blocked-on, next action."""
    text, path = _read_log()
    out = {a: None for a in ("Claude", "Codex", "Antigravity")}
    for chunk in reversed(re.split(r"\n(?=## )", text)):
        head = chunk.split("\n", 1)[0]
        a = agent_of(head)
        if not a or out[a]: continue
        blk = re.search(r"Blocked on:\s*(.+)", chunk); nxt = re.search(r"NEXT ACTION:\s*(.+)", chunk)
        out[a] = {"title": head.lstrip("# ").strip()[:140], "blocked": (blk.group(1).strip() if blk else "none recorded")[:400],
                  "next": (nxt.group(1).strip() if nxt else "none recorded")[:400]}
    return out, path


V4CLI = r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\nexen.cmd"
_v4cache = {}


def v4_recent(agent):
    """Latest conversation for an agent from the V4 connectors (works even if the agent never writes SESSION-LOG). Cached 60 s."""
    import subprocess, time
    key = agent.lower(); hit = _v4cache.get(key)
    if hit and time.time() - hit[0] < 60: return hit[1]
    res = None
    try:
        out = subprocess.run([V4CLI, "--json", key, "recent"], capture_output=True, text=True, timeout=25, creationflags=0x08000000).stdout
        rows = json.loads(out)
        row = next((r for r in rows if r.get("title") or r.get("preview")), rows[0] if rows else None)
        if row: res = f"{row.get('title') or row.get('preview') or row.get('id')} | steps {row.get('steps', '?')} | {str(row.get('mtime') or row.get('updated') or '')[:19]}"
    except Exception:  # noqa: BLE001 - connector missing or slow, tracker still works from SESSION-LOG
        res = None
    _v4cache[key] = (time.time(), res)
    return res


def open_target(target):
    if target.startswith("http"):
        import webbrowser; webbrowser.open(target)
    elif os.path.exists(target): os.startfile(target)


def summary_text():
    b = next_blocker(); lines = []
    lines.append("NEXT BLOCKER (you): " + (f"{b[1]}  ->  {b[2]}" if b else "none, all steps ticked"))
    ag, path = agents_latest()
    for a, e in ag.items():
        lines.append(f"{a}: " + (f"blocked on: {e['blocked'][:110]} | next: {e['next'][:90]}" if e else "no entry in SESSION-LOG"))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary_text())
