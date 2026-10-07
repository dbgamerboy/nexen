"""Head start for Novel and Recursive Learning from public, openly licensed Hugging Face datasets.

Rows come through the datasets-server REST API (no bulk download, no account) and are cached with provenance.
Distillation is extractive: a symptom line, the exceptions named, and the first sentence of the fix. No model is called.
Every fact enters through the novelty gate with a `url:` source, so trust stays at the third-party level (0.5) and
duplicates are reinforced instead of stored twice. Leaked or scraped-without-permission dumps are not used.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from .. import paths

API = "https://datasets-server.huggingface.co"
ERR = re.compile(r"\b\w*(?:Error|Exception)\b|\b(?:error|exception|traceback|fail(?:s|ed|ure)?|crash(?:es|ed)?|bug|not working|broken|timeout|timed out|hang|freez|segfault|deadlock|leak)\b", re.I)
EXC = re.compile(r"\b[A-Z][A-Za-z]+(?:Error|Exception|Warning)\b")

SOURCES = [
    {"id": "princeton-nlp/SWE-bench_Lite", "split": "test", "kind": "swe", "license": "dataset card; issues from public GitHub repos", "limit": 300},
    {"id": "glaiveai/glaive-code-assistant-v3", "split": "train", "kind": "qa", "license": "apache-2.0", "limit": 2400, "q": "question", "a": "answer"},
    {"id": "m-a-p/CodeFeedback-Filtered-Instruction", "split": "train", "kind": "qa", "license": "apache-2.0", "limit": 2400, "q": "query", "a": "answer"},
]


def _get(url, timeout=90):
    """GET JSON; one backoff-and-retry on 429 or a timeout, then the error propagates to the caller."""
    req = urllib.request.Request(url, headers={"User-Agent": "nexen-headstart"})
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as exc:
            if attempt or not (getattr(exc, "code", 0) == 429 or isinstance(exc, TimeoutError)):
                raise
            time.sleep(20)


def _pages(src):
    """Yield rows for one source, 100 per call, until its limit. Failures end that source and are reported."""
    ds = urllib.parse.quote(src["id"], safe="/")
    sp = _get("%s/splits?dataset=%s" % (API, ds)).get("splits", [])
    cfg = next((s["config"] for s in sp if s["split"] == src["split"]), "default")
    off = 0
    while off < src["limit"]:
        if src.get("where"):
            url = "%s/filter?dataset=%s&config=%s&split=%s&where=%s&offset=%d&length=100" % (API, ds, cfg, src["split"], urllib.parse.quote(src["where"]), off)
        else:
            url = "%s/rows?dataset=%s&config=%s&split=%s&offset=%d&length=100" % (API, ds, cfg, src["split"], off)
        rows = _get(url).get("rows", [])
        if not rows:
            return
        for r in rows:
            yield r["row"], off + len(rows)
        off += len(rows)
        time.sleep(0.15)


def _first(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r"(.{20,%d}?[.!?])(\s|$)" % n, text)
    return (m.group(1) if m else text[:n]).strip()


def distill(src, row, idx):
    """One short claim plus its provenance, or None when the row is not about a failure."""
    base = "url:huggingface.co/datasets/%s#%d" % (src["id"], idx)
    if src["kind"] == "swe":
        stmt = str(row.get("problem_statement", ""))
        title = _first(stmt, 200)
        excs = ", ".join(list(dict.fromkeys(EXC.findall(stmt)))[:3])
        text = "Bug pattern in %s: %s%s" % (row.get("repo", "a public repo"), title, (" Exceptions named: %s." % excs) if excs else "")
        return {"text": text[:420], "source_ids": ["url:huggingface.co/datasets/%s#%s" % (src["id"], row.get("instance_id", idx))], "domain": "coding",
                "tags": ["headstart", "swe-bench", str(row.get("repo", ""))]}
    if src["kind"] == "qa":
        q, a = str(row.get(src["q"], "")), str(row.get(src["a"], ""))
        if not ERR.search(q) or len(q) < 25:
            return None
        return {"text": "Symptom: %s Fix: %s" % (_first(q, 230), _first(a, 230)), "source_ids": [base], "domain": "coding", "tags": ["headstart", src["id"].split("/")[1]]}
    if src["kind"] == "reddit":
        s = str(row.get("summary") or row.get("completion") or "").strip()
        if len(s) < 25 or not ERR.search(s):
            return None
        return {"text": "People describe the problem as: %s" % s[:300], "source_ids": [base], "domain": "general", "tags": ["headstart", "reddit-tldr", "techsupport"]}
    return None


def fetch(limit_scale=1.0, log=None, only=None):
    """Download and distill every source into a cached JSONL. Returns per-source counts and any failure."""
    out = paths.DATA / "datasets"
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for src in SOURCES:
        if only and only not in src["id"]:
            continue
        kept, seen, err = [], 0, None
        s = dict(src, limit=int(src["limit"] * limit_scale))
        try:
            for row, idx in _pages(s):
                seen += 1
                d = distill(s, row, seen)
                if d:
                    d["dataset"], d["license"] = s["id"], s["license"]
                    kept.append(d)
        except Exception as exc:  # one dataset failing never stops the others
            err = "%s: %s" % (type(exc).__name__, str(exc)[:120])
        name = s["id"].replace("/", "__")
        with (out / (name + ".jsonl")).open("w", encoding="utf-8") as fh:
            for d in kept:
                fh.write(json.dumps(d) + "\n")
        report.append({"dataset": s["id"], "rows_read": seen, "distilled": len(kept), "license": s["license"], "error": err})
        if log:
            log(report[-1])
    return report


def write_corpus(items):
    """Passages for the recursive learner's local provider: one markdown file per dataset."""
    d = paths.DATA / "datasets" / "corpus"
    d.mkdir(parents=True, exist_ok=True)
    by = {}
    for it in items:
        by.setdefault(it["dataset"], []).append(it["text"])
    for ds, texts in by.items():
        (d / (ds.replace("/", "__") + ".md")).write_text("# %s (distilled, third-party claims)\n\n" % ds + "\n\n".join(texts), encoding="utf-8")
    return str(d)


def load_cached():
    items = []
    for f in sorted((paths.DATA / "datasets").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
    return items


def ingest(app, spine, items=None):
    """Push cached items through the novelty gate; measure spine coverage on real bug reports; seed the frontier."""
    items = items if items is not None else load_cached()
    ops, uncovered = {}, []
    t0 = time.time()
    covered = swe = 0
    for it in items:
        r = app.novel.ingest({"text": it["text"], "source_ids": it["source_ids"], "domain": it["domain"], "tags": it["tags"], "origin": "headstart"})
        ops[r["op"]] = ops.get(r["op"], 0) + 1
        if "swe-bench" in it["tags"]:
            swe += 1
            if spine.diagnose(it["text"], k=1)["confident"]:
                covered += 1
            else:
                uncovered.append(it["text"][:200])
    seeded = 0
    for q in uncovered[:60]:
        if app.ledger.push_frontier("What is the common cause and fix for: " + q, "headstart", "coding", 0.9, 0):
            seeded += 1
    for pid, p in spine.problems.items():
        if p.get("evidence") == "general" and app.ledger.push_frontier("What do public sources say about preventing: " + p["title"], "headstart:" + pid, "coding", 0.6, 0):
            seeded += 1
    corpus = write_corpus(items)
    return {"items": len(items), "ops": ops, "seconds": round(time.time() - t0, 1), "swe_reports": swe,
            "catalog_confident_on_real_bug_reports": round(covered / swe, 3) if swe else None, "frontier_seeded": seeded, "corpus_dir": corpus}
