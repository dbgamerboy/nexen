"""The routine: when MARVIN, the swarm and the workflows run, ordered by what keeps the owner housed and paid.

Priority is money and stability first (housing, unemployment, benefits, then Upwork and Fiverr services, then owned
inventory and affiliate), then the 24/7 coding infrastructure that makes money repeatable, then music. Blocks are
data: the owner can move, add, pause or retime any of them at any moment and the plan is rebuilt. A block never
overrides the rules engine or the global STOP; external effects inside a block still wait for the owner.
"""
import json
import re
import time

from nexen.core import gate, paths

LANES = {
    "survival": {"weight": 10, "kw": r"benefits?|unemploy\w*|housing|rent|snap|oregon|multnomah|shelter|eviction|food stamps?|medicaid|section 8|stability", "external": True},
    "services": {"weight": 9, "kw": r"upwork|fiverr|gig|proposal|client|landing page|freelanc|invoice|service offer", "external": True},
    "review": {"weight": 9, "kw": r"approval|owner review|decision", "external": False},
    "infra": {"weight": 8, "kw": r"n8n|ollama|pc2|worker|swarm|v3|v4|marvin|ticket|test|build|workflow|mcp|vault|ingest|lora|train", "external": False},
    "research": {"weight": 7, "kw": r"research|learn|novel|recursive|world|study", "external": False},
    "dropship": {"weight": 7, "kw": r"lumipaw|curviana|curivana|supplier|tiktok shop|product|dropship|amboras|store", "external": True},
    "affiliate": {"weight": 6, "kw": r"affiliate|amazon|commission", "external": True},
    "clipping": {"weight": 6, "kw": r"clip|whop|campaign|shorts", "external": True},
    "training": {"weight": 5, "kw": r"fine.?tune|qlora|lora|dataset|training", "external": False},
    "youtube": {"weight": 4, "kw": r"youtube|channel|faceless|kids", "external": True},
    "persona": {"weight": 3, "kw": r"persona|ai girl|sienna|maya|influencer", "external": True},
    "music": {"weight": 2, "kw": r"music|wdr|beat|stem|mix|master", "external": False},
}
DEFAULT_BLOCKS = [
    {"id": "morning-plan", "start": "06:30", "minutes": 15, "lane": "review", "title": "MARVIN morning plan and overnight receipts", "actor": "marvin", "internal": True},
    {"id": "stability", "start": "07:00", "minutes": 60, "lane": "survival", "title": "Housing, unemployment and benefits: prepare, track deadlines, draft submissions", "actor": "benefits", "internal": False},
    {"id": "services", "start": "08:15", "minutes": 90, "lane": "services", "title": "Upwork and Fiverr: proposals, delivery, outreach drafts (owner sends)", "actor": "dropship", "internal": False},
    {"id": "owner-review-am", "start": "10:00", "minutes": 15, "lane": "review", "title": "Owner approvals queue: one screen, one next action", "actor": "marvin", "internal": False},
    {"id": "inventory", "start": "10:30", "minutes": 90, "lane": "dropship", "title": "Owned inventory and affiliate: product truth, scripts, drafts", "actor": "dropship", "internal": False},
    {"id": "research", "start": "12:15", "minutes": 45, "lane": "research", "title": "Recursive learning pass, world snapshot, YouTube transcripts", "actor": "research", "internal": True},
    {"id": "clip-check", "start": "13:15", "minutes": 30, "lane": "clipping", "title": "Check paid campaigns; clip only for active paid ones", "actor": "clipper", "internal": False},
    {"id": "swarm", "start": "14:00", "minutes": 120, "lane": "infra", "title": "Swarm window: disjoint packets, one canary first, receipts required", "actor": "swarm", "internal": True},
    {"id": "post-window", "start": "16:15", "minutes": 45, "lane": "dropship", "title": "Post window: approved items only, rules engine checked per account", "actor": "content", "internal": False},
    {"id": "infra-health", "start": "17:30", "minutes": 30, "lane": "infra", "title": "Health, backups, knowledge sync, swap sweep, failure mining", "actor": "infra", "internal": True},
    {"id": "owner-review-pm", "start": "20:00", "minutes": 15, "lane": "review", "title": "Evening approvals and tomorrow's priorities", "actor": "marvin", "internal": False},
    {"id": "training", "start": "22:00", "minutes": 180, "lane": "training", "title": "Fine-tune window (GPU free only; CPU-only if gaming)", "actor": "coder", "internal": True, "gpu": True},
    {"id": "quiet", "start": "01:00", "minutes": 300, "lane": "infra", "title": "Quiet hours: indexing, benchmarks, no posting, no messages", "actor": "infra", "internal": True},
]


def _m(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


class Schedule:
    def __init__(self, app=None, path=None, clock=None):
        self.app = app
        self.path = path or (paths.DATA / "schedule.json")
        self.clock = clock or time.time
        self.state = self._load()

    def _load(self):
        st = {"blocks": [dict(b) for b in DEFAULT_BLOCKS], "paused_lanes": [], "weights": {}, "gaming": False, "done": {}, "notes": []}
        try:
            if self.path != ":memory:" and self.path.exists():
                st.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError):
            pass
        return st

    def _save(self):
        if self.path == ":memory:":
            return
        paths.ensure_data()
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ owner adjustments, any time
    def block(self, bid):
        return next((b for b in self.state["blocks"] if b["id"] == bid), None)

    def move(self, bid, start=None, minutes=None):
        b = self.block(bid)
        if b is None:
            raise KeyError(bid)
        if start:
            _m(start)
            b["start"] = start
        if minutes:
            b["minutes"] = int(minutes)
        self._note("moved %s -> %s %s" % (bid, b["start"], b["minutes"]))
        self._save()
        return b

    def add(self, bid, start, minutes, lane, title, actor="marvin", internal=False, gpu=False):
        if lane not in LANES:
            raise ValueError("lane must be one of " + ", ".join(LANES))
        if self.block(bid):
            raise ValueError("block exists")
        b = {"id": bid, "start": start, "minutes": int(minutes), "lane": lane, "title": title, "actor": actor, "internal": internal, "gpu": gpu}
        _m(start)
        self.state["blocks"].append(b)
        self._note("added " + bid)
        self._save()
        return b

    def remove(self, bid):
        self.state["blocks"] = [b for b in self.state["blocks"] if b["id"] != bid]
        self._note("removed " + bid)
        self._save()

    def pause_lane(self, lane, on=True):
        p = set(self.state["paused_lanes"])
        (p.add if on else p.discard)(lane)
        self.state["paused_lanes"] = sorted(p)
        self._note(("paused " if on else "resumed ") + lane)
        self._save()

    def set_weight(self, lane, weight):
        self.state["weights"][lane] = float(weight)
        self._note("weight %s=%s" % (lane, weight))
        self._save()

    def set_gaming(self, on):
        self.state["gaming"] = bool(on)
        self._save()

    def _note(self, text):
        self.state["notes"] = (self.state["notes"] + ["%s %s" % (time.strftime("%m-%d %H:%M"), text)])[-30:]

    # ------------------------------------------------------------------ what is due and what goes in each block
    def weight(self, lane):
        return self.state["weights"].get(lane, LANES[lane]["weight"])

    def lane_tasks(self, per_lane=3):
        """Open canonical tasks mapped to lanes by keyword; in-progress first, newest first."""
        out = {k: [] for k in LANES}
        if self.app is None:
            return out
        try:
            from nexen.features.connectors.nexen import REGISTRY
            rows = REGISTRY["nexen"].tasks(limit=500)
        except Exception:
            return out
        rows = [r for r in rows if r.get("status") != "done"]
        rows.sort(key=lambda r: (r.get("status") != "in_progress", -(r.get("id") or 0)))
        for r in rows:
            text = str(r.get("text", ""))
            for lane, cfg in LANES.items():
                if re.search(r"\b(?:%s)\b" % cfg["kw"], text, re.I) and len(out[lane]) < per_lane:  # whole words only: 'rent' must not match 'current'
                    out[lane].append({"id": r["id"], "status": r["status"], "text": text[:110].replace("\n", " ")})
                    break
        return out

    def due(self, now=None):
        t = now or self.clock()
        lt = time.localtime(t)
        minute = lt.tm_hour * 60 + lt.tm_min
        day = time.strftime("%Y-%m-%d", lt)
        out = []
        for b in self.state["blocks"]:
            if b["lane"] in self.state["paused_lanes"]:
                continue
            s = _m(b["start"])
            end = s + b["minutes"]
            inside = (s <= minute < end) if end <= 1440 else (minute >= s or minute < end - 1440)
            if inside and self.state["done"].get(b["id"]) != day:
                out.append({**b, "blocked_by": self._blocked(b)})
        return out

    def _blocked(self, b):
        why = []
        if gate.stop_active():
            why.append("global STOP: internal blocks wait; owner-facing prep is still produced")
        if b.get("gpu") and self.state["gaming"]:
            why.append("gaming mode: GPU block runs CPU-only or waits")
        return why

    def mark_done(self, bid):
        self.state["done"][bid] = time.strftime("%Y-%m-%d", time.localtime(self.clock()))
        self._save()

    def plan(self):
        tasks = self.lane_tasks()
        rows = []
        for b in sorted(self.state["blocks"], key=lambda b: _m(b["start"])):
            lane = b["lane"]
            rows.append({**b, "end": "%02d:%02d" % (((_m(b["start"]) + b["minutes"]) // 60) % 24, (_m(b["start"]) + b["minutes"]) % 60),
                         "priority": self.weight(lane), "paused": lane in self.state["paused_lanes"], "tasks": tasks.get(lane, []),
                         "external": LANES[lane]["external"], "blocked_by": self._blocked(b)})
        return {"blocks": rows, "paused_lanes": self.state["paused_lanes"], "gaming": self.state["gaming"], "stop": gate.stop_active(),
                "priority_order": sorted(LANES, key=lambda k: -self.weight(k)), "conflicts": self.conflicts(), "notes": self.state["notes"][-8:]}

    def conflicts(self):
        bl = sorted(self.state["blocks"], key=lambda b: _m(b["start"]))
        out = []
        for i, a in enumerate(bl):
            for b in bl[i + 1:]:
                sa, ea, sb, eb = _m(a["start"]), _m(a["start"]) + a["minutes"], _m(b["start"]), _m(b["start"]) + b["minutes"]
                if sb < ea and sa < eb and a["lane"] not in {"review"} and b["lane"] not in {"review"} and not (a.get("internal") and b.get("internal")):
                    out.append("%s overlaps %s" % (a["id"], b["id"]))
        for b in bl:
            if b["lane"] in {"dropship", "youtube", "persona"} and "post" in b["id"]:
                s = _m(b["start"])
                if s >= 23 * 60 or s < 6 * 60:
                    out.append("%s posts inside quiet hours" % b["id"])
        return out

    def render_markdown(self):
        p = self.plan()
        lines = ["# NEXEN daily routine (generated %s)" % time.strftime("%Y-%m-%d %H:%M"), "", "Priority: " + " > ".join(p["priority_order"]), ""]
        for b in p["blocks"]:
            lines.append("- **%s-%s** [%s%s] %s" % (b["start"], b["end"], b["lane"], ", paused" if b["paused"] else "", b["title"]))
            for t in b["tasks"]:
                lines.append("    - #%s (%s) %s" % (t["id"], t["status"], t["text"]))
        if p["conflicts"]:
            lines += ["", "Conflicts: " + "; ".join(p["conflicts"])]
        return "\n".join(lines)
