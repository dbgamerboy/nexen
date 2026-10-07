"""NEXEN Universal Multi-Bot Synchronization & Communication CLI.

Unifies communication, state dispatching, and skill access across:
- NEXEN V3 (Control plane, tasks, state)
- MARVIN (AI operator, bus, heartbeats)
- HERMES (Agent gateway, live sessions)
- OTHER BOTS (Codex, Claude Code, Subagents)
- ARSENAL & CLI-ANYTHING (3,805 skills & 255 repos)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Core Paths
NEXEN_ROOT = Path(r"H:\NEXEN")
MARVIN_BUS = NEXEN_ROOT / "marvin" / "bus"
STATE_DIR = NEXEN_ROOT / "state"
LOG_DIR = NEXEN_ROOT / "logs" / "bot_sync"
LOG_DIR.mkdir(parents=True, exist_ok=True)

SKILLS_INDEX_PATH = NEXEN_ROOT / "arsenal" / "SKILLS-INDEX.json"
ARSENAL_REPOS_DIR = NEXEN_ROOT / "arsenal" / "repos"
CLI_ANYTHING_DIR = ARSENAL_REPOS_DIR / "HKUDS__CLI-Anything"

CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"
CODEX_SKILLS_DIR = Path.home() / ".codex" / "skills"
HERMES_DIR = Path.home() / "AppData" / "Local" / "hermes"

# Logging setup
LOG_FILE = LOG_DIR / "bot_sync.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.bot_sync")

# Forbidden unverified hype patterns
FORBIDDEN_HYPE_PATTERNS = [
    re.compile(r"(?i)\bguaranteed\s+(?:income|money|return|sales|profit)\b"),
    re.compile(r"(?i)\bpay[\s-]to[\s-]join\b"),
    re.compile(r"(?i)\bget[\s-]rich[\s-]quick\b"),
    re.compile(r"(?i)\bpassive\s+millions\b"),
]


def check_hype_filter(message: str) -> Optional[str]:
    for pat in FORBIDDEN_HYPE_PATTERNS:
        match = pat.search(message)
        if match:
            return f"Blocked claim pattern: '{match.group(0)}' (Policy forbids unverified revenue/pay-to-join hype)."
    return None


class NexenBotSync:
    """Core synchronization and messaging engine."""

    def __init__(self) -> None:
        MARVIN_BUS.mkdir(parents=True, exist_ok=True)

    def get_status(self) -> Dict[str, Any]:
        """Gathers unified status across NEXEN V3, MARVIN, HERMES, and Ollama."""
        status: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {},
            "marvin": {},
            "hermes": {},
            "models_loaded": [],
        }

        # 1. Check MARVIN Heartbeat
        hb_file = MARVIN_BUS / "marvin-heartbeat.json"
        if hb_file.exists():
            try:
                status["marvin"] = json.loads(hb_file.read_text(encoding="utf-8"))
            except Exception:
                status["marvin"] = {"status": "unreadable"}
        else:
            status["marvin"] = {"status": "missing_heartbeat"}

        # 2. Check NEXEN State
        st_file = MARVIN_BUS / "nexen-state.json"
        if st_file.exists():
            try:
                st_data = json.loads(st_file.read_text(encoding="utf-8"))
                status["services"] = st_data.get("services", [])
                status["money_lanes"] = st_data.get("money", {}).get("lanes", [])
            except Exception:
                status["services"] = {"status": "unreadable"}

        # 3. Check Hermes Live State
        hermes_live = MARVIN_BUS / "hermes-live.json"
        if hermes_live.exists():
            try:
                h_data = json.loads(hermes_live.read_text(encoding="utf-8"))
                status["hermes"] = {
                    "connected": h_data.get("connected", False),
                    "model": h_data.get("model", "unknown"),
                    "session_id": h_data.get("session_id", "unknown"),
                    "last_activity": h_data.get("at", "unknown"),
                }
            except Exception:
                status["hermes"] = {"status": "unreadable"}

        # 4. Check Ollama Loaded Models
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/ps", headers={"User-Agent": "NexenSync"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                status["models_loaded"] = [
                    {
                        "name": m.get("name"),
                        "size_mb": round(m.get("size", 0) / (1024 * 1024), 1),
                        "processor": m.get("processor", "unknown"),
                    }
                    for m in data.get("models", [])
                ]
        except Exception:
            status["models_loaded"] = "offline_or_unreachable"

        return status

    def dispatch_message(self, recipient: str, message: str, sender: str = "operator") -> Dict[str, Any]:
        """Dispatches an inter-bot message/task with safety gating and receipt generation."""
        # Policy Check
        filter_err = check_hype_filter(message)
        if filter_err:
            log.error("MESSAGE REJECTED: %s", filter_err)
            return {"status": "rejected", "reason": filter_err}

        msg_id = f"msg_{int(time.time()*1000)}"
        entry = {
            "id": msg_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": sender,
            "to": recipient,
            "content": message,
            "status": "dispatched",
        }

        # 1. Write to MARVIN Actions / Bus
        actions_file = MARVIN_BUS / "actions.json"
        actions = []
        if actions_file.exists():
            try:
                actions = json.loads(actions_file.read_text(encoding="utf-8"))
                if not isinstance(actions, list):
                    actions = [actions]
            except Exception:
                actions = []

        actions.append(entry)
        actions_file.write_text(json.dumps(actions, indent=2), encoding="utf-8")

        # 2. Append to Events JSONL
        events_file = MARVIN_BUS / "events.jsonl"
        with open(events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # 3. Log to Bot Sync Messages
        sync_log = LOG_DIR / "MESSAGES.jsonl"
        with open(sync_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        log.info("Message %s dispatched: %s -> %s", msg_id, sender, recipient)
        return {"status": "dispatched", "message_id": msg_id, "entry": entry}

    def list_models(self) -> Dict[str, Any]:
        """Lists all installed Ollama models and currently resident GPU models."""
        result: Dict[str, Any] = {"installed": [], "running_in_gpu": []}
        try:
            # Tags
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "NexenSync"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                result["installed"] = [
                    {
                        "name": m.get("name"),
                        "size_gb": round(m.get("size", 0) / (1024**3), 2),
                        "modified": m.get("modified_at"),
                    }
                    for m in data.get("models", [])
                ]
            # Running
            req2 = urllib.request.Request("http://127.0.0.1:11434/api/ps", headers={"User-Agent": "NexenSync"})
            with urllib.request.urlopen(req2, timeout=3) as resp2:
                data2 = json.loads(resp2.read().decode())
                result["running_in_gpu"] = data2.get("models", [])
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_qc_receipts(self) -> Dict[str, Any]:
        """Collects verified music renders and content QC review receipts."""
        qc_data: Dict[str, Any] = {
            "audio_masters": [],
            "content_review": {},
            "publishing_latest": {},
        }

        # Audio masters
        masters_dir = NEXEN_ROOT / "music" / "factory" / "masters"
        if masters_dir.exists():
            for f in masters_dir.glob("*.wav"):
                qc_data["audio_masters"].append({
                    "file": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
                })

        # Content review scorecard
        scorecard = NEXEN_ROOT / "reports" / "marvin-content-quality-20260930" / "chatgpt-review-v2.json"
        if scorecard.exists():
            try:
                qc_data["content_review"] = json.loads(scorecard.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Publishing latest
        pub_latest = NEXEN_ROOT / "publishing" / "state" / "LATEST.json"
        if pub_latest.exists():
            try:
                qc_data["publishing_latest"] = json.loads(pub_latest.read_text(encoding="utf-8"))
            except Exception:
                pass

        return qc_data

    def search_skills(self, query: str) -> List[Dict[str, Any]]:
        """Searches across all 3,805 indexed skills in Arsenal."""
        if not SKILLS_INDEX_PATH.exists():
            log.error("Skills index not found at %s", SKILLS_INDEX_PATH)
            return []

        try:
            with open(SKILLS_INDEX_PATH, "r", encoding="utf-8") as f:
                skills: List[Dict[str, Any]] = json.load(f)
        except Exception as e:
            log.error("Failed to load skills index: %s", e)
            return []

        q = query.lower().strip()
        tokens = [t for t in re.split(r"\s+", q) if len(t) >= 2]
        matches = []
        for s in skills:
            hay = f"{s.get('name', '')} {s.get('description', '')} {s.get('repo', '')}".lower()
            if q in hay or (tokens and all(tok in hay for tok in tokens)):
                matches.append(s)
            elif tokens and any(tok in hay for tok in tokens) and len(tokens) > 1:
                matches.append(s)

        return matches

    def search_repos(self, query: str) -> List[Dict[str, Any]]:
        """Searches across all 255 cloned repositories in Arsenal."""
        if not ARSENAL_REPOS_DIR.exists():
            return []

        q = query.lower()
        matches = []
        for d in ARSENAL_REPOS_DIR.iterdir():
            if d.is_dir() and q in d.name.lower():
                card_file = d / "_nexen" / "CARD.md"
                desc = ""
                if card_file.exists():
                    try:
                        desc = card_file.read_text(encoding="utf-8").split("\n")[2]
                    except Exception:
                        pass
                matches.append({"name": d.name, "path": str(d), "description": desc})

        return matches

    def install_skill_on_demand(self, skill_name: str) -> Dict[str, Any]:
        """Installs/copies an Arsenal skill into Claude Code and Codex skill directories."""
        matches = self.search_skills(skill_name)
        exact = [s for s in matches if s.get("name", "").lower() == skill_name.lower()]
        target_skill = exact[0] if exact else (matches[0] if matches else None)

        if not target_skill:
            return {"status": "error", "message": f"Skill '{skill_name}' not found in Arsenal."}

        src_path = Path(target_skill["path"])
        if not src_path.exists():
            return {"status": "error", "message": f"Skill path does not exist on disk: {src_path}"}

        sanitized_name = re.sub(r"[^\w.-]+", "-", target_skill["name"]).strip("-")
        installed_to = []

        # 1. Copy to Claude Code
        CLAUDE_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        claude_target = CLAUDE_SKILLS_DIR / sanitized_name
        if not claude_target.exists():
            shutil.copytree(src_path, claude_target)
            installed_to.append(str(claude_target))

        # 2. Copy to Codex
        CODEX_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        codex_target = CODEX_SKILLS_DIR / sanitized_name
        if not codex_target.exists():
            shutil.copytree(src_path, codex_target)
            installed_to.append(str(codex_target))

        log.info("Skill '%s' installed to: %s", sanitized_name, installed_to)
        return {
            "status": "installed",
            "skill": target_skill["name"],
            "repo": target_skill["repo"],
            "installed_to": installed_to,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXEN Universal Multi-Bot Synchronization CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Status
    subparsers.add_parser("status", help="Get unified status of all bots and services")

    # Message
    msg_parser = subparsers.add_parser("send", help="Send a message/task to another bot")
    msg_parser.add_argument("to", choices=["marvin", "hermes", "codex", "claude", "all"], help="Recipient bot")
    msg_parser.add_argument("message", help="Instruction or payload text")
    msg_parser.add_argument("--from-agent", default="operator", help="Sender identifier")

    # Models
    subparsers.add_parser("models", help="List installed and running Ollama models")

    # QC
    subparsers.add_parser("qc", help="Show audio and content QC receipts")

    # Skills Search
    skills_parser = subparsers.add_parser("skills", help="Search the 3,805 Arsenal skills")
    skills_parser.add_argument("query", help="Keyword to search")

    # Repos Search
    repos_parser = subparsers.add_parser("repos", help="Search the 255 Arsenal repos")
    repos_parser.add_argument("query", help="Keyword to search")

    # Install Skill
    install_parser = subparsers.add_parser("install-skill", help="Hot-install an Arsenal skill into Claude and Codex")
    install_parser.add_argument("name", help="Name of skill to install")

    # Hardware Brain Tier
    subparsers.add_parser("tier", help="Query live hardware telemetry and active model tier")

    args = parser.parse_args()
    sync = NexenBotSync()

    if args.command == "status":
        print(json.dumps(sync.get_status(), indent=2))

    elif args.command == "tier":
        sys.path.insert(0, r"H:\NEXEN\tools")
        from adaptive_brain_tier import AdaptiveBrainTier
        print(json.dumps(AdaptiveBrainTier().select_optimal_brain(), indent=2))

    elif args.command == "send":
        res = sync.dispatch_message(args.to, args.message, sender=args.from_agent)
        print(json.dumps(res, indent=2))

    elif args.command == "models":
        res = sync.list_models()
        print(json.dumps(res, indent=2))

    elif args.command == "qc":
        res = sync.get_qc_receipts()
        print(json.dumps(res, indent=2))

    elif args.command == "skills":
        matches = sync.search_skills(args.query)
        print(f"Found {len(matches)} matching skills for '{args.query}':")
        for m in matches[:15]:
            print(f"- {m['name']} (from {m['repo']}): {m.get('description', '')[:90]}")
        if len(matches) > 15:
            print(f"... and {len(matches) - 15} more.")

    elif args.command == "repos":
        matches = sync.search_repos(args.query)
        print(f"Found {len(matches)} matching repos for '{args.query}':")
        for m in matches[:15]:
            print(f"- {m['name']}: {m.get('description', '')}")

    elif args.command == "install-skill":
        res = sync.install_skill_on_demand(args.name)
        print(json.dumps(res, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
