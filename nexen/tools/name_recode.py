"""Recode the assistant's old name (JARVIS) to MARVIN across NEXEN source, safely.

inventory  count every occurrence by root, file type and category (read-only).
apply      write a recoded COPY of the code under H:\\NEXEN-ENTERPRISE\\Source\\NEXEN-core with a manifest.

For Python the rewrite is token-based: only COMMENTS and PROSE string literals change. Identifiers, imports, file names,
routes, short key-like strings and third-party project names are never touched; they are listed as legacy identifiers
and kept working. Every rewritten .py file must (a) compile and (b) have an AST identical to the original once string
constants are masked, which proves only text changed. A file that fails either check is left as the original copy.
Live V3 files are never modified here: the copy replaces them at cutover.
"""
import argparse
import ast
import io
import json
import os
import py_compile
import re
import shutil
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from nexen import identity  # noqa: E402

ROOTS = [r"H:\NEXEN\v1\app", r"H:\NEXEN\marvin\brain", r"H:\NEXEN\tools", r"H:\NEXEN\apps", r"H:\NEXEN\loop", r"H:\NEXEN\cli", r"H:\NEXEN\launcher",
         r"H:\NEXEN-ENTERPRISE\Apps\BusinessOperations\app", r"H:\NEXEN\boot", r"H:\NEXEN\finetune", r"H:\NEXEN\clipping", r"H:\NEXEN\integrations"]
SKIP = {"__pycache__", "node_modules", "venv", ".git", "site-packages", "library", "arsenal", "repos", "data", "models", "base", "runs", "worktrees", "backups", "tools-venv", "WebView2Fixed153", ".venv", "ComfyUI", "coderabbit", "jobs", "User Data", "kilo", "state", "work", "stage"}
TEXT_EXT = {".md", ".txt"}
CODE_EXT = {".py", ".pyw"}
LIST_ONLY_EXT = {".html", ".js", ".json", ".ps1", ".cmd", ".bat", ".yaml", ".yml", ".toml", ".cs", ".ahk"}
ANY = re.compile(r"(?i)jarvis")
OUT = Path(r"H:\NEXEN-ENTERPRISE\Source\NEXEN-core")


def walk(roots):
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for n in names:
                p = Path(dirpath) / n
                if (p.suffix.lower() in CODE_EXT | TEXT_EXT | LIST_ONLY_EXT or ANY.search(n)) and not n.lower().startswith(("vocab", "merges", "male_names", "female_names", "passwords")):
                    try:
                        if p.stat().st_size < 3_000_000:
                            yield p
                    except OSError:
                        continue


def classify_py(src):
    """Return list of (kind, text) for each JARVIS occurrence: comment, prose-string, key-string, identifier."""
    found = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if not ANY.search(tok.string):
                continue
            if tok.type == tokenize.COMMENT:
                found.append("comment")
            elif tok.type == tokenize.STRING:
                body = tok.string
                prose = (" " in body.strip("\"' ") or "\n" in body) and not identity._PROTECT.fullmatch(body.strip("\"' "))
                found.append("prose-string" if prose else "key-string")
            elif tok.type == tokenize.NAME:
                found.append("identifier")
            else:
                found.append("other")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        found.append("unparseable")
    return found


def inventory():
    rows, files = {}, {}
    for p in walk(ROOTS):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name_hit = bool(ANY.search(p.name))
        n = len(ANY.findall(text))
        if not n and not name_hit:
            continue
        ext = p.suffix.lower()
        kinds = classify_py(text) if ext in CODE_EXT else (["prose"] * n if ext in TEXT_EXT else ["list-only"] * n)
        if name_hit:
            kinds.append("file-name")
        files[str(p)] = {"count": n, "kinds": {k: kinds.count(k) for k in set(kinds)}}
        for k in kinds:
            rows[k] = rows.get(k, 0) + 1
    return {"files": len(files), "occurrences": sum(f["count"] for f in files.values()), "by_kind": rows,
            "top_files": sorted(((v["count"], k) for k, v in files.items()), reverse=True)[:25], "detail": files}


def _mask(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.dump(tree)


def recode_py(src):
    out, last = [], 0
    lines = src.splitlines(keepends=True)
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln))
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    changes = 0
    for tok in toks:
        if not ANY.search(tok.string) or tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        if tok.type == tokenize.STRING:
            body = tok.string
            if not ((" " in body.strip("\"' ") or "\n" in body) and not identity._PROTECT.fullmatch(body.strip("\"' "))):
                continue
        new = identity.normalize(tok.string)
        if new == tok.string:
            continue
        a = offs[tok.start[0] - 1] + tok.start[1]
        b = offs[tok.end[0] - 1] + tok.end[1]
        out.append(src[last:a])
        out.append(new)
        last = b
        changes += 1
    out.append(src[last:])
    return "".join(out), changes


def apply():
    if OUT.exists() and OUT.name == 'NEXEN-core':
        shutil.rmtree(OUT)  # generated output only; rebuilt from the live sources on every run
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"changed": [], "kept_as_original": [], "legacy_identifiers": {}, "list_only": [], "failed_checks": []}
    for p in walk(ROOTS):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ext = p.suffix.lower()
        if not (ANY.search(text) or ANY.search(p.name)):
            continue
        rel = p.drive.replace(":", "") + "\\" + str(p.relative_to(p.anchor))
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if ANY.search(p.name):
            manifest["legacy_identifiers"].setdefault("file-names", []).append(str(p))
        if ext in CODE_EXT:
            res = recode_py(text)
            if res is None:
                shutil.copy2(p, dest)
                manifest["kept_as_original"].append(str(p))
                continue
            new, n = res
            if n:
                try:
                    ok = _mask(ast.parse(text)) == _mask(ast.parse(new))
                except SyntaxError:
                    ok = False
                if ok:
                    dest.write_text(new, encoding="utf-8", newline="")
                    try:
                        py_compile.compile(str(dest), doraise=True, cfile=str(dest) + ".chk")
                        os.remove(str(dest) + ".chk")
                    except py_compile.PyCompileError:
                        ok = False
                if ok:
                    manifest["changed"].append({"file": str(p), "edits": n})
                    leftover = classify_py(new)
                    for k in set(leftover):
                        manifest["legacy_identifiers"].setdefault(k, []).append(str(p))
                    continue
                manifest["failed_checks"].append(str(p))
            shutil.copy2(p, dest)
            for k in set(classify_py(text)):
                manifest["legacy_identifiers"].setdefault(k, []).append(str(p))
        elif ext in TEXT_EXT:
            new = identity.normalize(text)
            dest.write_text(new, encoding="utf-8", newline="")
            if new != text:
                manifest["changed"].append({"file": str(p), "edits": len(ANY.findall(text)) - len(ANY.findall(new))})
        else:
            shutil.copy2(p, dest)
            manifest["list_only"].append({"file": str(p), "occurrences": len(ANY.findall(text))})
    (OUT / "RECODE-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"changed_files": len(manifest["changed"]), "edits": sum(c["edits"] for c in manifest["changed"]), "kept_original": len(manifest["kept_as_original"]),
            "failed_checks": len(manifest["failed_checks"]), "list_only": len(manifest["list_only"]),
            "legacy_kinds": {k: len(v) for k, v in manifest["legacy_identifiers"].items()}, "out": str(OUT)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["inventory", "apply"])
    a = ap.parse_args()
    res = inventory() if a.mode == "inventory" else apply()
    if a.mode == "inventory":
        res.pop("detail")
    print(json.dumps(res, indent=2))

