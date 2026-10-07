"""Dependency-free text similarity: TF-IDF cosine, token Jaccard and MinHash shingles.

An optional embedding function can be passed to ``composite``; the best of the
lexical and embedding scores wins, so a missing embedding model never blocks learning.
"""
import hashlib
import math
import re
import unicodedata
from collections import Counter

_TOKEN = re.compile(r"[\w']+", re.UNICODE)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
STOP = frozenset("""a an and are as at be but by for from has have in is it its of on or that the this to was were
will with we you your i our they them their he she his her not no do does did can could should would may might
been being than then there these those so if into out up down over under about""".split())
NEGATIONS = frozenset("not no never cannot cant dont doesnt didnt isnt arent wasnt werent without disabled false failed fails blocked".split())
_P = (1 << 61) - 1
_PERMS = 64


def normalize(text):
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text).casefold().replace("_", " ").replace("-", " ")
    return " ".join(_TOKEN.findall(text.replace("’", "'")))


def tokens(text, drop_stop=True):
    words = [w.replace("'", "") for w in normalize(text).split()]
    return [w for w in words if w and (not drop_stop or w not in STOP)]


def numbers(text):
    return set(n.replace(",", "") for n in _NUM.findall(text or ""))


def has_negation(text):
    return sum(1 for w in tokens(text, drop_stop=False) if w in NEGATIONS) % 2 == 1


def fingerprint(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _shingles(text, k=5):
    s = " ".join(tokens(text, drop_stop=False))
    if len(s) <= k:
        return {s} if s else set()
    return {s[i:i + k] for i in range(len(s) - k + 1)}


_COEF = [(((i * 2654435761) | 1) % _P, (i * 40503 + 12345) % _P) for i in range(1, _PERMS + 1)]


def minhash(text):
    base = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big") % _P
            for s in _shingles(text)]
    if not base:
        return tuple([0] * _PERMS)
    return tuple(min((a * h + b) % _P for h in base) for a, b in _COEF)


def minhash_sim(a, b):
    if not a or not b or a == tuple([0] * _PERMS) or b == tuple([0] * _PERMS):
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def tfidf_cosine(a_tokens, b_tokens, df=None, n_docs=1):
    """Cosine of TF-IDF vectors; ``df`` maps token to document frequency over a corpus."""
    ca, cb = Counter(a_tokens), Counter(b_tokens)
    if not ca or not cb:
        return 0.0

    def weight(tok, count):
        d = (df or {}).get(tok, 0)
        idf = math.log((n_docs + 1) / (d + 1)) + 1.0
        return (1 + math.log(count)) * idf

    wa = {t: weight(t, c) for t, c in ca.items()}
    wb = {t: weight(t, c) for t, c in cb.items()}
    dot = sum(wa[t] * wb[t] for t in wa.keys() & wb.keys())
    na = math.sqrt(sum(v * v for v in wa.values()))
    nb = math.sqrt(sum(v * v for v in wb.values()))
    return dot / (na * nb) if na and nb else 0.0


def cosine_vec(u, v):
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    return dot / (nu * nv) if nu and nv else 0.0


def composite(a, b, df=None, n_docs=1, embed=None):
    """0..1 similarity. Exact normalized equality is 1.0."""
    if normalize(a) == normalize(b) and normalize(a):
        return 1.0
    ta, tb = tokens(a), tokens(b)
    lexical = 0.5 * tfidf_cosine(ta, tb, df, n_docs) + 0.3 * jaccard(ta, tb) + 0.2 * minhash_sim(minhash(a), minhash(b))
    if embed is not None:
        try:
            lexical = max(lexical, cosine_vec(embed(a), embed(b)))
        except Exception:  # an embedding outage must not stop learning
            pass
    return min(1.0, lexical)


def key_terms(text, n=6):
    """Rarest-looking content words, longest first as a cheap salience proxy."""
    counts = Counter(t for t in tokens(text) if len(t) > 3 and not t.isdigit())
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-len(kv[0]) - 2 * kv[1], kv[0]))[:n]]


def paragraphs(text, min_chars=60, max_chars=1200):
    """Split a document into passage-sized chunks, keeping the nearest heading as a title."""
    out, heading, buf = [], "", []

    def flush():
        body = " ".join(buf).strip()
        buf.clear()
        if len(body) >= min_chars:
            out.append((heading, body[:max_chars]))

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading = stripped.lstrip("#").strip()[:120]
        elif not stripped:
            flush()
        else:
            buf.append(stripped)
            if sum(len(x) for x in buf) > max_chars:
                flush()
    flush()
    return out
