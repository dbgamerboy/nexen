"""Obvious-flaw scanner: cheap static rules over Python source, each mapped to a problem class.

It finds the defects that have actually bitten NEXEN (swallowed exceptions, shell=True, network calls without a
timeout, string-built SQL, hard-coded secrets). Read-only; reports file:line so a fix packet can be exact.
"""
import os
import re
from pathlib import Path

RULES = [
    ("swallowed-exception", "COD-005", 4, re.compile(r"^\s*except(\s+\w[\w\.]*)?(\s+as\s+\w+)?:\s*$"), "next-line-pass"),
    ("bare-except-pass", "COD-005", 4, re.compile(r"except(\s+Exception)?\s*:\s*pass\b"), None),
    ("shell-true", "COD-012", 5, re.compile(r"shell\s*=\s*True"), None),
    ("eval-exec", "COD-012", 5, re.compile(r"(?<![\w\.])(eval|exec)\("), None),
    ("os-system", "COD-012", 4, re.compile(r"os\.system\("), None),
    ("string-built-sql", "COD-012", 5, re.compile(r"execute\(\s*(f[\"']|[\"'][^\"']*[\"']\s*(%|\+|\.format))"), None),
    ("hardcoded-secret", "COD-012", 5, re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token)\s*=\s*[\"'][A-Za-z0-9_\-\.]{12,}[\"']"), None),
    ("network-no-timeout", "COD-013", 3, re.compile(r"(urlopen|requests\.(get|post|put|delete)|httpx\.(get|post))\("), "no-timeout"),
    ("unbounded-loop", "COD-006", 3, re.compile(r"^\s*while\s+True\s*:"), "no-break-or-wait"),
    ("text-mode-hash-write", "ENV-007", 2, re.compile(r"write_text\(.*\)\s*$"), "near-sha"),
]
SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".git", "site-packages", "library", "arsenal", "repos", "tests"}


def scan_file(path, max_findings=60):
    out = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for name, pid, sev, rx, extra in RULES:
            if not rx.search(line):
                continue
            window = "\n".join(lines[i:i + 6])
            if extra == "next-line-pass" and not re.match(r"\s*pass\b", lines[i + 1] if i + 1 < len(lines) else ""):
                continue
            if extra == "no-timeout" and "timeout" in window:
                continue
            if extra == "no-break-or-wait" and re.search(r"break|sleep|wait|return|\.get\(", "\n".join(lines[i:i + 25])):
                continue
            if extra == "near-sha" and not re.search(r"sha|hash|digest", "\n".join(lines[max(0, i - 6):i + 6]), re.I):
                continue
            out.append({"file": str(path), "line": i + 1, "rule": name, "problem": pid, "severity": sev, "code": stripped[:140]})
            if len(out) >= max_findings:
                return out
    return out


def scan(roots, max_files=400, max_findings=200):
    findings, files = [], 0
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for n in names:
                if n.endswith((".py", ".pyw")) and not n.startswith("test_"):
                    files += 1
                    findings += scan_file(Path(dirpath) / n)
                    if files >= max_files or len(findings) >= max_findings:
                        return _summary(findings, files)
    return _summary(findings, files)


def _summary(findings, files):
    by_rule = {}
    for f in findings:
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
    findings.sort(key=lambda f: (-f["severity"], f["file"], f["line"]))
    return {"files_scanned": files, "findings": len(findings), "by_rule": by_rule, "top": findings[:25]}
