from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(r"H:\NEXEN\v1\app\data\nexen.db")
DEFAULT_SESSION_LOG = Path(r"F:\NEXEN_MEMORY\00-Control\SESSION-LOG.md")
DEFAULT_WORKTREE = Path(r"H:\NEXEN\worktrees\v3-project-integration-20260926")
DEFAULT_PC2_ROOT = Path(r"H:\NEXEN\pc2")
DEFAULT_DESKTOP = Path.home() / "Desktop" / "MARVIN" / "Reports"
DEFAULT_H_REPORTS = Path(r"H:\NEXEN\reports\coding-sessions")
STOP_FILES = (
    Path(r"F:\NEXEN_MEMORY\04-Execution\STOP"),
    Path(r"H:\NEXEN\loop\STOP"),
    Path(r"H:\NEXEN\recovery\coding-loop-20260927\runtime\active-next\STOP"),
)

def _safe_read(path: Path, limit: int = 40000) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""

def _sanitize(text: str) -> str:
    text = re.sub(r"\\\\[A-Za-z0-9_.-]+\\[^\s]+", "[PC2 share redacted]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[network address redacted]", text)
    text = re.sub(r"\bDESKTOP-[A-Za-z0-9-]+\b", "PC2/worker host", text)
    text = re.sub(r"\bsk-[A-Za-z0-9._-]{12,}\b", "[credential redacted]", text)
    text = re.sub(r"(?i)((?:api[_ -]?key|secret|token)\s*[:=]\s*)\S+", r"\1[redacted]", text)
    return text
def _db_snapshot(db_path: Path) -> tuple[list[str], list[str], list[str]]:
    if not db_path.exists():
        return (
            ["IMPLEMENTATION LEASE | UNAVAILABLE: canonical DB missing"],
            ["TASKS | UNAVAILABLE"],
            ["RECENT TASK HISTORY | UNAVAILABLE"],
        )
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        lease = con.execute(
            "SELECT owner,task_id,scope,expires_at FROM coding_implementation_lease WHERE singleton=1"
        ).fetchone()
        now = time.time()
        if lease and lease["expires_at"] > now:
            lease_lines = [
                "IMPLEMENTATION LEASE | ACTIVE",
                f"  task={lease['task_id']} owner={_sanitize(str(lease['owner']))}",
                f"  scope={_sanitize(str(lease['scope']))}",
                f"  expires_in_seconds={max(0, int(lease['expires_at'] - now))}",
                "  COLLISION GUARD: do not start overlapping implementation until this lease releases.",
            ]
        else:
            lease_lines = ["IMPLEMENTATION LEASE | FREE"]
        tasks = con.execute(
            """SELECT id,text,status FROM hub_requests
               WHERE status IN ('in_progress','planned')
               ORDER BY CASE id WHEN 142 THEN 0 WHEN 152 THEN 1 ELSE 2 END, id
               LIMIT 16"""
        ).fetchall()
        task_lines = ["OPEN CANONICAL TASKS"] + [
            f"  #{r['id']} [{r['status']}] {_sanitize(str(r['text']))}" for r in tasks
        ]
        history = con.execute(
            """SELECT id,request_id,new_status,outcome,created_at FROM task_history
               WHERE request_id IN (142,152)
               ORDER BY id DESC LIMIT 10"""
        ).fetchall()
        history_lines = ["RECENT TASK 142/152 HISTORY"] + [
            f"  history#{r['id']} task#{r['request_id']} {r['created_at']} "
            f"{_sanitize(str(r['outcome']))[:420]}" for r in history
        ]
        con.close()
        return lease_lines, task_lines, history_lines
    except (OSError, sqlite3.Error) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        return (
            [f"IMPLEMENTATION LEASE | UNAVAILABLE: {_sanitize(msg)}"],
            ["TASKS | UNAVAILABLE"],
            ["RECENT TASK HISTORY | UNAVAILABLE"],
        )

def _stop_snapshot() -> list[str]:
    active = [p for p in STOP_FILES if p.exists()]
    if not active:
        return ["GLOBAL STOP | no configured STOP marker found"]
    return ["GLOBAL STOP | ACTIVE", *[f"  {p}" for p in active]]
def _git_snapshot(worktree: Path) -> list[str]:
    if not worktree.exists():
        return ["WORKTREE | UNAVAILABLE"]
    git = shutil.which("git")
    if not git:
        for candidate in (
            Path(r"F:\07_SOFTWARE\Git\cmd\git.exe"),
            Path(r"C:\Program Files\Git\cmd\git.exe"),
        ):
            if candidate.exists():
                git = str(candidate)
                break
    if not git:
        return ["WORKTREE | git executable unavailable"]
    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                [git, "-C", str(worktree), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    branch = run("branch", "--show-current") or "(detached/unknown)"
    head = run("rev-parse", "--short", "HEAD") or "unknown"
    status = run("status", "--short")
    changed = [line for line in status.splitlines() if line.strip()]
    lines = [f"WORKTREE | branch={branch} head={head} changed_paths={len(changed)}"]
    lines.extend(f"  {line}" for line in changed[:40])
    if len(changed) > 40:
        lines.append(f"  ... {len(changed) - 40} more paths")
    return lines

def _pc2_snapshot(pc2_root: Path) -> list[str]:
    package = pc2_root / "coding-loop-v1"
    ready = {}
    try:
        if (package / "_READY.json").exists():
            ready = json.loads((package / "_READY.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        ready = {}
    packets = list((package / "packet-bank").glob("*.json")) if (package / "packet-bank").exists() else []
    local_results = list((package / "results").glob("*.json")) if (package / "results").exists() else []
    returned = list((pc2_root / "returned").glob("*.json")) if (pc2_root / "returned").exists() else []
    latest = max(local_results + returned, key=lambda p: p.stat().st_mtime, default=None)
    lines = [
        "PC2 STATUS | local evidence only; connector visibility is not PC2 availability authority",
        f"  staged_packets={len(packets)} local_results={len(local_results)} returned_receipts={len(returned)}",
    ]
    if ready:
        state = ready.get("status") or ready.get("state") or ready.get("ready") or "present"
        lines.append(f"  package_ready={_sanitize(str(state))}")
    if latest:
        lines.append(f"  latest_local_receipt={latest.name} modified={datetime.fromtimestamp(latest.stat().st_mtime).astimezone().isoformat(timespec='seconds')}")
    else:
        lines.append("  latest_local_receipt=none in local H: result folders")
    return lines

def _hourly_snapshot(hourly_dir: Path) -> list[str]:
    candidates = list(hourly_dir.glob("NEXEN-V3-HOURLY-*.*")) if hourly_dir.exists() else []
    if not candidates:
        return ["LATEST NEXEN/MARVIN OPS SNAPSHOT | UNAVAILABLE"]
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    wanted = (
        "TICKET / STATUS", "CURRENT MILESTONE", "DID", "PROOF PASS", "PROOF FAIL",
        "PROGRESS CHANGE", "WORKERS CHECKED", "WORKERS UNAVAILABLE", "BLOCKER",
        "NEEDS ME ONE ACTION OR NONE", "NEXT",
    )
    lines = [f"LATEST NEXEN/MARVIN OPS SNAPSHOT | {latest.name}"]
    for line in _safe_read(latest).splitlines():
        if any(line.startswith(prefix) for prefix in wanted):
            lines.append("  " + _sanitize(line))
    return lines
def _session_log_snapshot(session_log: Path) -> list[str]:
    try:
        lines = session_log.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-36:]
    except OSError:
        return ["SESSION LOG TAIL | UNAVAILABLE"]
    if not lines:
        return ["SESSION LOG TAIL | UNAVAILABLE"]
    return ["SESSION LOG TAIL | last 36 lines", *["  " + _sanitize(x) for x in lines]]

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "session").lower()).strip("-")[:48] or "session"

def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def generate_report(args) -> dict[str, str]:
    now = datetime.now().astimezone()
    lease_lines, task_lines, history_lines = _db_snapshot(Path(args.db))
    desktop = Path(args.desktop_dir)
    hourly_dir = Path(args.hourly_dir) if args.hourly_dir else desktop
    h_root = Path(args.h_report_root)
    report_lines = [
        "NEXEN / MARVIN CODING COLLISION GUARD",
        f"Generated: {now.isoformat(timespec='seconds')}",
        f"Mode: {args.mode}",
        f"Session: agent={_sanitize(args.agent)} topic={_sanitize(args.topic)} title={_sanitize(args.title)}",
        "",
        *lease_lines,
        *(_stop_snapshot()),
        "",
        *task_lines,
        "",
        *history_lines,
        "",
        *(_git_snapshot(Path(args.worktree))),
        "",
        *(_pc2_snapshot(Path(args.pc2_root))),
        "",
        *(_hourly_snapshot(hourly_dir)),
        "",
        *(_session_log_snapshot(Path(args.session_log))),
        "",
        f"SESSION NEXT | {_sanitize(args.next_step) if args.next_step else 'Read this report before starting another implementation packet.'}",
        "",
    ]
    text = "\n".join(report_lines)
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y%m%d-%H%M%S")
    latest = desktop / "NEXEN-CODING-STATUS-LATEST.txt"
    daily = desktop / f"NEXEN-CODING-DAILY-{now.strftime('%Y%m%d')}.txt"
    _write_atomic(latest, text)
    daily.parent.mkdir(parents=True, exist_ok=True)
    with daily.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {stamp} {args.mode} =====\n{text}")
    h_daily = h_root / day / f"{stamp}-{args.mode}-{_slug(args.agent)}-{_slug(args.title)}.txt"
    _write_atomic(h_daily, text)
    archive = ""
    if args.mode == "session":
        archive_path = desktop / "Coding Sessions" / day / f"{stamp}-{_slug(args.agent)}-{_slug(args.title)}.txt"
        _write_atomic(archive_path, text)
        archive = str(archive_path)
    return {"latest": str(latest), "daily": str(daily), "archive": archive, "h_receipt": str(h_daily)}
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Write NEXEN/MARVIN anti-overlap coding status reports.")
    ap.add_argument("--mode", choices=("session", "daily"), default="session")
    ap.add_argument("--agent", default="unknown")
    ap.add_argument("--topic", default="nexen-ops")
    ap.add_argument("--title", default="coding session status")
    ap.add_argument("--next", dest="next_step", default="")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--session-log", default=str(DEFAULT_SESSION_LOG))
    ap.add_argument("--worktree", default=str(DEFAULT_WORKTREE))
    ap.add_argument("--pc2-root", default=str(DEFAULT_PC2_ROOT))
    ap.add_argument("--desktop-dir", default=str(DEFAULT_DESKTOP))
    ap.add_argument("--h-report-root", default=str(DEFAULT_H_REPORTS))
    ap.add_argument("--hourly-dir", default="")
    return ap

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = generate_report(args)
    print("coding_session_report:", json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
