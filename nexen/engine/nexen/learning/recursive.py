"""Recursive Learning: question -> evidence -> gate -> follow-up questions, bounded.

Research it applies:
- Reflexion / ReasoningBank: every run stores a lesson (what strategy, what yield).
- Voyager skill library: strategies that keep paying off become named recipes.
- Darwin Godel Machine style archive and bandit: UCB1 picks among strategy variants,
  so the loop improves its own search policy from measured yield, not from guesses.
- Curiosity: the frontier is seeded from the money-weighted gap map of Novel Learning.

Safety bounds: depth <= 3, candidates per run <= 60, wall time capped, cycle and stall
detection, follow-ups are questions (never facts), results land only in the V4 ledger.
"""
import hashlib
import math
import os
import time
from pathlib import Path

from .. import textsim
from .novel import DOMAIN_WEIGHT, DOMAIN_WORDS, NovelLearner, infer_domain

MAX_DEPTH = 3
MAX_CANDIDATES = 60
REWARD = {"ADD": 1.0, "UPDATE": 0.8, "REINFORCE": 0.3, "HOLD": 0.0, "NOOP": -0.05, "REJECT": -0.1}
STRATEGIES = {
    "wide": {"depth": 1, "per_question": 12},
    "balanced": {"depth": 2, "per_question": 8},
    "deep": {"depth": 3, "per_question": 5},
}


class LocalCorpusProvider:
    """Finds passages in local notes. Read-only; bounded file count and size; cached by mtime."""

    def __init__(self, roots, exts=(".md", ".txt"), max_files=600, max_bytes=300_000, budget=12.0):
        self.roots = [Path(r) for r in roots]
        self.exts, self.max_files, self.max_bytes, self.budget = exts, max_files, max_bytes, budget
        self._cache = {}
        self._files = None

    def _list(self):
        if self._files is None:
            found, started = [], time.time()
            for root in self.roots:
                if time.time() - started > self.budget:
                    break
                try:
                    for dirpath, dirs, names in os.walk(root):
                        if time.time() - started > self.budget:
                            break
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "node_modules"}]
                        for n in names:
                            if n.lower().endswith(self.exts):
                                p = Path(dirpath) / n
                                try:
                                    found.append((p.stat().st_mtime, p))
                                except OSError:
                                    continue
                        if len(found) > self.max_files * 4:
                            break
                except OSError:
                    continue
            found.sort(key=lambda x: -x[0])
            self._files = [p for _, p in found[: self.max_files]]
        return self._files

    def _passages(self, path):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
        hit = self._cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            raw = path.read_bytes()[: self.max_bytes]
        except OSError:
            return []
        sha = hashlib.sha256(raw).hexdigest()[:10]
        text = raw.decode("utf-8", errors="replace")
        out = [(h, b, "file:%s#%s@%s" % (path, (h or "top")[:40].replace(" ", "_"), sha)) for h, b in textsim.paragraphs(text)]
        self._cache[path] = (mtime, out)
        return out

    def fetch(self, question, limit=8):
        q = textsim.tokens(question)
        if not q:
            return []
        qset, scored = set(q), []
        for path in self._list():
            for heading, body, sid in self._passages(path):
                toks = textsim.tokens(heading + " " + body)
                if not toks:
                    continue
                hit = len(qset & set(toks))
                if hit >= max(2, len(qset) // 2):
                    scored.append((hit / math.sqrt(len(set(toks)) + 1), heading, body, sid))
        scored.sort(key=lambda x: -x[0])
        return [{"title": h, "text": b, "source_ids": [sid], "origin": "recursive"} for _, h, b, sid in scored[:limit]]


def followups(item_text, domain, n=2):
    """Cheap heuristic follow-up questions from an admitted fact. No model needed."""
    terms = textsim.key_terms(item_text, 6)
    out = []
    if len(terms) >= 2:
        out.append("%s %s evidence" % (terms[0], terms[1]))
    if len(terms) >= 4:
        out.append("%s %s status" % (terms[2], terms[3]))
    if len(terms) >= 6:
        out.append("%s %s result" % (terms[4], terms[5]))
    return out[:n]


class RecursiveLearner:
    def __init__(self, novel=None, provider=None):
        self.novel = novel or NovelLearner()
        self.ledger = self.novel.ledger
        self.provider = provider

    # strategy selection: UCB1 over measured yield ----------------------------------
    def choose_strategy(self, explore=1.2):
        stats = self.ledger.strategy_stats()
        total = sum(p for p, _ in stats.values()) + 1
        best, best_score = None, -1e9
        for name in STRATEGIES:
            pulls, reward = stats.get(name, (0, 0.0))
            if pulls == 0:
                return name
            score = reward / pulls + explore * math.sqrt(math.log(total) / pulls)
            if score > best_score:
                best, best_score = name, score
        return best

    def seed_questions(self, k=3):
        """Curiosity: one question per thinnest money-weighted domain."""
        out = []
        for gap in self.novel.gaps()[:k]:
            words = DOMAIN_WORDS.get(gap["domain"], "knowledge").split()
            out.append((" ".join(words[:3]), gap["domain"], gap["gap_score"]))
        return out

    # the loop ------------------------------------------------------------------------
    def run(self, questions=None, strategy=None, max_seconds=30, max_candidates=MAX_CANDIDATES, provider=None):
        provider = provider or self.provider
        if provider is None:
            raise ValueError("a provider with fetch(question, limit) is required")
        strategy = strategy or self.choose_strategy()
        cfg = STRATEGIES[strategy]
        max_depth = min(cfg["depth"], MAX_DEPTH)
        started = time.time()
        queue = []
        if questions:
            for q in questions:
                queue.append((q if isinstance(q, str) else q[0], 0, "root", infer_domain(q if isinstance(q, str) else q[0])))
        else:
            for row in self.ledger.pop_frontier(limit=4, max_depth=max_depth):
                queue.append((row["question"], row["depth"], row["parent"] or "frontier", row["domain"] or "general"))
            if not queue:
                for q, dom, _ in self.seed_questions():
                    queue.append((q, 0, "gap", dom))
        seen_q, evaluated, counts, reward_sum = set(), 0, {}, 0.0
        tree, truncated = [], False
        while queue:
            question, depth, parent, domain = queue.pop(0)
            qfp = textsim.fingerprint(question)
            if qfp in seen_q:
                continue
            seen_q.add(qfp)
            if evaluated >= max_candidates or time.time() - started > max_seconds:
                truncated = True
                self.ledger.push_frontier(question, parent, domain, DOMAIN_WEIGHT.get(domain, 0.3), depth)
                continue
            try:
                found = provider.fetch(question, cfg["per_question"])
            except Exception as exc:
                self.ledger.event("provider_error", None, {"question": question, "error": type(exc).__name__})
                self.ledger.close_frontier(question, "error")
                continue
            admitted_here = 0
            for cand in found:
                if evaluated >= max_candidates:
                    truncated = True
                    break
                res = self.novel.ingest(cand, depth=depth, origin="recursive")
                evaluated += 1
                counts[res["op"]] = counts.get(res["op"], 0) + 1
                reward_sum += REWARD.get(res["op"], 0.0)
                if res["op"] in {"ADD", "UPDATE"} and res.get("item_id"):
                    admitted_here += 1
                    if depth < max_depth:
                        for fq in followups(cand["text"], res.get("domain", "general")):
                            if textsim.fingerprint(fq) not in seen_q:
                                pri = DOMAIN_WEIGHT.get(res.get("domain", "general"), 0.3) * (res["novelty"] or 0.5)
                                if depth + 1 <= max_depth:
                                    queue.append((fq, depth + 1, res["item_id"], res.get("domain", "general")))
                                self.ledger.push_frontier(fq, res["item_id"], res.get("domain", "general"), pri, depth + 1)
            self.ledger.close_frontier(question, "done")
            tree.append({"question": question, "depth": depth, "found": len(found), "admitted": admitted_here})
            # stall detection: an empty branch does not descend further (its follow-ups were never queued)
        yield_per = reward_sum / evaluated if evaluated else 0.0
        self.ledger.strategy_update(strategy, yield_per)
        self.ledger.add_lesson("success" if yield_per >= 0.3 else "failure",
                               "; ".join(t["question"] for t in tree[:5]), strategy,
                               "evaluated=%d ops=%s" % (evaluated, counts), yield_per)
        if tree:
            dom = tree[0].get("domain") or infer_domain(tree[0]["question"])
            self.ledger.upsert_skill("recipe:%s:%s" % (strategy, dom),
                                     "Research recipe: %s strategy over a local corpus" % strategy,
                                     {"strategy": strategy, **cfg, "provider": type(provider).__name__},
                                     yield_per >= 0.3)
        self.ledger.event("recursive_run", None, {"strategy": strategy, "evaluated": evaluated, "ops": counts,
                                                   "yield": round(yield_per, 3), "truncated": truncated})
        return {"strategy": strategy, "evaluated": evaluated, "ops": counts, "yield": round(yield_per, 3),
                "tree": tree, "truncated": truncated, "max_depth": max_depth, "automatic_publish": False}

    # tree mode, compatible with the V1 companion contract --------------------------------
    def run_tree(self, seeds, expand=None, max_depth=MAX_DEPTH, max_candidates=50):
        if not 0 <= max_depth <= MAX_DEPTH:
            raise ValueError("max_depth must be between 0 and 3")
        if not 1 <= max_candidates <= 50:
            raise ValueError("max_candidates must be between 1 and 50")
        results, seen, errors = [], set(), 0

        def walk(cand, depth, ancestry):
            nonlocal errors
            if len(results) >= max_candidates:
                return
            text = cand if isinstance(cand, str) else (cand.get("text") or cand.get("title") or "")
            fp = textsim.fingerprint(text)
            cid = cand.get("candidate_id") if isinstance(cand, dict) else None
            if (cid and cid in ancestry) or fp in seen:
                results.append({"candidate_id": cid or fp[:12], "op": "NOOP", "status": "excluded_cycle_or_duplicate", "depth": depth})
                return
            seen.add(fp)
            res = self.novel.ingest(cand, depth=depth, origin="recursive")
            res["depth"], res["candidate_id"] = depth, cid or fp[:12]
            results.append(res)
            if res["op"] not in {"ADD", "UPDATE"} or expand is None or depth >= max_depth:
                return
            try:
                kids = expand(dict(cand) if isinstance(cand, dict) else {"text": cand}) or []
            except Exception as exc:
                errors += 1
                res["expansion_error"] = type(exc).__name__
                return
            for kid in kids:
                walk(kid, depth + 1, ancestry | ({cid} if cid else set()))

        for seed in seeds:
            walk(seed, 0, set())
        counts = {}
        for r in results:
            counts[r["op"]] = counts.get(r["op"], 0) + 1
        return {"candidates": results, "summary": {"evaluated": len(results), "by_op": counts,
                                                    "expansion_errors": errors, "max_depth": max_depth,
                                                    "automatic_publish": False}}
