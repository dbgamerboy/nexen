"""Bounded, evidence-first recursive learning companion.

The Novel Learning scope is supplied at the interface; this module does not
assume its responsibilities or replace it. It evaluates already surfaced,
source-linked candidates and follow-ups. It never writes to the knowledge
index: an eligible result is only a proposal for owner review.
"""
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import unicodedata


VERSION = 1
MAX_RECURSION_DEPTH = 3
MAX_CANDIDATES = 50
MAX_TEXT_CHARS = 12000
MAX_SOURCE_IDS = 50

# Do not infer Novel Learning's scope from its name. Its current scope terms or
# reference items must be supplied; otherwise candidate eligibility fails closed.
DEFAULT_NOVEL_LEARNING_SCOPE = ()

_NOVEL_OWNERS = {"novel_learning", "novelty_learning"}
_FEEDBACK_DECISIONS = {"approve", "exclude"}
_FEEDBACK_REASONS = {
    "owner_approved", "novel_overlap", "duplicate", "conflict",
    "insufficient_provenance", "other",
}
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def normalize_text(value):
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().replace("_", " ").replace("-", " ")
    return " ".join(_TOKEN_RE.findall(text))


def candidate_fingerprint(value):
    """Stable content identity; raw candidate text is never stored in feedback."""
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def _tokens(value):
    return set(normalize_text(value).split())


def _similarity(left, right):
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _as_text(item):
    if isinstance(item, str):
        return item[:MAX_TEXT_CHARS]
    if not isinstance(item, Mapping):
        return ""
    values = [item.get(key) for key in ("title", "topic", "text", "summary")]
    return " ".join(value for value in values if isinstance(value, str))[:MAX_TEXT_CHARS]


def _source_ids(candidate):
    values = candidate.get("source_ids", [])
    if not isinstance(values, (list, tuple)):
        values = []
    result = []
    for value in values[:MAX_SOURCE_IDS]:
        if isinstance(value, str) and value.strip():
            cleaned = value.strip()[:300]
            if cleaned not in result:
                result.append(cleaned)
    sources = candidate.get("sources", [])
    if isinstance(sources, (list, tuple)):
        for source in sources[:MAX_SOURCE_IDS]:
            if isinstance(source, Mapping):
                ident = source.get("source_id") or source.get("id")
                if isinstance(ident, str) and ident.strip() and ident.strip() not in result:
                    result.append(ident.strip()[:300])
    return result[:MAX_SOURCE_IDS]


def _mentions(text, terms):
    normalized = normalize_text(text)
    for term in terms:
        phrase = normalize_text(term)
        if phrase and (" " + phrase + " ") in (" " + normalized + " "):
            return term
    return None


def _owner_is_novel(candidate):
    for key in ("owner", "module", "system", "lane"):
        value = candidate.get(key)
        if isinstance(value, str):
            label = normalize_text(value).replace(" ", "_")
            if label in _NOVEL_OWNERS:
                return True
    return False


def _feedback_for(feedback, fingerprint):
    if not isinstance(feedback, Mapping):
        return None
    item = feedback.get(fingerprint)
    if not isinstance(item, Mapping):
        return None
    decision = item.get("decision")
    return dict(item) if decision in _FEEDBACK_DECISIONS else None


def _result(candidate_id, fingerprint, status, can_add, reason, **extra):
    return {
        "candidate_id": candidate_id,
        "fingerprint": fingerprint,
        "status": status,
        "can_add": can_add,
        "reason": reason,
        "requires_human_review": True,
        "auto_ingested": False,
        **extra,
    }


def evaluate_candidate(candidate, *, existing_items=(), novel_learning_items=(),
                       novel_learning_scope=None, scope_configured=None,
                       feedback=None, prior_run_fingerprints=()):
    """Assess one candidate without mutating memory or executing candidate text.

    ``can_add=True`` means only that the candidate can enter a human review
    queue. The authoritative memory index is never written here.
    """
    if not isinstance(candidate, Mapping):
        return _result("", "", "needs_review_invalid_candidate", None,
                       "Candidate must be an object with text and provenance.")
    text = _as_text(candidate)
    fingerprint = candidate_fingerprint(text)
    candidate_id = candidate.get("candidate_id")
    candidate_id = candidate_id.strip()[:100] if isinstance(candidate_id, str) else ""
    if not candidate_id:
        candidate_id = "candidate-" + fingerprint[:16]
    if not normalize_text(text):
        return _result(candidate_id, fingerprint, "needs_review_empty", None,
                       "Candidate text is empty after normalization.")

    details = " ".join([text] + [str(candidate.get(key, "")) for key in ("topic", "tags")])
    if _owner_is_novel(candidate):
        return _result(candidate_id, fingerprint, "excluded_novel_overlap", False,
                       "Candidate declares Novel Learning as its owner/module.")

    scope_terms = list(DEFAULT_NOVEL_LEARNING_SCOPE)
    if isinstance(novel_learning_scope, (list, tuple, set)):
        scope_terms.extend(term for term in novel_learning_scope if isinstance(term, str))
    overlap_term = _mentions(details, scope_terms)
    if overlap_term:
        return _result(candidate_id, fingerprint, "excluded_novel_overlap", False,
                       "Candidate matches a Novel Learning scope term.",
                       matched_scope_term=overlap_term)

    novel_matches = []
    for item in novel_learning_items if isinstance(novel_learning_items, (list, tuple)) else ():
        reference_text = _as_text(item)
        score = _similarity(text, reference_text)
        source_id = item.get("source_id") if isinstance(item, Mapping) else None
        if not isinstance(source_id, str) and isinstance(item, Mapping):
            source_id = item.get("id")
        if score >= 0.25:
            return _result(candidate_id, fingerprint, "excluded_novel_overlap", False,
                           "Lexical overlap with a Novel Learning reference; excluded conservatively.",
                           overlap_score=round(score, 3),
                           related_source_ids=[source_id] if isinstance(source_id, str) else [])
        if score >= 0.12:
            novel_matches.append((score, source_id))
    if novel_matches:
        score, source_id = max(novel_matches, key=lambda match: match[0])
        return _result(candidate_id, fingerprint, "needs_review_novel_overlap", None,
                       "Possible overlap with Novel Learning; hold for an owner decision.",
                       overlap_score=round(score, 3),
                       related_source_ids=[source_id] if isinstance(source_id, str) else [])

    existing = list(existing_items) if isinstance(existing_items, (list, tuple)) else []
    exact_matches = []
    similar_matches = []
    for item in existing:
        item_text = _as_text(item)
        if not item_text:
            continue
        source_id = item.get("source_id") if isinstance(item, Mapping) else None
        if normalize_text(text) == normalize_text(item_text):
            if isinstance(source_id, str):
                exact_matches.append(source_id)
            else:
                exact_matches.append("existing-memory")
        else:
            score = _similarity(text, item_text)
            if score >= 0.62:
                similar_matches.append((score, source_id))
    if exact_matches:
        return _result(candidate_id, fingerprint, "excluded_duplicate", False,
                       "Exact match already exists in indexed memory.",
                       related_source_ids=list(dict.fromkeys(exact_matches)))
    if fingerprint in set(prior_run_fingerprints):
        return _result(candidate_id, fingerprint, "excluded_duplicate", False,
                       "Same candidate was already evaluated in this recursive run.")
    if similar_matches:
        score, source_id = max(similar_matches, key=lambda match: match[0])
        return _result(candidate_id, fingerprint, "needs_review_similarity", None,
                       "Possible duplicate or contradiction; hold for owner review.",
                       overlap_score=round(score, 3),
                       related_source_ids=[source_id] if isinstance(source_id, str) else [])

    sources = _source_ids(candidate)
    if not sources:
        return _result(candidate_id, fingerprint, "needs_review_provenance", None,
                       "No source IDs were supplied; an ungrounded candidate cannot be added.")

    declared_scope = any(normalize_text(term) for term in scope_terms)
    scoped_references = any(
        normalize_text(_as_text(item)) and isinstance(item, Mapping)
        and isinstance(item.get("source_id") or item.get("id"), str)
        and bool((item.get("source_id") or item.get("id")).strip())
        for item in (novel_learning_items if isinstance(novel_learning_items, (list, tuple)) else ())
    )
    scope_has_evidence = declared_scope or scoped_references
    if scope_configured is None:
        scope_configured = scope_has_evidence
    else:
        scope_configured = bool(scope_configured) and scope_has_evidence
    if not scope_configured:
        return _result(candidate_id, fingerprint, "needs_review_scope", None,
                       "The current Novel Learning scope is not connected; possible overlap cannot be ruled out.",
                       source_ids=sources)

    prior = _feedback_for(feedback, fingerprint)
    if prior and prior["decision"] == "exclude":
        return _result(candidate_id, fingerprint, "excluded_by_owner_feedback", False,
                       "The owner previously excluded this exact candidate.",
                       feedback_reason=prior.get("reason_code", "other"), source_ids=sources)
    if prior and prior["decision"] == "approve":
        return _result(candidate_id, fingerprint, "approved_for_staging", True,
                       "Owner previously approved this exact candidate for staging.",
                       feedback_reason=prior.get("reason_code", "owner_approved"), source_ids=sources)
    return _result(candidate_id, fingerprint, "proposal_ready", True,
                   "Evidence and configured scope checks passed; owner approval is still required.",
                   source_ids=sources)


def run_recursive_learning(seeds, *, expand=None, existing_items=(),
                           novel_learning_items=(), novel_learning_scope=None,
                           scope_configured=None, feedback=None, max_depth=MAX_RECURSION_DEPTH,
                           max_candidates=MAX_CANDIDATES):
    """Recursively assess a bounded candidate tree supplied by an adapter.

    The ``expand`` callback may return follow-up candidates, but it is called
    only for candidates eligible for owner review. Exceptions are reported by
    type and stop that branch; no retries or external calls are made here.
    """
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 0 <= max_depth <= MAX_RECURSION_DEPTH:
        raise ValueError("max_depth must be between 0 and 3")
    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or not 1 <= max_candidates <= MAX_CANDIDATES:
        raise ValueError("max_candidates must be between 1 and 50")
    if not isinstance(seeds, (list, tuple)):
        raise ValueError("seeds must be a list or tuple")

    results = []
    seen_fingerprints = set()
    truncated = False
    expansion_errors = 0

    def walk(candidate, depth, ancestry):
        nonlocal truncated, expansion_errors
        if len(results) >= max_candidates:
            truncated = True
            return
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, Mapping) else None
        candidate_id = candidate_id.strip()[:100] if isinstance(candidate_id, str) else ""
        if candidate_id and candidate_id in ancestry:
            fingerprint = candidate_fingerprint(_as_text(candidate))
            results.append(_result(candidate_id, fingerprint, "needs_review_cycle", None,
                                   "Recursive expansion returned an ancestor candidate; branch stopped.", depth=depth))
            return
        text = _as_text(candidate)
        fingerprint = candidate_fingerprint(text)
        if fingerprint in seen_fingerprints:
            results.append(_result(candidate_id or "candidate-" + fingerprint[:16], fingerprint,
                                   "excluded_duplicate", False,
                                   "Same candidate was already assessed in this recursive run.", depth=depth))
            return
        seen_fingerprints.add(fingerprint)
        item = evaluate_candidate(
            candidate,
            existing_items=existing_items,
            novel_learning_items=novel_learning_items,
            novel_learning_scope=novel_learning_scope,
            scope_configured=scope_configured,
            feedback=feedback,
            prior_run_fingerprints=(),
        )
        item["depth"] = depth
        results.append(item)
        if not item["can_add"] or expand is None or depth >= max_depth:
            return
        try:
            children = expand(dict(candidate)) if callable(expand) else []
        except Exception as exc:
            expansion_errors += 1
            item["expansion_error"] = type(exc).__name__
            return
        if children is None:
            return
        if not isinstance(children, (list, tuple)):
            expansion_errors += 1
            item["expansion_error"] = "InvalidExpansionResult"
            return
        next_ancestry = ancestry | ({candidate_id} if candidate_id else set())
        for child in children:
            if len(results) >= max_candidates:
                truncated = True
                break
            walk(child, depth + 1, next_ancestry)

    for seed in seeds:
        if len(results) >= max_candidates:
            truncated = True
            break
        walk(seed, 0, set())

    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "version": VERSION,
        "candidates": results,
        "summary": {
            "evaluated": len(results),
            "by_status": counts,
            "truncated": truncated,
            "max_depth": max_depth,
            "max_candidates": max_candidates,
            "expansion_errors": expansion_errors,
            "automatic_ingestion": False,
        },
    }


def _database_uri(database, mode):
    path = Path(database)
    if mode == "rw" and not path.is_file():
        raise FileNotFoundError("The existing NEXEN task database is required for feedback storage.")
    return path.resolve().as_uri() + "?mode=" + mode


def _ensure_feedback_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS recursive_learning_feedback(
        id INTEGER PRIMARY KEY,
        candidate_fingerprint TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('approve','exclude')),
        reason_code TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE INDEX IF NOT EXISTS idx_recursive_learning_feedback_latest
        ON recursive_learning_feedback(candidate_fingerprint,id DESC)""")


def record_feedback(database, candidate_text, decision, *, reason_code="other"):
    """Persist owner feedback only; stores hashes and IDs, never candidate text."""
    if decision not in _FEEDBACK_DECISIONS:
        raise ValueError("decision must be approve or exclude")
    if reason_code not in _FEEDBACK_REASONS:
        raise ValueError("unsupported reason_code")
    text = candidate_text[:MAX_TEXT_CHARS] if isinstance(candidate_text, str) else ""
    if not normalize_text(text):
        raise ValueError("candidate_text is required")
    created_at = datetime.now(timezone.utc).isoformat()
    fingerprint = candidate_fingerprint(text)
    uri = _database_uri(database, "rw")
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        with connection:
            _ensure_feedback_schema(connection)
            connection.execute(
                "INSERT INTO recursive_learning_feedback(candidate_fingerprint,decision,reason_code,created_at) VALUES(?,?,?,?)",
                (fingerprint, decision, reason_code, created_at),
            )
    return {"fingerprint": fingerprint, "decision": decision, "reason_code": reason_code,
            "created_at": created_at,
            "candidate_text_stored": False, "knowledge_written": False}


def load_feedback(database):
    """Read latest owner feedback by fingerprint; a missing table is an empty ledger."""
    path = Path(database)
    if not path.is_file():
        return {}
    uri = _database_uri(path, "ro")
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recursive_learning_feedback'"
            ).fetchone()
            if not exists:
                return {}
            rows = connection.execute("""SELECT f.candidate_fingerprint,f.decision,f.reason_code,
                f.created_at FROM recursive_learning_feedback f
                JOIN (SELECT candidate_fingerprint,MAX(id) id FROM recursive_learning_feedback
                GROUP BY candidate_fingerprint) latest ON latest.id=f.id""").fetchall()
    except sqlite3.Error:
        return {}
    result = {}
    for row in rows:
        result[row["candidate_fingerprint"]] = {
            "decision": row["decision"], "reason_code": row["reason_code"],
            "created_at": row["created_at"],
        }
    return result
