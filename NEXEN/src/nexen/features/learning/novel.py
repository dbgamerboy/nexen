"""Novel Learning: a novelty gate in front of a bitemporal knowledge ledger.

Research it applies:
- SAGE-style novelty gate: embed-or-lexical distance to memory decides admission.
- Mem0-style operations: ADD, UPDATE (supersede), REINFORCE, NOOP, plus HOLD for review.
- Zep-style validity windows: a superseded fact keeps valid_from/valid_to, so
  ``recall(as_of=...)`` answers what NEXEN believed at a past time.
- MAP-Elites style archive over domain by evidence strength, and a gap map that
  points curiosity at thin, money-weighted cells.

The gate admits into V4's own ledger. It never writes to V3 files or the vault.
"""
import math
import time

from nexen.core import identity
from nexen.shared.utils import textsim
from nexen.features.learning.ledger import Ledger, now

DOMAIN_WEIGHT = {"money": 1.0, "coding": 0.9, "clipping": 0.8, "dropshipping": 0.8, "marvin": 0.7,
                 "infra": 0.7, "learning": 0.6, "music": 0.4, "general": 0.3}
DOMAIN_WORDS = {
    "money": "revenue money income sale sales paid payout price profit affiliate client upwork fiverr offer invoice cash",
    "clipping": "clip clipper clipping whop campaign reels shorts caption subtitle ffmpeg",
    "dropshipping": "dropshipping supplier product tiktok shop store curviana lumipaw shopify listing",
    "coding": "code python test tests function module bug refactor commit build compile exe api cli mcp",
    "marvin": "marvin voice discord assistant hud brain tts",
    "infra": "n8n ollama pc2 gpu worker queue server port workflow backup stop pause scheduler",
    "learning": "learning novelty recursive memory knowledge ledger recall retrieval embedding",
    "music": "music beat mix master mastering wdr stems render fl studio song",
}
SOURCE_BASE = {"owner": 0.90, "receipt": 0.80, "test": 0.70, "file": 0.60, "url": 0.50, "chat": 0.35, "model": 0.25}


def infer_domain(text):
    toks = set(textsim.tokens(text))
    best, score = "general", 0
    for dom, words in DOMAIN_WORDS.items():
        hit = len(toks & set(words.split()))
        if hit > score:
            best, score = dom, hit
    return best


def source_trust(source_ids):
    """Independent sources raise trust with diminishing returns; no source means zero."""
    if not source_ids:
        return 0.0
    miss = 1.0
    for i, sid in enumerate(dict.fromkeys(source_ids)):
        base = SOURCE_BASE.get(str(sid).split(":", 1)[0].lower(), 0.40)
        miss *= 1.0 - base * (0.85 ** i)
    return round(1.0 - miss, 4)


def quality_score(text, has_sources):
    words = textsim.tokens(text, drop_stop=False)
    n = len(words)
    if n == 0:
        return 0.0
    length = 1.0 if 8 <= n <= 160 else (n / 8 if n < 8 else max(0.4, 160 / n))
    uniq = len(set(words)) / n
    specific = min(1.0, (len(textsim.numbers(text)) * 0.25 + len(textsim.key_terms(text, 8)) * 0.1))
    # Length gates everything: a two-word note cannot score well on uniqueness alone.
    return round(min(1.0, length * (0.4 + 0.6 * (0.4 * uniq + 0.4 * specific + 0.2 * (1.0 if has_sources else 0.0)))), 4)


def _collect_sources(candidate):
    out = []
    for v in candidate.get("source_ids") or []:
        if isinstance(v, str) and v.strip():
            out.append(v.strip()[:300])
    for s in candidate.get("sources") or []:
        if isinstance(s, dict):
            ident = s.get("source_id") or s.get("id")
            if isinstance(ident, str) and ident.strip():
                out.append(ident.strip()[:300])
    return list(dict.fromkeys(out))[:50]


def _text(candidate):
    if isinstance(candidate, str):
        return candidate[:12000]
    parts = [candidate.get(k) for k in ("title", "text", "summary") if isinstance(candidate.get(k), str)]
    return " ".join(parts)[:12000]


class NovelLearner:
    def __init__(self, ledger=None, embed=None):
        self.ledger = ledger or Ledger()
        self.embed = embed

    # assessment ---------------------------------------------------------------
    def assess(self, candidate):
        if isinstance(candidate, str):
            candidate = {"text": candidate}
        text = _text(candidate)
        fp = textsim.fingerprint(text)
        res = {"fingerprint": fp, "op": "REJECT", "status": "rejected", "novelty": 0.0, "best_sim": 0.0,
               "neighbor_id": None, "quality": 0.0, "trust": 0.0, "reasons": [], "relation": None}
        if not textsim.normalize(text):
            res["reasons"].append("empty after normalization")
            return res
        p = self.ledger.params()
        sources = _collect_sources(candidate)
        owner_origin = str(candidate.get("origin", "")).lower() in {"owner", "user"}
        if owner_origin and not sources:
            sources = ["owner:direct"]
        res["trust"] = source_trust(sources)
        res["quality"] = quality_score(text, bool(sources))
        res["domain"] = candidate.get("domain") or infer_domain(text)
        res["sources"] = sources

        same = self.ledger.find_fingerprint(fp)
        if same is not None:
            res.update(neighbor_id=same["id"], best_sim=1.0, novelty=0.0)
            new_src = [s for s in sources if s not in (same["source_ids"] or [])]
            res["op"], res["status"] = ("REINFORCE", "admitted") if new_src else ("NOOP", "admitted")
            res["reasons"].append("exact duplicate; %d new independent source(s)" % len(new_src))
            return res

        neighbors = self.ledger.neighbors(text)
        toks = textsim.tokens(text)
        n_docs = max(1, self.ledger.count())
        df = self.ledger.doc_freq(toks + [t for nb in neighbors for t in textsim.tokens(nb["text"])][:200])
        best, best_sim, scored = None, 0.0, []
        for nb in neighbors:
            s = textsim.composite(text, nb["title"] + " " + nb["text"] if nb["title"] else nb["text"], df, n_docs, self.embed)
            scored.append((s, nb))
            if s > best_sim:
                best, best_sim = nb, s
        # Novelty mixes distance (1 - similarity) with information gain: the share of this
        # candidate's terms that the three nearest memories do not already contain.
        known = set()
        for _, nb in sorted(scored, key=lambda x: -x[0])[:3]:
            known |= set(textsim.tokens(nb["text"]))
        gain = (len(set(toks) - known) / len(set(toks))) if toks and known else 1.0
        res["best_sim"] = round(best_sim, 4)
        res["gain"] = round(gain, 4)
        res["novelty"] = round(0.5 * (1.0 - best_sim) + 0.5 * gain, 4)
        res["neighbor_id"] = best["id"] if best else None

        if best is not None and best_sim >= p["dup_threshold"]:
            new_src = [s for s in sources if s not in (best["source_ids"] or [])]
            res["op"], res["status"] = ("REINFORCE", "admitted") if new_src else ("NOOP", "admitted")
            res["reasons"].append("near duplicate (sim %.2f)" % best_sim)
            return res

        if not sources:
            res.update(op="HOLD", status="held")
            res["reasons"].append("no provenance: needs a source id before admission")
            return res
        if res["quality"] < p["quality_min"]:
            res.update(op="HOLD", status="held")
            res["reasons"].append("quality %.2f below %.2f" % (res["quality"], p["quality_min"]))
            return res

        if best is not None and best_sim >= p["update_threshold"]:
            return self._same_subject(res, candidate, text, best, p)

        if res["novelty"] < p["novelty_min"]:
            res.update(op="NOOP", status="rejected")
            res["reasons"].append("novelty %.2f below %.2f" % (res["novelty"], p["novelty_min"]))
            return res
        res.update(op="ADD", status="admitted")
        res["reasons"].append("novel: nearest similarity %.2f" % best_sim)
        return res

    def _same_subject(self, res, candidate, text, old, p):
        old_toks, new_toks = textsim.tokens(old["text"]), textsim.tokens(text)
        overlap = textsim.jaccard(old_toks, new_toks)
        # Supersession needs the SAME claim with a different value. Passages that share a template but differ in
        # words (two bake-off winners, two inventory rows, two commands) are different facts and both stay.
        words_old = [t for t in old_toks if not any(c.isdigit() for c in t)]
        words_new = [t for t in new_toks if not any(c.isdigit() for c in t)]
        same_claim = textsim.jaccard(words_old, words_new) >= 0.85
        num_changed = same_claim and textsim.numbers(old["text"]) != textsim.numbers(text) and textsim.numbers(old["text"]) and textsim.numbers(text)
        neg_flip = textsim.has_negation(old["text"]) != textsim.has_negation(text)
        if neg_flip:
            plain_old = [t for t in words_old if t not in textsim.NEGATIONS]
            plain_new = [t for t in words_new if t not in textsim.NEGATIONS]
            neg_flip = textsim.jaccard(plain_old, plain_new) >= 0.7   # a flipped word inside a long, different passage is not a contradiction
        newer = str(candidate.get("observed_at") or now()) >= str(old.get("observed_at") or "")
        old_trust = old.get("trust") or 0.0
        if neg_flip:
            res["relation"] = "contradiction"
            if res["trust"] >= old_trust + p["trust_margin"] and newer:
                res.update(op="UPDATE", status="admitted")
                res["reasons"].append("contradicts item %s; newer and more trusted, supersedes" % old["id"])
            else:
                res.update(op="HOLD", status="held")
                res["reasons"].append("contradicts item %s; trust gap too small, held for resolution" % old["id"])
            return res
        if num_changed and overlap >= 0.45:
            res["relation"] = "value_change"
            if newer and res["trust"] >= old_trust - 0.10:
                res.update(op="UPDATE", status="admitted")
                res["reasons"].append("value changed vs %s; newer observation supersedes" % old["id"])
            else:
                res.update(op="HOLD", status="held")
                res["reasons"].append("value differs from %s but is older or less trusted" % old["id"])
            return res
        added = len(set(new_toks) - set(old_toks)) / max(1, len(set(new_toks)))
        if added >= 0.30:
            # Same subject, new information: keep both. Only value changes and contradictions supersede,
            # so an extension can never delete a still-true older item.
            res["relation"] = "extension"
            res.update(op="ADD", status="admitted")
            res["reasons"].append("extends %s with %.0f%% new terms; both kept" % (old["id"], added * 100))
            return res
        res["relation"] = "restatement"
        res.update(op="NOOP", status="rejected")
        res["reasons"].append("restates %s without new information" % old["id"])
        return res

    # ingestion ------------------------------------------------------------------
    def ingest(self, candidate, depth=0, origin=None):
        if isinstance(candidate, str):
            candidate = {"text": candidate}
        candidate = dict(candidate)
        for key in ("text", "title", "summary"):  # JARVIS is MARVIN: stored knowledge never carries two names
            if isinstance(candidate.get(key), str):
                candidate[key] = identity.normalize(candidate[key])
        a = self.assess(candidate)
        led = self.ledger
        item_id = a["neighbor_id"] if a["op"] in {"REINFORCE", "NOOP"} else None
        if a["op"] in {"ADD", "UPDATE", "HOLD"}:
            rec = {"fingerprint": a["fingerprint"], "title": str(candidate.get("title", ""))[:200],
                   "text": _text({"text": candidate.get("text", candidate.get("summary", ""))}) or _text(candidate),
                   "domain": a["domain"], "tags": candidate.get("tags") or [], "source_ids": a["sources"],
                   "trust": a["trust"], "novelty": a["novelty"], "quality": a["quality"], "status": a["status"],
                   "origin": origin or candidate.get("origin") or "novel", "depth": depth,
                   "observed_at": str(candidate.get("observed_at") or now()),
                   "meta": {**(candidate.get("meta") or {}), "relation": a.get("relation"), "related": a.get("neighbor_id")}}
            if a["op"] == "UPDATE":
                rec["supersedes"] = a["neighbor_id"]
            item_id = led.insert_item(rec)
            if a["op"] == "UPDATE":
                led.supersede(a["neighbor_id"], led.get(item_id)["valid_from"])
                if a.get("relation") in {"contradiction", "value_change"}:
                    led.label_decision(a["neighbor_id"], 0, "superseded:" + a["relation"])
        elif a["op"] == "REINFORCE":
            led.add_sources(item_id, a["sources"])
            merged = led.get(item_id)
            led.set_trust(item_id, source_trust(merged["source_ids"]))
            led.label_decision(item_id, 1, "corroborated")
        elif a["op"] == "REJECT":
            item_id = None
        led.log_decision(item_id, a["op"], a["novelty"], a["best_sim"], a["quality"], a["trust"])
        led.event("ingest", item_id, {"op": a["op"], "reasons": a["reasons"], "depth": depth})
        a["item_id"] = item_id
        a["can_publish"] = False
        return a

    def release(self, item_id):
        """Promote a held item after a human or an agent fixed its provenance. Re-checks the gate."""
        item = self.ledger.get(item_id)
        if item is None or item["status"] != "held":
            return {"ok": False, "reason": "not a held item"}
        self.ledger.reject(item_id, "released for re-assessment")
        out = self.ingest({"text": item["text"], "title": item["title"], "domain": item["domain"],
                           "source_ids": item["source_ids"], "tags": item["tags"]})
        return {"ok": out["op"] in {"ADD", "UPDATE", "REINFORCE"}, "result": out}

    def undo_supersede(self, new_id):
        """Reverse a supersession: the older item is valid again and the newer one stops claiming to replace it."""
        new = self.ledger.get(new_id)
        if new is None or not new.get("supersedes"):
            return {"ok": False, "reason": "item does not supersede anything"}
        old_id = new["supersedes"]
        self.ledger.restore(old_id)
        with self.ledger.lock:
            self.ledger.db.execute("UPDATE items SET supersedes=NULL WHERE id=?", (new_id,))
            self.ledger.db.commit()
        self.ledger.label_decision(old_id, 1, "restored")
        self.ledger.event("undo_supersede", new_id, {"restored": old_id})
        return {"ok": True, "restored": old_id, "kept": new_id}

    def reaudit_supersessions(self):
        """Re-check every supersession against the current rule and undo the ones it would no longer make."""
        with self.ledger.lock:
            ids = [r["id"] for r in self.ledger.db.execute("SELECT id FROM items WHERE supersedes IS NOT NULL")]
        undone, kept = [], 0
        for new_id in ids:
            new = self.ledger.get(new_id)
            old = self.ledger.get(new["supersedes"])
            if old is None:
                continue
            words_old = [t for t in textsim.tokens(old["text"]) if not any(c.isdigit() for c in t)]
            words_new = [t for t in textsim.tokens(new["text"]) if not any(c.isdigit() for c in t)]
            if textsim.jaccard(words_old, words_new) >= 0.85:
                kept += 1
            else:
                undone.append(self.undo_supersede(new_id))
        return {"checked": len(ids), "kept": kept, "undone": len(undone)}

    def feedback(self, item_id, good, note=""):
        self.ledger.label_decision(item_id, 1 if good else 0, "owner")
        if not good:
            self.ledger.reject(item_id, "owner marked bad: " + note)
        self.ledger.event("feedback", item_id, {"good": bool(good), "note": note})

    # recall --------------------------------------------------------------------
    def recall(self, query, k=5, as_of=None, domain=None):
        if as_of:
            pool = self.ledger.valid_items(domain, as_of, limit=2000)
        else:
            pool = self.ledger.neighbors(query, k=max(k, 5))
            if domain:
                pool = [x for x in pool if x["domain"] == domain]
        n_docs = max(1, self.ledger.count())
        df = self.ledger.doc_freq(textsim.tokens(query))
        ranked, t_now = [], time.time()
        for it in pool:
            sim = textsim.composite(query, it["text"], df, n_docs, self.embed)
            age_days = 0.0
            try:
                age_days = max(0.0, (t_now - time.mktime(time.strptime(it["created_at"][:19], "%Y-%m-%dT%H:%M:%S"))) / 86400)
            except (ValueError, OverflowError):
                pass
            score = 0.60 * sim + 0.20 * (it["trust"] or 0) + 0.15 * math.exp(-age_days / 45) + 0.05 * min(it["uses"] or 0, 10) / 10
            ranked.append((score, sim, it))
        ranked.sort(key=lambda x: -x[0])
        out = []
        for score, sim, it in ranked[:k]:
            if not as_of:
                self.ledger.touch(it["id"])
            out.append({"id": it["id"], "score": round(score, 4), "similarity": round(sim, 4), "text": it["text"],
                        "title": it["title"], "domain": it["domain"], "trust": it["trust"],
                        "evidence_n": it["evidence_n"], "source_ids": it["source_ids"],
                        "valid_from": it["valid_from"], "valid_to": it["valid_to"], "status": it["status"]})
        return out

    # coverage and curiosity ------------------------------------------------------
    def archive(self):
        """MAP-Elites archive: best admitted item per (domain, evidence bin)."""
        cells = {}
        for it in self.ledger.valid_items(limit=5000):
            if it["status"] != "admitted":
                continue
            bin_ = "1" if it["evidence_n"] <= 1 else ("2" if it["evidence_n"] == 2 else "3+")
            fitness = (it["quality"] or 0) * (0.5 + (it["novelty"] or 0)) * (0.5 + (it["trust"] or 0))
            key = "%s|%s" % (it["domain"], bin_)
            if key not in cells or fitness > cells[key]["fitness"]:
                cells[key] = {"cell": key, "fitness": round(fitness, 4), "id": it["id"], "text": it["text"][:160]}
        return sorted(cells.values(), key=lambda c: c["cell"])

    def gaps(self):
        """Domains ranked by weighted thinness and lack of corroboration; drives curiosity."""
        stats = {}
        for it in self.ledger.valid_items(limit=5000):
            if it["status"] != "admitted":
                continue
            s = stats.setdefault(it["domain"], {"n": 0, "corroborated": 0, "trust": 0.0})
            s["n"] += 1
            s["corroborated"] += 1 if it["evidence_n"] >= 2 else 0
            s["trust"] += it["trust"] or 0
        out = []
        for dom, w in DOMAIN_WEIGHT.items():
            s = stats.get(dom, {"n": 0, "corroborated": 0, "trust": 0.0})
            share = s["corroborated"] / s["n"] if s["n"] else 0.0
            score = w * (1.0 / (1 + s["n"])) + w * (1 - share) * 0.5
            out.append({"domain": dom, "items": s["n"], "corroborated_share": round(share, 3),
                        "gap_score": round(score, 4), "weight": w})
        return sorted(out, key=lambda x: -x["gap_score"])
