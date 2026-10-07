"""Live update. Drop a package in updates/<version>/ with manifest.json; apply verifies, backs up, copies, tests, rolls back.

Package layout:
  updates/<name>/manifest.json   {"version": "4.0.1", "notes": "...", "files": [{"path": "engine/nexen/x.py", "sha256": "..."}]}
  updates/<name>/<each file at the same relative path>

Only engine/, ui/ and modules/ can be written. modules/*.json adds buttons and modules instantly with no restart.
Engine changes write restart.flag; NEXEN.exe restarts the engine when it sees it.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from nexen import VERSION
from nexen.core import paths

ALLOWED = ("engine", "ui", "modules")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pending():
    root = paths.APP / "updates"
    out = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            m = d / "manifest.json"
            if d.is_dir() and not d.name.startswith("_") and m.is_file() and not (d / "APPLIED").exists():
                try:
                    data = json.loads(m.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    out.append({"name": d.name, "error": "bad manifest"})
                    continue
                out.append({"name": d.name, "version": data.get("version"), "notes": data.get("notes", ""), "files": len(data.get("files", []))})
    return out


def status():
    return {"current": VERSION, "app": str(paths.APP), "pending": pending()}


def verify(name):
    d = paths.APP / "updates" / name
    data = json.loads((d / "manifest.json").read_text(encoding="utf-8-sig"))
    problems = []
    for f in data.get("files", []):
        rel = Path(f["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] not in ALLOWED:
            problems.append("path not allowed: %s" % f["path"])
            continue
        src = d / rel
        if not src.is_file():
            problems.append("missing in package: %s" % f["path"])
        elif _sha(src) != f.get("sha256"):
            problems.append("hash mismatch: %s" % f["path"])
    return data, problems


def apply(name, run_tests=True):
    d = paths.APP / "updates" / name
    data, problems = verify(name)
    if problems:
        return {"ok": False, "stage": "verify", "problems": problems}
    backup = paths.APP / "updates" / "_backup" / ("%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), name))
    touched = []
    try:
        for f in data["files"]:
            dest = paths.APP / f["path"]
            if dest.exists():
                keep = backup / f["path"]
                keep.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, keep)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / f["path"], dest)
            touched.append(f["path"])
        if run_tests and (paths.APP / "tests").is_dir():
            r = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", str(paths.APP / "tests"),
                                "-t", str(paths.APP)], capture_output=True, text=True, timeout=300, cwd=str(paths.APP))
            if r.returncode != 0:
                raise RuntimeError("tests failed after update:\n" + (r.stderr or r.stdout)[-1500:])
    except Exception as e:
        for rel in touched:
            old = backup / rel
            dest = paths.APP / rel
            if old.exists():
                shutil.copy2(old, dest)
            elif dest.exists():
                dest.unlink()
        return {"ok": False, "stage": "apply", "error": str(e)[:1800], "rolled_back": touched}
    (d / "APPLIED").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    needs_restart = any(p.startswith("engine") for p in touched)
    if needs_restart:
        paths.ensure_data()
        (paths.DATA / "restart.flag").write_text(name, encoding="utf-8")
    return {"ok": True, "applied": touched, "backup": str(backup), "restart_requested": needs_restart, "version": data.get("version")}


def make_package(name, version, files, notes=""):
    """Build a package from files already in the app tree (paths relative to APP)."""
    d = paths.APP / "updates" / name
    d.mkdir(parents=True, exist_ok=True)
    entries = []
    for rel in files:
        src = paths.APP / rel
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        entries.append({"path": rel.replace("\\", "/"), "sha256": _sha(dest)})
    (d / "manifest.json").write_text(json.dumps({"version": version, "notes": notes, "files": entries}, indent=2), encoding="utf-8")
    return str(d)


def stamp():
    """Changes whenever UI, modules or engine files change; the page polls this to reload itself."""
    newest = 0.0
    for sub in ALLOWED:
        root = paths.APP / sub
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in {".py", ".html", ".js", ".css", ".json"}:
                    try:
                        newest = max(newest, p.stat().st_mtime)
                    except OSError:
                        pass
    return int(newest)
