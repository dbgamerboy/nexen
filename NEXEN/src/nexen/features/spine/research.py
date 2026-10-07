"""Research you can see: what was learned, from where, with a link to the source, plus YouTube transcript research.

YouTube research uses the yt-dlp already on this PC to fetch only the auto-generated English subtitles (small text files),
never the video. Passages go through Novel Learning with source ids url:youtube:<id>, so the viewer can link back.
"""
import glob
import json
import os
import re
import time
from pathlib import Path

from nexen.core import paths
from nexen.shared.utils import textsim
from nexen.features.connectors import base

YTDLP = paths.H_NEXEN / "tools" / "yt-dlp" / "yt-dlp.exe"


def link_for(source_id):
    s = str(source_id)
    if s.startswith("url:youtube:"):
        return "https://www.youtube.com/watch?v=" + s.split(":", 2)[2]
    if s.startswith("url:gdelt:"):
        return "https://api.gdeltproject.org/api/v2/doc/doc?query=%22" + s.split(":", 2)[2].replace("-", "%20") + "%22&mode=timelinetone&timespan=7d"
    if s.startswith("url:hackernews:"):
        return "https://hn.algolia.com/?q=" + s.split(":", 2)[2].replace("-", "+")
    if s.startswith("file:"):
        return s[5:].split("#")[0]
    if s.startswith("url:"):
        return s[4:]
    return None


def items(app, query="", domain=None, origin=None, limit=60):
    """Research items for the viewer: newest first, filtered, each with clickable source links."""
    where, args = ["status IN ('admitted','superseded')"], []
    if domain:
        where.append("domain=?")
        args.append(domain)
    if origin:
        where.append("origin=?")
        args.append(origin)
    if query:
        where.append("text LIKE ?")
        args.append("%" + query + "%")
    sql = "SELECT * FROM items WHERE %s ORDER BY created_at DESC LIMIT ?" % " AND ".join(where)
    args.append(limit)
    with app.ledger.lock:
        rows = [app.ledger._row(r) for r in app.ledger.db.execute(sql, args)]
    out = []
    for it in rows:
        out.append({"id": it["id"], "text": it["text"], "title": it["title"], "domain": it["domain"], "origin": it["origin"], "trust": it["trust"], "status": it["status"],
                    "created": it["created_at"], "sources": [{"id": s, "link": link_for(s)} for s in it["source_ids"][:4]], "evidence_n": it["evidence_n"]})
    return out


def _vtt_text(path):
    lines, last = [], ""
    for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if not ln or ln.startswith(("WEBVTT", "Kind:", "Language:")) or "-->" in ln or re.fullmatch(r"\d+", ln):
            continue
        if ln != last:
            lines.append(ln)
            last = ln
    return " ".join(lines)


def youtube(app, query, videos=2, max_passages=30, timeout=240):
    """Search YouTube, fetch subtitles only, learn the passages. Returns what was found and what the gate did with it."""
    if not YTDLP.is_file():
        return {"ok": False, "error": "yt-dlp not found at %s" % YTDLP}
    out = paths.DATA / "youtube"
    out.mkdir(parents=True, exist_ok=True)
    stamp = "%d" % time.time()
    tmpl = str(out / (stamp + "-%(id)s.%(ext)s"))
    rc, so, se = base.run_cli([str(YTDLP), "ytsearch%d:%s" % (videos, query), "--skip-download", "--write-auto-subs", "--sub-langs", "en", "--sub-format", "vtt",
                               "--print", "META|%(id)s|%(title)s|%(channel)s|%(duration)s", "--no-simulate", "-o", tmpl, "--no-warnings", "--socket-timeout", "15"], timeout=timeout)
    metas = [l.split("|", 4) for l in so.splitlines() if l.startswith("META|")]
    results, counts = [], {}
    for m in metas:
        vid, title, channel = m[1], m[2], m[3]
        vtts = glob.glob(str(out / ("%s-%s*.vtt" % (stamp, vid))))
        if not vtts:
            results.append({"id": vid, "title": title, "passages": 0, "note": "no English auto-subtitles"})
            continue
        text = _vtt_text(vtts[0])
        words = text.split()
        passages = [" ".join(words[i:i + 120]) for i in range(0, min(len(words), 120 * max_passages), 120)]
        n = 0
        for p in passages:
            r = app.novel.ingest({"text": p, "title": "YouTube: %s (%s)" % (title, channel), "source_ids": ["url:youtube:" + vid], "origin": "youtube", "tags": ["youtube", query]})
            counts[r["op"]] = counts.get(r["op"], 0) + 1
            n += r["op"] in {"ADD", "UPDATE"}
        results.append({"id": vid, "title": title, "channel": channel, "passages": len(passages), "admitted": n, "url": "https://www.youtube.com/watch?v=" + vid})
    return {"ok": bool(metas), "query": query, "videos": results, "ops": counts, "yt_dlp_exit": rc, "stderr": base.redact(se[-200:]) if rc else ""}
