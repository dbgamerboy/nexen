"""Authenticated-app API adapter for read-only skill routing.

Register these endpoints inside the existing NEXEN hub. The hub's global
app_auth middleware protects every /api/ route; this module adds no second
authentication mechanism and deliberately grants no service-key bypass.
"""
from __future__ import annotations

import re
import threading
from collections import Counter
from typing import Any

from fastapi import HTTPException, Path, Query

from skill_router import SkillRouter, load_router


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:[A-Z][A-Z0-9_]*_)?(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|"
    r"refresh[_ -]?token|bot[_ -]?token|password|passwd|secret)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;<>]+)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|\d{7,12}:[A-Za-z0-9_-]{25,})\b"
)


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ""
    text = value[:limit]
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    return _SECRET_VALUE_RE.sub("[REDACTED CREDENTIAL]", text)


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item, limit=300) for item in value if isinstance(item, str)]


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Expose identity/provenance, but not local manifest paths or raw bodies."""
    provenance = candidate.get("skill_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    public_provenance = {
        "status": _safe_text(provenance.get("status"), limit=300),
        "content_sha256": _safe_text(provenance.get("content_sha256"), limit=100),
        "repositories": _safe_string_list(provenance.get("repositories")),
        "repository_urls": _safe_string_list(provenance.get("repository_urls")),
        "repository_commits": _safe_string_list(provenance.get("repository_commits")),
    }
    related = candidate.get("related_entities")
    related = related if isinstance(related, dict) else {}
    repos = []
    for repo in related.get("repos", []) if isinstance(related.get("repos"), list) else []:
        if not isinstance(repo, dict):
            continue
        repos.append({
            "kind": "repo",
            "id": _safe_text(repo.get("id"), limit=100),
            "name": _safe_text(repo.get("name"), limit=300),
            "url": _safe_text(repo.get("url"), limit=1000),
            "commit": _safe_text(repo.get("commit"), limit=100),
            "status": _safe_text(repo.get("status"), limit=300),
        })
    tools = []
    for tool in related.get("tools", []) if isinstance(related.get("tools"), list) else []:
        if not isinstance(tool, dict):
            continue
        tools.append({
            "kind": "tool",
            "id": _safe_text(tool.get("id"), limit=100),
            "name": _safe_text(tool.get("name"), limit=300),
            "status": _safe_text(tool.get("status"), limit=300),
            "credential_check_required_before_execution": True,
            "cost_check_required_before_external_use": True,
            "execution_authorized": False,
        })
    requirements = candidate.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    license_status = candidate.get("license_status")
    license_status = license_status if isinstance(license_status, dict) else {}
    public_license_status = {
        "status": _safe_text(license_status.get("status"), limit=300),
        "skill_license": license_status.get("skill_license"),
        "repo_license_labels": _safe_string_list(license_status.get("repo_license_labels")),
    }
    scope = candidate.get("review_scope")
    public_scope = None
    if isinstance(scope, dict):
        public_scope = {
            "scope": _safe_text(scope.get("scope"), limit=1000),
            "limits": _safe_string_list(scope.get("limits")),
        }
    return {
        "kind": "skill",
        "skill_id": _safe_text(candidate.get("skill_id"), limit=100),
        "name": _safe_text(candidate.get("name"), limit=300),
        "description": _safe_text(candidate.get("description"), limit=1000),
        "score": candidate.get("score") if isinstance(candidate.get("score"), int) else 0,
        "match_kind": _safe_text(candidate.get("match_kind"), limit=100),
        "route_status": "suggestion_only",
        "review_status": _safe_text(candidate.get("review_status"), limit=100),
        "review_scope": public_scope,
        "skill_provenance": public_provenance,
        "license_status": public_license_status,
        "availability": _safe_text(candidate.get("availability"), limit=300),
        "requirements": {
            "manual_review_required": bool(requirements.get("manual_review_required", True)),
            "credential_check_required_before_execution": True,
            "cost_check_required_before_external_or_paid_use": True,
            "license_check_required_before_install_or_redistribution": True,
            "availability_check_required_before_use": True,
            "budget_constraint": "Paid actions require exact MARVIN approval; this router grants no paid or external-action approval.",
            "source_method_evidence_required": True,
            "installation_authorized": False,
            "execution_authorized": False,
            "publishing_or_external_action_authorized": False,
        },
        "related_entities": {"repos": repos, "tools": tools},
        "evidence_limit": "Catalog metadata is a discovery hint, not evidence that this skill fits or is safe for the source method.",
        "execution_allowed": False,
    }


class _RouterHolder:
    """Lazily load the local catalog once, without making registration fail."""

    def __init__(self, router: SkillRouter | None):
        self.router = router
        self.lock = threading.Lock()

    def get(self) -> SkillRouter:
        if self.router is not None:
            return self.router
        with self.lock:
            if self.router is None:
                try:
                    self.router = load_router()
                except (OSError, ValueError, RuntimeError):
                    raise HTTPException(
                        status_code=503,
                        detail="The local skill catalog or source ledger is unavailable.",
                    ) from None
        return self.router


def _status_response(router: SkillRouter) -> dict[str, Any]:
    receipt = router.receipt()
    classifications = Counter(method.classification for method in router.source_methods)
    skills = router.skills
    scopes = [
        {"skill_id": skill.id, "name": skill.name, "scope": skill.review_scope.get("scope")}
        for skill in skills
        if skill.review_status == "bounded_static_review" and isinstance(skill.review_scope, dict)
    ]
    source_ids = [int(method.source_id) for method in router.source_methods]
    actionable = classifications.get("actionable_method", 0)
    partial = classifications.get("partial_method", 0)
    held = classifications.get("needs_visual_review", 0) + classifications.get("insufficient_method", 0)
    no_route = len(source_ids) - actionable - partial - held
    return {
        "status": "ready",
        "local_only": True,
        "read_only": True,
        "catalog": {
            "sha256": receipt.get("catalog_sha256"),
            "skill_count": receipt.get("skill_count", 0),
            "repo_reference_count": receipt.get("repo_reference_count", 0),
            "tool_declaration_count": receipt.get("tool_declaration_count", 0),
        },
        "source_ledger": {
            "sha256": receipt.get("source_ledger_sha256"),
            "method_count": len(source_ids),
            "minimum_source_id": min(source_ids) if source_ids else None,
            "maximum_source_id": max(source_ids) if source_ids else None,
        },
        "route_counts": {
            "actionable_suggestions": actionable,
            "partial_method_suggestions_require_source_review": partial,
            "held_for_source_evidence": held,
            "no_automation_route": no_route,
        },
        "review_scopes": scopes,
        "excluded_skill_count": sum(skill.review_status == "excluded" for skill in skills),
        "suggestion_only": True,
        "execution_allowed": False,
        "publishing_or_external_action_authorized": False,
    }


def search_response(router: SkillRouter, query: str, *, limit: int = 10) -> dict[str, Any]:
    """Return bounded skill metadata without exposing source paths or instructions."""
    if not isinstance(query, str):
        raise ValueError("Search query must be text.")
    query = query.strip()
    if not query or len(query) > 200:
        raise ValueError("Search query must contain 1 to 200 characters.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("Search limit must be from 1 to 20.")

    results = []
    for item in router.search(query, kinds=["skill"], limit=limit):
        if item.get("kind") != "skill":
            continue
        public = _public_candidate({
            "kind": "skill",
            "skill_id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "score": None,
            "match_kind": "metadata_search",
            "review_status": item.get("review_status"),
            "review_scope": item.get("review_scope"),
            "skill_provenance": item.get("provenance"),
            "license_status": item.get("license_status"),
            "availability": item.get("availability"),
            "requirements": item.get("requirements"),
            "related_entities": {},
        })
        public.pop("score", None)
        public["task_ids"] = [
            value for value in item.get("task_ids", [])
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        ]
        results.append(public)

    receipt = router.receipt()
    return {
        "status": "ready",
        "query": _safe_text(query, limit=200),
        "result_count": len(results),
        "results": results,
        "catalog_sha256": receipt.get("catalog_sha256"),
        "suggestion_only": True,
        "execution_allowed": False,
        "publishing_or_external_action_authorized": False,
    }


def source_response(router: SkillRouter, source_id: int, *, limit: int = 5) -> dict[str, Any]:
    """Build the safe public response used by both the API and local CLI."""
    if not isinstance(source_id, int) or isinstance(source_id, bool) or not 1 <= source_id <= 1_000_000:
        raise ValueError("Source ID must be a positive integer.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError("Candidate limit must be from 1 to 10.")
    route = router.route_source(source_id, limit=limit)
    return {
        "status": "ready",
        "local_only": True,
        "source": {
            "kind": "source_method",
            "id": route["source_method_id"],
            "source_id": route["source_id"],
            "shortcode": _safe_text(route.get("shortcode"), limit=100),
            "method": _safe_text(route.get("method")),
            "classification": _safe_text(route.get("classification"), limit=100),
            "evidence_status": _safe_text(route.get("evidence_status"), limit=500),
            "exact_next_piece": _safe_text(route.get("exact_next_piece")),
        },
        "route_state": _safe_text(route.get("route_state"), limit=100),
        "hold_reason": _safe_text(route.get("hold_reason"), limit=1000),
        "requirements": route.get("requirements", {}),
        "candidate_count": len(route.get("candidates", [])),
        "candidates": [_public_candidate(item) for item in route.get("candidates", [])],
        "provenance": {
            "catalog_sha256": route.get("provenance", {}).get("catalog_sha256"),
            "source_ledger_sha256": route.get("provenance", {}).get("source_ledger_sha256"),
            "source_row_id": route.get("provenance", {}).get("source_row_id"),
            "basis": "Local source-ledger summary and catalog metadata only; no source file body is returned.",
        },
        "suggestion_only": True,
        "execution_allowed": False,
    }


def register(app, *, router: SkillRouter | None = None) -> None:
    """Register read-only skill catalog endpoints on the authenticated NEXEN app.

    The NEXEN hub must register this module inside its normal startup path,
    where the existing app_auth middleware protects the /api/ namespace.
    """
    holder = _RouterHolder(router)

    @app.get("/api/workflow-skills/status")
    def workflow_skill_status():
        return _status_response(holder.get())

    @app.get("/api/workflow-skills/search")
    def workflow_skill_search(
        q: str = Query(..., min_length=1, max_length=200),
        limit: int = Query(10, ge=1, le=20),
    ):
        try:
            return search_response(holder.get(), q, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @app.get("/api/workflow-skills/source/{source_id}")
    def workflow_skill_source(
        source_id: int = Path(..., ge=1, le=1_000_000),
        limit: int = Query(5, ge=1, le=10),
    ):
        loaded = holder.get()
        try:
            return source_response(loaded, source_id, limit=limit)
        except KeyError:
            raise HTTPException(status_code=404, detail="Source ID was not found in the local ledger.") from None

