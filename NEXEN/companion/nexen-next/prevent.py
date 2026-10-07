"""Failure prevention data for the NEXEN NEXT tab: live checks from the V4 spine, each joined to its catalog fix.
No tkinter here, so it can be tested alone."""
import os
import sys

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engine")
ORDER = {"bad": 0, "warn": 1, "ok": 2}


def _spine_modules():
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)
    from nexen.spine import indicators, problems
    return indicators, problems


def scan(timeout=10):
    """Rows for every live check, worst first. Each row carries the catalog title, prevention and first fix steps."""
    indicators, problems = _spine_modules()
    catalog = {p["id"]: p for p in problems.CATALOG}
    rows = []
    for c in indicators.live(timeout=timeout):
        p = catalog.get(c.get("problem")) or {}
        rows.append({"check": c["id"], "state": c["state"], "detail": c["detail"], "problem": c.get("problem"),
                     "title": p.get("title", ""), "prevent": p.get("prevent", []),
                     "steps": (p.get("playbooks") or [{}])[0].get("steps", [])})
    return sorted(rows, key=lambda r: ORDER.get(r["state"], 1))


def agent_prompt(row):
    """A ready prompt for Claude, Codex or Antigravity to fix one failing check."""
    steps = "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(row["steps"]))
    return ("Fix this NEXEN failure. Check: %s. Problem class: %s (%s). Evidence: %s\nSteps from the intellect spine:\n%s\n"
            "Test on the real input, read the output, then log it in SESSION-LOG. No passwords or tokens in files." %
            (row["check"], row["problem"], row["title"], row["detail"], steps))
