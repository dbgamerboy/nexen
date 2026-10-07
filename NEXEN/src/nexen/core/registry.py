"""Module registry: every NEXEN piece with a health probe and its buttons.

Sources: a static core list, Business Operations inventory and workflow sections, the MARVIN action
catalog, and a metadata-only census of the older NEXEN lines on F:. Hot-loaded modules (modules/*.json)
add entries without a rebuild. Launching is limited to an allowlist of trusted roots.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from nexen.core import paths
from nexen.features.connectors import base

TRUSTED_ROOTS = [Path(r"F:\NEXEN_MEMORY"), Path(r"H:\NEXEN-ENTERPRISE"), Path(r"H:\NEXEN"), Path(r"H:\NEXEN-VideoStudio"), Path(r"H:\NEXEN_V3")]


def core_modules():
    h = paths.H_NEXEN
    return [
        {"id": "v3-core", "name": "NEXEN V3 core", "line": "V3", "kind": "service", "probe": {"http": paths.V3_CORE_URL + "/healthz"},
         "notes": "Frozen line. V4 reads it through adapters and never writes its files.",
         "buttons": [{"id": "open", "label": "Open V3 hub", "kind": "url", "target": paths.V3_CORE_URL + "/"},
                     {"id": "tasks", "label": "V3 task room", "kind": "url", "target": paths.V3_CORE_URL + "/tasks"}]},
        {"id": "marvin", "name": "MARVIN (Discord + HUD)", "line": "V3", "kind": "service", "probe": {"path": str(h / "marvin" / "bus" / "events.jsonl")},
         "buttons": [{"id": "hud", "label": "MARVIN HUD", "kind": "url", "target": paths.V3_CORE_URL + "/marvin"},
                     {"id": "training", "label": "MARVIN training page (V3)", "kind": "url", "target": paths.V3_CORE_URL + "/marvin/training"},
                     {"id": "talk-log", "label": "Talk log", "kind": "view", "target": "marvin:talk"}]},
        {"id": "ollama", "name": "Ollama", "line": "shared", "kind": "service", "probe": {"http": paths.OLLAMA_URL + "/api/version", "timeout": 8},
         "notes": "Loaded machines answer slowly; MARVIN's brain times out its model lookup at 5 s.", "buttons": []},
        {"id": "n8n", "name": "n8n (local 5678)", "line": "shared", "kind": "service", "probe": {"http": paths.N8N_URL + "/healthz"},
         "buttons": [{"id": "open", "label": "n8n editor", "kind": "url", "target": paths.N8N_URL}]},
        {"id": "n8n-staging", "name": "n8n (staging 5680)", "line": "shared", "kind": "service", "probe": {"http": "http://127.0.0.1:5680/healthz"},
         "buttons": [{"id": "open", "label": "n8n staging editor", "kind": "url", "target": "http://127.0.0.1:5680"}]},
        {"id": "pair", "name": "PAIR router (PC2 route)", "line": "shared", "kind": "service", "probe": {"http": "http://127.0.0.1:11435/api/version", "timeout": 8}, "buttons": []},
        {"id": "obsidian", "name": "Obsidian vault", "line": "shared", "kind": "data", "probe": {"vault": True},
         "buttons": [{"id": "log", "label": "Session log tail", "kind": "view", "target": "vault:log"}]},
        {"id": "codex", "name": "Codex (Astra)", "line": "tool", "kind": "agent", "probe": {"path": str(Path(os.environ.get("USERPROFILE", "")) / ".codex" / "session_index.jsonl")}, "buttons": []},
        {"id": "antigravity", "name": "Antigravity", "line": "tool", "kind": "agent", "probe": {"cli": "agy"}, "buttons": []},
        {"id": "hermes", "name": "Hermes", "line": "tool", "kind": "agent", "probe": {"cli": "hermes"}, "buttons": []},
        {"id": "claude", "name": "Claude Code", "line": "tool", "kind": "agent", "probe": {"cli": "claude"}, "buttons": []},
        {"id": "chatgpt", "name": "ChatGPT (manual bridge)", "line": "tool", "kind": "agent", "probe": {"always": True},
         "notes": "No API. Packets go to the outbox; replies come back as saved scorecards.", "buttons": []},
        {"id": "bizops", "name": "NEXEN Business Operations", "line": "V4", "kind": "app", "probe": {"path": str(paths.BIZ_OPS / "app" / "clipper_app.pyw")},
         "buttons": [{"id": "launch", "label": "Open Business Operations", "kind": "script",
                      "target": str(paths.BIZ_OPS / "START-BUSINESS-OPERATIONS.ps1")}]},
        {"id": "review", "name": "Source Review workspace", "line": "V4", "kind": "app", "probe": {"path": str(paths.BIZ_OPS / "START-REVIEW-WORKSPACE.ps1")},
         "buttons": [{"id": "launch", "label": "Open Source Review", "kind": "script",
                      "target": str(paths.BIZ_OPS / "START-REVIEW-WORKSPACE.ps1")}]},
        {"id": "ocr", "name": "Local GPU OCR (RTX 2070)", "line": "V4", "kind": "service", "probe": {"path": str(paths.HOME / "Services" / "LocalOCR")}, "buttons": []},
        {"id": "learning", "name": "V4 Novel + Recursive Learning", "line": "V4", "kind": "engine", "probe": {"path": str(paths.LEARNING_DB)},
         "buttons": [{"id": "gaps", "label": "Curiosity gaps", "kind": "view", "target": "learning:gaps"},
                     {"id": "archive", "label": "Quality-diversity archive", "kind": "view", "target": "learning:archive"}]},
    ]


def bizops_buttons():
    """Buttons that mirror NEXEN Business Operations. Each reads the existing files; none publishes."""
    out = []
    prod = paths.BIZ_OPS / "products"
    if prod.is_dir():
        for p in sorted(prod.glob("*.json")):
            out.append({"id": "product-" + p.stem, "label": "Product: " + p.stem.replace("-", " "), "kind": "view", "target": "file:" + str(p), "group": "Products"})
    for label, grp in (("Content Review", "Home"), ("A/B Testing", "Tabs"), ("Competitor Study", "Tabs"), ("Affiliate Studio", "Tabs")):
        out.append({"id": "bo-" + label.lower().replace(" ", "-").replace("/", ""), "label": label + " (opens Business Operations)",
                    "kind": "script", "target": str(paths.BIZ_OPS / "START-BUSINESS-OPERATIONS.ps1"), "group": grp})
    ws = paths.BIZ_OPS / "app" / "workflow_sections.json"
    try:
        for s in json.loads(ws.read_text(encoding="utf-8-sig")).get("sections", []):
            out.append({"id": "wf-" + s["name"].lower()[:30].replace(" ", "-"), "label": "Workflows: " + s["name"], "kind": "view",
                        "target": "workflows:" + s["name"], "group": "Workflow sections"})
    except (OSError, ValueError):
        pass
    inv = paths.BIZ_INVENTORY / "PROGRAM-INVENTORY.json"
    if inv.is_file():
        out.append({"id": "button-box", "label": "Button Box: all recovered software (KEEP / REVIEW / ARCHIVE)", "kind": "view",
                    "target": "bizops:inventory", "group": "Button Box"})
    return out


def marvin_buttons():
    """Action buttons from the app's own catalog (config/actions.json). Executed by actions.py."""
    from nexen.features.operations import actions
    return [{"id": "action-" + a["id"], "label": a["label"], "kind": "marvin-action", "target": a["id"], "risk": a.get("risk", "confirm"),
             "lane": a.get("lane"), "help": a.get("help", ""), "inputs": actions.public(a)["inputs"],
             "group": "Actions: " + str(a.get("lane", "other"))} for a in actions.catalog()]


def f_census(max_dirs=15):
    rows = []
    for d in paths.F_LEGACY[:max_dirs]:
        p = Path(d)
        try:
            exists = p.exists()
            rows.append({"path": d, "exists": exists, "modified": base.iso(p.stat().st_mtime) if exists else None})
        except OSError as e:
            rows.append({"path": d, "exists": None, "error": type(e).__name__})
    return rows


def hot_modules():
    out = []
    if paths.MODULES.is_dir():
        for p in sorted(paths.MODULES.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            for m in (data if isinstance(data, list) else [data]):
                if isinstance(m, dict) and m.get("id") and m.get("name"):
                    m.setdefault("line", "V4")
                    m.setdefault("kind", "hot")
                    m.setdefault("buttons", [])
                    m["hot_file"] = p.name
                    out.append(m)
    return out


def probe(m, timeout=2.0):
    spec = m.get("probe") or {}
    try:
        if "http" in spec:
            with urllib.request.urlopen(spec["http"], timeout=spec.get("timeout", timeout)) as r:
                return {"state": "up" if r.status < 500 else "degraded", "detail": "HTTP %d" % r.status}
        if "path" in spec:
            exists = Path(spec["path"]).exists()
            return {"state": "present" if exists else "missing", "detail": spec["path"]}
        if "cli" in spec:
            exe = shutil.which(spec["cli"])
            return {"state": "present" if exe else "missing", "detail": exe or "not on PATH"}
        if spec.get("vault"):
            v = paths.vault()
            return {"state": "present" if v else "missing", "detail": str(v) if v else "no vault found"}
        if spec.get("always"):
            return {"state": "manual", "detail": "no automated probe"}
    except Exception as e:  # a failing probe is a state, never a crash
        return {"state": "down", "detail": "%s" % type(e).__name__}
    return {"state": "unknown", "detail": "no probe"}


def all_modules(with_probe=True):
    mods = core_modules() + hot_modules()
    if with_probe:
        threads, results = [], {}

        def run(m):
            results[m["id"]] = probe(m)
        for m in mods:
            t = threading.Thread(target=run, args=(m,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(10)
        for m in mods:
            m["health"] = results.get(m["id"], {"state": "unknown", "detail": "probe timed out"})
    return mods


def is_trusted(path):
    try:
        rp = Path(path).resolve()
    except OSError:
        return False
    return any(root.resolve() == rp or root.resolve() in rp.parents for root in TRUSTED_ROOTS if root.exists())


def launch(kind, target):
    """Start a trusted local thing. No shell, no arguments from the caller."""
    if kind == "url":
        u = urlparse(target)
        if u.scheme in {"http", "https"} and u.hostname in {"127.0.0.1", "localhost"}:
            os.startfile(target)  # opens in the default browser
            return {"ok": True}
        return {"ok": False, "error": "only local urls open from buttons"}
    if kind == "script":
        if not is_trusted(target) or not str(target).lower().endswith((".ps1", ".cmd", ".bat", ".exe", ".pyw")):
            return {"ok": False, "error": "script is outside trusted roots"}
        if str(target).lower().endswith(".ps1"):
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target)],
                             cwd=str(Path(target).parent), creationflags=0x08000000)
        else:
            os.startfile(str(target))
        return {"ok": True}
    if kind == "file":
        if is_trusted(target) and str(target).lower().endswith((".pdf", ".md", ".txt", ".html", ".json", ".csv", ".png", ".mp4")):
            os.startfile(str(target))
            return {"ok": True}
        return {"ok": False, "error": "file is outside trusted roots or not a document type"}
    if kind == "folder":
        if is_trusted(target):
            os.startfile(str(target))
            return {"ok": True}
        return {"ok": False, "error": "folder is outside trusted roots"}
    return {"ok": False, "error": "unknown launch kind"}
