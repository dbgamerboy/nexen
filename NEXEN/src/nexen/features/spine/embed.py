"""Optional semantic layer: Ollama embeddings with a persistent cache and a circuit breaker.

Lexical matching misses paraphrases. When Ollama answers, embeddings re-rank candidates. When it is slow or down
(it often is under load) a breaker opens for five minutes and everything keeps working lexically.
"""
import hashlib
import json
import sqlite3
import threading
import time
import urllib.request

from nexen.core import paths
from nexen.shared.utils import textsim

_lock = threading.RLock()
_breaker_until = 0.0


class Embedder:
    def __init__(self, model="embeddinggemma:latest", db_path=None, timeout=6.0):
        self.model, self.timeout = model, timeout
        self.path = str(db_path or (paths.DATA / "embed_cache.db"))
        if self.path != ":memory:":
            paths.ensure_data()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, model TEXT, v TEXT)")
        self.fn = None  # tests inject a function

    def _key(self, text):
        return hashlib.sha256((self.model + "\n" + text).encode()).hexdigest()

    def available(self):
        return self.fn is not None or time.time() >= _breaker_until

    def vector(self, text):
        global _breaker_until
        text = (text or "")[:2000]
        k = self._key(text)
        with _lock:
            row = self.db.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        if row:
            return json.loads(row[0])
        if not self.available():
            return None
        try:
            if self.fn is not None:
                vec = self.fn(text)
            else:
                body = json.dumps({"model": self.model, "input": text}).encode()
                req = urllib.request.Request(paths.OLLAMA_URL + "/api/embed", data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    vec = json.loads(r.read())["embeddings"][0]
        except Exception:
            _breaker_until = time.time() + 300
            return None
        with _lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (k, self.model, json.dumps(vec)))
            self.db.commit()
        return vec

    def rerank(self, query, items, text_of=lambda x: x["text"], keep=None):
        """Return items sorted by semantic similarity, blended with their existing score. Falls back unchanged."""
        qv = self.vector(query)
        if qv is None:
            return items, False
        scored = []
        for it in items:
            v = self.vector(text_of(it))
            if v is None:
                return items, False
            sem = textsim.cosine_vec(qv, v)
            scored.append((0.5 * sem + 0.5 * float(it.get("score", 0)), sem, it))
        scored.sort(key=lambda x: -x[0])
        out = []
        for blended, sem, it in scored[: keep or len(scored)]:
            out.append({**it, "semantic": round(sem, 3), "score": round(blended, 3)})
        return out, True
