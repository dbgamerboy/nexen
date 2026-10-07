"""World model: how the world and the public are reading the topics NEXEN lives or dies on.

Free public feeds, no keys, read-only, each one optional. Every number is labeled with WHAT IT MEASURES:
- GDELT average tone: how global news is framing a topic (media framing, not what people think).
- Hacker News stories and points: attention and discussion among a tech-leaning audience.
- Wikipedia top pages: what people looked up yesterday.
- Mastodon trending tags: what is spreading on one open social network.
- RSS headlines: a lexicon score of the day's headlines from BBC and NPR.
No single signal is "public opinion". The summary says so, lists sample sizes, and flags missing sources.
"""
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from nexen.core import paths
from nexen.shared.utils import textsim

TOPICS = ["artificial intelligence", "tiktok", "youtube", "dropshipping", "unemployment", "inflation", "housing", "tariffs", "ai generated content", "freelance"]
FEEDS = {"bbc-world": "http://feeds.bbci.co.uk/news/world/rss.xml", "bbc-business": "http://feeds.bbci.co.uk/news/business/rss.xml",
         "bbc-tech": "http://feeds.bbci.co.uk/news/technology/rss.xml", "npr-news": "https://feeds.npr.org/1001/rss.xml"}
POS = set("""good great win wins gain gains growth grow rise rises surge boom record strong success breakthrough improve improves recovery hope relief
safe safer peace deal agreement boost benefit benefits help helps cure launch launches approve approved praised celebrate best top better""".split())
NEG = set("""bad crisis fall falls drop drops crash war attack killed dead death deaths fear fears threat threats ban bans banned lawsuit fraud scam layoffs
layoff cuts cut recession inflation shortage shortages collapse fail fails failed storm disaster protest protests tariff tariffs warn warns warning
worst risk risks hack hacked leak outage strike shutdown sanctions arrest arrested""".split())
SCHEMA = """CREATE TABLE IF NOT EXISTS snap(id INTEGER PRIMARY KEY, ts REAL, topic TEXT, source TEXT, metric TEXT, value REAL, n INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS run(id INTEGER PRIMARY KEY, ts REAL, sources TEXT, missing TEXT);"""


def http_get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "NEXEN-world/1.0 (local research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def lexicon_score(text):
    toks = [t for t in textsim.tokens(text, drop_stop=False)]
    pos, neg = sum(1 for t in toks if t in POS), sum(1 for t in toks if t in NEG)
    return (pos - neg) / max(1, pos + neg) if (pos + neg) else 0.0


class World:
    def __init__(self, db_path=None, get=None, sleep=time.sleep):
        self.path = str(db_path or (paths.DATA / "world.db"))
        if self.path != ":memory:":
            paths.ensure_data()
        self.get, self.sleep = get or http_get, sleep
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _put(self, topic, source, metric, value, n, detail=""):
        with self.lock:
            self.db.execute("INSERT INTO snap(ts,topic,source,metric,value,n,detail) VALUES(?,?,?,?,?,?,?)", (time.time(), topic, source, metric, value, n, detail[:400]))
            self.db.commit()

    # ------------------------------------------------------------------ collectors
    def gdelt(self, topic):
        q = urllib.parse.quote('"%s"' % topic)
        url = "https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=timelinetone&format=json&timespan=7d" % q
        try:
            raw = self.get(url, 20)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            self.sleep(15)  # rate limited: wait once, then give up for this snapshot
            raw = self.get(url, 20)
        data = json.loads(raw)
        pts = [p["value"] for s in data.get("timeline", []) for p in s.get("data", []) if isinstance(p.get("value"), (int, float))]
        if not pts:
            return None
        half = len(pts) // 2 or 1
        first, last = sum(pts[:half]) / half, sum(pts[half:]) / max(1, len(pts) - half)
        self._put(topic, "gdelt", "tone_7d_mean", sum(pts) / len(pts), len(pts), "trend %+.2f (second half minus first half)" % (last - first))
        self._put(topic, "gdelt", "tone_trend", last - first, len(pts))
        return sum(pts) / len(pts), last - first, len(pts)

    def hackernews(self, topic):
        data = json.loads(self.get("https://hn.algolia.com/api/v1/search_by_date?query=%s&tags=story&hitsPerPage=30" % urllib.parse.quote(topic), 15))
        hits = data.get("hits", [])
        if not hits:
            return None
        pts = sorted(h.get("points") or 0 for h in hits)
        com = sum(h.get("num_comments") or 0 for h in hits)
        self._put(topic, "hackernews", "stories", len(hits), len(hits), "median points %d, comments %d" % (pts[len(pts) // 2], com))
        self._put(topic, "hackernews", "median_points", pts[len(pts) // 2], len(hits))
        return len(hits), pts[len(pts) // 2], com

    def rss(self):
        got = {}
        for name, url in FEEDS.items():
            try:
                root = ET.fromstring(self.get(url, 12))
            except Exception:
                continue
            titles = [(i.findtext("title") or "").strip() for i in root.iter("item")][:25]
            if not titles:
                continue
            score = sum(lexicon_score(t) for t in titles) / len(titles)
            self._put("headlines", name, "lexicon_score", score, len(titles), " | ".join(titles[:3]))
            got[name] = (score, len(titles))
        return got

    def wikipedia(self):
        t = time.gmtime(time.time() - 86400)
        url = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/%04d/%02d/%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
        arts = json.loads(self.get(url, 15))["items"][0]["articles"]
        names = [a["article"].replace("_", " ") for a in arts if not a["article"].startswith(("Main_Page", "Special:", "Wikipedia:", "Portal:", "-"))][:12]
        self._put("attention", "wikipedia", "top_articles", len(names), len(names), ", ".join(names))
        return names

    def mastodon(self):
        tags = json.loads(self.get("https://mastodon.social/api/v1/trends/tags?limit=10", 12))
        names = [x["name"] for x in tags]
        self._put("attention", "mastodon", "trending_tags", len(names), len(names), ", ".join(names))
        return names

    def collect(self, topics=None, sources=None, gdelt_gap=6.0):
        """One snapshot. Returns what answered and what did not; never raises."""
        topics = topics or TOPICS
        sources = sources or ["gdelt", "hackernews", "rss", "wikipedia", "mastodon"]
        ok, missing = {}, []

        def attempt(label, fn):
            try:
                r = fn()
                if r:
                    ok[label] = r
                else:
                    missing.append(label + ":empty")
            except Exception as e:
                missing.append("%s:%s" % (label, type(e).__name__))
        for i, t in enumerate(topics):
            if "gdelt" in sources:
                if i:
                    self.sleep(gdelt_gap)  # GDELT asks for one request every five seconds
                attempt("gdelt:" + t, lambda t=t: self.gdelt(t))
            if "hackernews" in sources:
                attempt("hackernews:" + t, lambda t=t: self.hackernews(t))
        if "rss" in sources:
            attempt("rss", self.rss)
        if "wikipedia" in sources:
            attempt("wikipedia", self.wikipedia)
        if "mastodon" in sources:
            attempt("mastodon", self.mastodon)
        with self.lock:
            self.db.execute("INSERT INTO run(ts,sources,missing) VALUES(?,?,?)", (time.time(), json.dumps(sorted(ok)), json.dumps(missing)))
            self.db.commit()
        return {"answered": len(ok), "missing": missing, "sources": sorted(ok)}

    # ------------------------------------------------------------------ reading it back
    def latest(self, topic, source, metric):
        with self.lock:
            r = self.db.execute("SELECT * FROM snap WHERE topic=? AND source=? AND metric=? ORDER BY id DESC LIMIT 1", (topic, source, metric)).fetchone()
        return dict(r) if r else None

    def previous(self, topic, source, metric):
        with self.lock:
            rows = self.db.execute("SELECT * FROM snap WHERE topic=? AND source=? AND metric=? ORDER BY id DESC LIMIT 2", (topic, source, metric)).fetchall()
        return dict(rows[1]) if len(rows) > 1 else None

    def summary(self, topics=None):
        topics = topics or TOPICS
        rows = []
        for t in topics:
            tone, trend = self.latest(t, "gdelt", "tone_7d_mean"), self.latest(t, "gdelt", "tone_trend")
            hn, hn_prev = self.latest(t, "hackernews", "stories"), self.previous(t, "hackernews", "stories")
            if not (tone or hn):
                continue
            rows.append({"topic": t, "media_tone": round(tone["value"], 2) if tone else None, "tone_trend": round(trend["value"], 2) if trend else None,
                         "tone_samples": tone["n"] if tone else 0, "hn_stories": int(hn["value"]) if hn else None,
                         "hn_change": (int(hn["value"] - hn_prev["value"]) if hn and hn_prev else None)})
        feeds = []
        with self.lock:
            for r in self.db.execute("SELECT source,value,n,detail FROM snap WHERE topic='headlines' AND id IN (SELECT MAX(id) FROM snap WHERE topic='headlines' GROUP BY source)"):
                feeds.append({"feed": r["source"], "headline_score": round(r["value"], 2), "headlines": r["n"]})
        wiki = self.latest("attention", "wikipedia", "top_articles")
        masto = self.latest("attention", "mastodon", "trending_tags")
        with self.lock:
            last = self.db.execute("SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()
        return {"topics": rows, "feeds": feeds, "wikipedia_top": (wiki or {}).get("detail"), "mastodon_trending": (masto or {}).get("detail"),
                "last_run": {"ts": time.strftime("%Y-%m-%d %H:%M", time.localtime(last["ts"])), "missing": json.loads(last["missing"])} if last else None,
                "reading_guide": ["media_tone = GDELT 7-day average tone of global news (-10 negative to +10 positive). It measures media framing, not what people think.",
                                  "hn_stories = recent Hacker News stories on the topic: attention among a tech-leaning audience.",
                                  "headline_score = share of positive minus negative words in today's headlines (-1 to 1).",
                                  "Small sample sizes and missing sources are shown. Never read one signal as public opinion."]}

    def facts(self):
        """Plain-language facts for Novel Learning. Same wording each run, so a new number supersedes the old one."""
        out, s = [], self.summary()
        day = time.strftime("%Y-%m-%d")
        for r in s["topics"]:
            if r["media_tone"] is not None:
                out.append({"text": "GDELT 7 day average news tone for the topic %s is %.2f with trend %.2f across %d samples (media framing, not public opinion)." % (r["topic"], r["media_tone"], r["tone_trend"] or 0, r["tone_samples"]),
                            "source_ids": ["url:gdelt:%s" % r["topic"].replace(" ", "-")], "domain": "world", "observed_at": day + "T12:00:00"})
            if r["hn_stories"] is not None:
                out.append({"text": "Hacker News shows %d recent stories about the topic %s (attention among a tech audience)." % (r["hn_stories"], r["topic"]),
                            "source_ids": ["url:hackernews:%s" % r["topic"].replace(" ", "-")], "domain": "world", "observed_at": day + "T12:00:00"})
        return out

    def relevant(self, query, k=4):
        toks = set(textsim.tokens(query))
        out = []
        for r in self.summary()["topics"]:
            if set(textsim.tokens(r["topic"])) & toks:
                out.append({"id": "world:" + r["topic"], "score": 0.6,
                            "text": "World signal for %s: media tone %s (trend %s, %d samples), Hacker News stories %s. Media framing, not public opinion." % (r["topic"], r["media_tone"], r["tone_trend"], r["tone_samples"], r["hn_stories"])})
        return out[:k]
