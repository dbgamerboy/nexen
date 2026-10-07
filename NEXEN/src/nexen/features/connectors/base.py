"""Shared helpers for connectors: read-only sqlite, bounded jsonl streaming, redaction."""
import json
import os
import re
import sqlite3
import time
from collections import deque
from contextlib import closing
from pathlib import Path

_SECRET = [
    re.compile(r"(?i)\b(sk|pk|rk|ghp|gho|xox[abp]|AKIA)[-_][A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*)\S{4,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{24}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}\b"),  # discord token shape
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # jwt
]
_LAN = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")


def redact(text):
    """Strip credential shapes and PC2 LAN addresses before text is stored or shown in a pack."""
    if not isinstance(text, str):
        return ""
    for rx in _SECRET:
        text = rx.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return _LAN.sub("[LAN-ADDR]", text)


def snippet(text, query, width=220):
    text = text or ""
    if not query:
        return text[:width]
    i = text.lower().find(query.lower())
    if i < 0:
        return text[:width]
    a = max(0, i - width // 3)
    return ("..." if a else "") + text[a:a + width].replace("\n", " ")


def ro_connect(path, timeout=3):
    p = str(path).replace("\\", "/")
    con = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=timeout)
    con.row_factory = sqlite3.Row
    return con


def ro_query(path, sql, args=()):
    if not Path(path).is_file():
        return []
    try:
        with closing(ro_connect(path)) as con:
            return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.Error:
        return []


def columns(path, table):
    return [r["name"] for r in ro_query(path, "PRAGMA table_info(%s)" % table)]


def stream_jsonl(path, max_bytes=200_000_000):
    """Yield parsed json objects; bad lines are skipped, never fatal."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def tail_jsonl(path, n=20, max_bytes=2_000_000):
    out = deque(maxlen=n)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in data[1:] if size > max_bytes else data:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return list(out)


def iso(ts):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return str(ts or "")


def mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def run_cli(args, timeout=180, stdin=None):
    """Run an external CLI without a shell. Returns (code, stdout, stderr)."""
    import subprocess
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, input=stdin)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "executable not found: %s" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ss" % timeout
