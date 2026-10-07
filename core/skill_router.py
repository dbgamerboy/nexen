"""Read-only, provenance-first routing for catalogued skills and source methods.

The router reads the local H: catalog and 82-source ledger as data. It never
imports or executes a skill, repository, tool declaration, or source method.
All matches are suggestions; no result authorizes installation, credentials,
spending, workflow changes, publication, or other external actions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


DEFAULT_CATALOG_PATH = Path(
    r"H:\NEXEN\handoffs\SKILLS-700-CATALOG-AND-ROUTING-20260927.json"
)
DEFAULT_SOURCE_LEDGER_PATH = Path(
    r"H:\NEXEN\recovery\source-82-matrix-20260927\SOURCE-82-MATRIX.csv"
)
DEFAULT_REVIEW_MANIFEST_ROOT = Path(r"H:\NEXEN\arsenal\repos")

EntityKind = Literal["skill", "repo", "tool", "source_method"]
_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_TOKEN_RE = re.compile(r"[\w-]{2,60}", re.UNICODE)
_SECRET_TOKEN_RE = re.compile(
    r"(?i)\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|\d{7,12}:[A-Za-z0-9_-]{25,})\b"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:[A-Z][A-Z0-9_]*_)?(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|"
    r"refresh[_ -]?token|bot[_ -]?token|password|passwd|secret)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;<>]+)"
)
_PLACEHOLDERS = {
    "", "[]", "none", "null", "n/a", "na", "unknown",
    "not specified", "not specified in frontmatter",
}
_STOPWORDS = {
    "the", "and", "for", "from", "with", "into", "using", "use", "via",
    "to", "of", "on", "a", "an", "in", "by", "at", "or", "is", "are",
    "this", "that", "method", "source", "skill", "tool", "workflow",
}

# This is the explicit review allowlist. A matching title or metadata label is
# insufficient: the exact SHA, repository, pinned commit, path and bytes must
# all agree before a scope is exposed as bounded static review.
_REVIEWED_SCOPES: dict[str, dict[str, Any]] = {
    "sha256:a1ccc0ecfe30ae53db26a73159a80ecad8c63a6a96c461a297789d889bf9ad2c": {
        "title": "content-engine",
        "repository": "affaan-m__everything-claude-code",
        "commit": "e482e579415fde18357cafce70f177ae19fd7f03",
        "path_suffix": ("affaan-m__everything-claude-code", "skills", "content-engine", "SKILL.md"),
        "scope": "NEXEN task 139 only: source-informed adaptation drafts after the source-faithful method is recorded separately.",
        "limits": ["No installation or skill execution.", "No publishing, cross-posting, outreach, or account mutation."],
    },
    "sha256:e7fb390a6663b46ea5d3c2876753a5ce32ba3bad1889686b21a42894caa1742d": {
        "title": "agent-harness-construction",
        "repository": "affaan-m__everything-claude-code",
        "commit": "e482e579415fde18357cafce70f177ae19fd7f03",
        "path_suffix": ("affaan-m__everything-claude-code", "skills", "agent-harness-construction", "SKILL.md"),
        "scope": "NEXEN task 19 only: advisory packet and tool-schema design, delivered by manual sanitized handoff.",
        "limits": ["No installation or skill execution.", "No new model/tool connections, automated agent dispatch, spending, or PC2 access."],
    },
}

_EXCLUDED_SKILL_IDS = {
    "sha256:6b3dab0674b5bef015c1965f19e3bf4f376e909ddec7b67ae2dfe10565c3a4c5": (
        "Reviewed candidate requires an ElevenLabs credential and conflicts with the no-secret, $0 and approval rules."
    ),
    "sha256:b4f2c57906b77b5abac19c89eef77d616ca4d9852a411feee2af33cfa8631fa0": (
        "Reviewed candidate requires installation and an n8n API key and can mutate workflows and credentials."
    ),
    "sha256:18ba79e8edb1eb8f95856ba1c1971e612e02d86caf9739a9f2f9ef94756f2dd2": (
        "Unreviewed sibling of a workflow-mutating n8n CLI; excluded from routing."
    ),
    "sha256:240ed1929230c94d842166f9680ae71043f6b2c06ebd1cb002e2a103e34fe5d6": (
        "Reviewed candidate requires installation and supports model pull/removal and remote-host selection."
    ),
}
_EXCLUDED_TITLES = {
    "video-use": "This title is excluded because the reviewed copy conflicts with the current credential and approval rules.",
    "cli-anything-n8n": "This title is excluded from live routing because its reviewed copy can mutate workflows and credentials; sibling variants remain unreviewed.",
    "cli-anything-ollama": "This title is excluded from PC2 routing because its reviewed copy can change models and remote-host selection.",
}

_LEDGER_FIELDS = {
    "source_id", "shortcode", "method", "classification", "evidence_status",
    "evidence_artifact_exists", "visual_review_required", "valid_export_count",
    "source_faithful_export_present", "nexen_adaptation_export_present",
    "primary_state", "installed_names", "staged_only_names", "exported_only_names",
    "exact_next_piece", "account_or_rights_gates",
}
_ACTIONABLE_CLASSIFICATIONS = {"actionable_method", "partial_method"}
_HELD_CLASSIFICATIONS = {"needs_visual_review", "insufficient_method"}
_MIN_METADATA_MATCH_SCORE = 2


class CatalogFormatError(ValueError):
    """The local catalog or source ledger does not match its expected shape."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"The configured {label} is unavailable")
    size = path.stat().st_size
    if size > max_bytes:
        raise CatalogFormatError(f"The configured {label} exceeds the size limit")
    content = path.read_bytes()
    if len(content) > max_bytes:
        raise CatalogFormatError(f"The configured {label} exceeds the size limit")
    return content


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_source_text(value: Any) -> str:
    """Keep source wording useful while suppressing credential-shaped values."""
    text = _text(value)[:4000]
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    return _SECRET_TOKEN_RE.sub("[REDACTED CREDENTIAL]", text)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        token for token in (item.casefold() for item in _TOKEN_RE.findall(value[:12000]))
        if token not in _STOPWORDS
    ))


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _tool_declarations(skill: dict[str, Any]) -> list[str]:
    deps = skill.get("dependencies_tools_model_interface")
    if not isinstance(deps, dict):
        return []
    declarations = _as_string_list(deps.get("tools"))
    return [item for item in declarations if item.casefold() not in _PLACEHOLDERS]


def _task_ids(skill: dict[str, Any]) -> list[int]:
    rows = skill.get("applicable_workstream_tasks")
    if not isinstance(rows, list):
        return []
    ids: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("task_ids"), list):
            continue
        for value in row["task_ids"]:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                ids.add(value)
    return sorted(ids)


def _normalize_skill_review(
    raw: dict[str, Any], review_root: Path | None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    stable_id = _text(raw.get("stable_id"))
    name = _text(raw.get("title"))
    if stable_id in _EXCLUDED_SKILL_IDS:
        return "excluded", None, _EXCLUDED_SKILL_IDS[stable_id]
    if name.casefold() in _EXCLUDED_TITLES:
        return "excluded", None, _EXCLUDED_TITLES[name.casefold()]

    scope = _REVIEWED_SCOPES.get(stable_id)
    if scope is None:
        return "unreviewed", None, None
    if review_root is None:
        return "review_receipt_unverified", None, "The reviewed manifest root was not configured."

    identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    if identity.get("content_sha256") != stable_id.removeprefix("sha256:"):
        return "review_receipt_unverified", None, "The catalog content identity does not match the reviewed SHA-256."

    source = raw.get("source_provenance") if isinstance(raw.get("source_provenance"), dict) else {}
    repos = _as_string_list(source.get("repos"))
    commits = _as_string_list(source.get("repository_commits"))
    paths = _as_string_list(source.get("paths"))
    if scope["repository"] not in repos or scope["commit"] not in commits:
        return "review_receipt_unverified", None, "The repository or pinned commit differs from the reviewed receipt."
    if not paths:
        return "review_receipt_unverified", None, "The reviewed manifest path is missing from the catalog."

    try:
        root = Path(review_root).resolve(strict=True)
        matched = False
        for raw_path in paths:
            manifest = Path(raw_path).resolve(strict=True)
            relative = manifest.relative_to(root)
            parts = tuple(part.casefold() for part in relative.parts)
            suffix = tuple(part.casefold() for part in scope["path_suffix"])
            if len(parts) < len(suffix) or parts[-len(suffix):] != suffix:
                continue
            if manifest.name.casefold() != "skill.md":
                continue
            content = _read_bounded(manifest, 512 * 1024, "reviewed skill manifest")
            if _sha256(content) == stable_id.removeprefix("sha256:"):
                matched = True
                break
    except (OSError, ValueError, RuntimeError):
        matched = False
    if not matched:
        return "review_receipt_unverified", None, "The exact reviewed manifest bytes are unavailable or no longer match."
    return "bounded_static_review", dict(scope), None


def _requirements(raw: dict[str, Any], review_status: str) -> dict[str, Any]:
    risks = raw.get("risk_approval_constraints")
    risks = risks if isinstance(risks, dict) else {}
    dependency_info = raw.get("dependencies_tools_model_interface")
    dependency_info = dependency_info if isinstance(dependency_info, dict) else {}
    deps = dependency_info.get("dependencies", "unknown")
    tools = dependency_info.get("tools", "unknown")
    unknown = any(
        not isinstance(value, list) and str(value).strip().casefold() in _PLACEHOLDERS
        for value in (deps, tools)
    )
    declared = bool(_tool_declarations(raw)) or (
        isinstance(deps, list) and any(isinstance(item, str) and item.strip() for item in deps)
    )
    paid_status = risks.get("paid_service_status", "unknown")
    return {
        "credential_status": "unknown" if unknown else ("declared capability; verify before use" if declared else "none declared; not verified"),
        "credential_check_required_before_execution": True,
        "cost_status": str(paid_status),
        "cost_check_required_before_external_or_paid_use": True,
        "budget_constraint": "Paid actions require exact MARVIN approval; this router grants no paid or external-action approval.",
        "license_check_required_before_install_or_redistribution": True,
        "availability_check_required_before_use": True,
        "manual_review_required": review_status != "bounded_static_review",
        "source_method_evidence_required": True,
        "installation_authorized": False,
        "execution_authorized": False,
        "publishing_or_external_action_authorized": False,
    }


@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str
    description: str
    review_status: str
    review_scope: dict[str, Any] | None
    exclusion_reason: str | None
    provenance: dict[str, Any]
    license_status: dict[str, Any]
    availability: str
    task_ids: tuple[int, ...]
    requirements: dict[str, Any]
    repo_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    searchable_text: str

    kind: Literal["skill"] = "skill"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "name": self.name,
            "description": self.description, "review_status": self.review_status,
            "review_scope": self.review_scope, "exclusion_reason": self.exclusion_reason,
            "provenance": self.provenance, "license_status": self.license_status,
            "availability": self.availability, "task_ids": list(self.task_ids),
            "requirements": self.requirements, "repo_ids": list(self.repo_ids),
            "tool_ids": list(self.tool_ids),
        }


@dataclass(frozen=True)
class RepoRecord:
    id: str
    name: str
    url: str | None
    commit: str | None
    source_skill_ids: tuple[str, ...]

    kind: Literal["repo"] = "repo"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "name": self.name,
            "url": self.url, "commit": self.commit,
            "source_skill_ids": list(self.source_skill_ids),
            "status": "metadata reference only; repository code is not executed",
            "execution_authorized": False,
        }


@dataclass(frozen=True)
class ToolRecord:
    id: str
    name: str
    source_skill_ids: tuple[str, ...]

    kind: Literal["tool"] = "tool"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "name": self.name,
            "source_skill_ids": list(self.source_skill_ids),
            "status": "declared capability reference only; availability and credentials are unverified",
            "credential_check_required_before_execution": True,
            "cost_check_required_before_external_use": True,
            "budget_constraint": "Paid actions require exact MARVIN approval; this router grants no paid or external-action approval.",
            "execution_authorized": False,
        }


@dataclass(frozen=True)
class SourceMethodRecord:
    id: str
    source_id: str
    shortcode: str
    method: str
    classification: str
    evidence_status: str
    exact_next_piece: str
    account_or_rights_gates: str
    fields: dict[str, str]

    kind: Literal["source_method"] = "source_method"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "source_id": self.source_id,
            "shortcode": self.shortcode, "method": self.method,
            "classification": self.classification, "evidence_status": self.evidence_status,
            "exact_next_piece": self.exact_next_piece,
            "account_or_rights_gates": self.account_or_rights_gates,
            "provenance": dict(self.fields),
        }


class SkillRouter:
    """A read-only router over one skill catalog and one source-method ledger."""

    def __init__(
        self,
        catalog_path: Path | str = DEFAULT_CATALOG_PATH,
        source_ledger_path: Path | str = DEFAULT_SOURCE_LEDGER_PATH,
        *,
        review_manifest_root: Path | str | None = DEFAULT_REVIEW_MANIFEST_ROOT,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.source_ledger_path = Path(source_ledger_path)
        self.review_manifest_root = Path(review_manifest_root) if review_manifest_root is not None else None
        catalog_bytes = _read_bounded(self.catalog_path, 64 * 1024 * 1024, "skill catalog")
        ledger_bytes = _read_bounded(self.source_ledger_path, 8 * 1024 * 1024, "source ledger")
        try:
            catalog = json.loads(catalog_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CatalogFormatError("The skill catalog is not valid UTF-8 JSON") from error
        if not isinstance(catalog, dict) or not isinstance(catalog.get("records"), list):
            raise CatalogFormatError("The skill catalog does not contain a records list")
        self.catalog = catalog
        self.catalog_sha256 = _sha256(catalog_bytes)
        self.source_ledger_sha256 = _sha256(ledger_bytes)
        self.skills = self._load_skills(catalog["records"])
        self.source_methods = self._load_source_methods(ledger_bytes)
        self.repos, self.tools = self._load_related_entities(catalog["records"])
        self._skill_by_id = {item.id: item for item in self.skills}
        self._repo_by_id = {item.id: item for item in self.repos}
        self._tool_by_id = {item.id: item for item in self.tools}
        self._method_by_source_id = {item.source_id: item for item in self.source_methods}

    def _load_skills(self, rows: list[Any]) -> tuple[SkillRecord, ...]:
        result: list[SkillRecord] = []
        seen: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise CatalogFormatError("A skill catalog record is not an object")
            ident = _text(raw.get("stable_id"))
            if not _ID_RE.fullmatch(ident):
                raise CatalogFormatError("A skill record is missing its exact SHA-256 ID")
            if ident in seen:
                raise CatalogFormatError("The deduplicated skill catalog contains a repeated stable ID")
            seen.add(ident)
            title = _text(raw.get("title"))
            if not title:
                raise CatalogFormatError("A skill record has no title")
            review_status, scope, exclusion = _normalize_skill_review(raw, self.review_manifest_root)
            provenance = raw.get("source_provenance") if isinstance(raw.get("source_provenance"), dict) else {}
            license_info = raw.get("license_provenance_status") if isinstance(raw.get("license_provenance_status"), dict) else {}
            source_paths = _as_string_list(provenance.get("paths"))
            if not source_paths:
                source_paths = [
                    _text(copy.get("path")) for copy in raw.get("source_copies", [])
                    if isinstance(copy, dict) and _text(copy.get("path"))
                ]
            repo_ids = self._repo_ids_for_skill(raw)
            tool_ids = tuple(
                self._tool_id(name) for name in _tool_declarations(raw)
            )
            description = _text(raw.get("description_purpose"))
            aliases = _as_string_list(raw.get("title_aliases"))
            searchable = " ".join([title, *aliases, description, *source_paths, *_as_string_list(provenance.get("repos"))])
            result.append(SkillRecord(
                id=ident,
                name=title,
                description=description,
                review_status=review_status,
                review_scope=scope,
                exclusion_reason=exclusion,
                provenance={
                    "status": _text(provenance.get("status")) or "unknown",
                    "repositories": _as_string_list(provenance.get("repos")),
                    "repository_urls": _as_string_list(provenance.get("repository_urls")),
                    "repository_commits": _as_string_list(provenance.get("repository_commits")),
                    "paths": source_paths,
                    "content_sha256": ident.removeprefix("sha256:"),
                },
                license_status=dict(license_info),
                availability=_text(raw.get("availability_status")) or "unknown",
                task_ids=tuple(_task_ids(raw)),
                requirements=_requirements(raw, review_status),
                repo_ids=repo_ids,
                tool_ids=tool_ids,
                searchable_text=searchable,
            ))
        return tuple(result)

    def _repo_ids_for_skill(self, raw: dict[str, Any]) -> tuple[str, ...]:
        provenance = raw.get("source_provenance") if isinstance(raw.get("source_provenance"), dict) else {}
        names = _as_string_list(provenance.get("repos"))
        urls = _as_string_list(provenance.get("repository_urls"))
        commits = _as_string_list(provenance.get("repository_commits"))
        ids = []
        for index, name in enumerate(names):
            url = urls[index] if index < len(urls) else None
            commit = commits[index] if index < len(commits) else None
            ids.append(self._repo_id(name, url, commit))
        return tuple(ids)

    @staticmethod
    def _repo_id(name: str, url: str | None, commit: str | None) -> str:
        canonical = "\0".join(("repo", name.casefold(), (url or "").casefold(), commit or ""))
        return "sha256:" + _sha256(canonical.encode("utf-8"))

    @staticmethod
    def _tool_id(name: str) -> str:
        canonical = "\0".join(("tool-declaration", name.strip().casefold()))
        return "sha256:" + _sha256(canonical.encode("utf-8"))

    def _load_related_entities(self, rows: list[Any]) -> tuple[tuple[RepoRecord, ...], tuple[ToolRecord, ...]]:
        repos: dict[str, dict[str, Any]] = {}
        tools: dict[str, dict[str, Any]] = {}
        for raw in rows:
            if not isinstance(raw, dict) or not _ID_RE.fullmatch(_text(raw.get("stable_id"))):
                continue
            skill_id = raw["stable_id"]
            provenance = raw.get("source_provenance") if isinstance(raw.get("source_provenance"), dict) else {}
            names = _as_string_list(provenance.get("repos"))
            urls = _as_string_list(provenance.get("repository_urls"))
            commits = _as_string_list(provenance.get("repository_commits"))
            for index, name in enumerate(names):
                url = urls[index] if index < len(urls) else None
                commit = commits[index] if index < len(commits) else None
                ident = self._repo_id(name, url, commit)
                item = repos.setdefault(ident, {"name": name, "url": url, "commit": commit, "skills": set()})
                item["skills"].add(skill_id)
            for name in _tool_declarations(raw):
                ident = self._tool_id(name)
                item = tools.setdefault(ident, {"name": name, "skills": set()})
                item["skills"].add(skill_id)
        repo_records = tuple(
            RepoRecord(id=ident, name=value["name"], url=value["url"], commit=value["commit"],
                       source_skill_ids=tuple(sorted(value["skills"])))
            for ident, value in sorted(repos.items(), key=lambda pair: (pair[1]["name"].casefold(), pair[0]))
        )
        tool_records = tuple(
            ToolRecord(id=ident, name=value["name"], source_skill_ids=tuple(sorted(value["skills"])))
            for ident, value in sorted(tools.items(), key=lambda pair: (pair[1]["name"].casefold(), pair[0]))
        )
        return repo_records, tool_records

    @staticmethod
    def _load_source_methods(ledger_bytes: bytes) -> tuple[SourceMethodRecord, ...]:
        try:
            reader = csv.DictReader(io.StringIO(ledger_bytes.decode("utf-8-sig", errors="strict")))
        except UnicodeDecodeError as error:
            raise CatalogFormatError("The source ledger is not valid UTF-8") from error
        if not reader.fieldnames or not _LEDGER_FIELDS.issubset(set(reader.fieldnames)):
            raise CatalogFormatError("The source ledger is missing required columns")
        methods: list[SourceMethodRecord] = []
        seen: set[str] = set()
        for row in reader:
            if not isinstance(row, dict):
                raise CatalogFormatError("A source ledger row is malformed")
            source_id = _text(row.get("source_id"))
            if not source_id.isdecimal() or str(int(source_id)) != source_id or int(source_id) < 1:
                raise CatalogFormatError("A source ledger ID must be a canonical positive decimal ID")
            if source_id in seen:
                raise CatalogFormatError("The source ledger repeats a source_id")
            seen.add(source_id)
            method = _text(row.get("method"))
            shortcode = _text(row.get("shortcode"))
            if not method or not shortcode:
                raise CatalogFormatError("A source method requires both a method and shortcode")
            # Keep only fields needed to identify and qualify the method. In
            # particular, installation/export inventories are not copied into
            # route results. Text is scrubbed before it can reach an adapter.
            fields = {
                "source_id": source_id,
                "shortcode": _safe_source_text(row.get("shortcode")),
                "classification": _safe_source_text(row.get("classification")),
                "evidence_status": _safe_source_text(row.get("evidence_status")),
            }
            methods.append(SourceMethodRecord(
                id=f"source:{source_id}:{shortcode}",
                source_id=source_id,
                shortcode=_safe_source_text(shortcode),
                method=_safe_source_text(method),
                classification=_safe_source_text(row.get("classification")),
                evidence_status=_safe_source_text(row.get("evidence_status")),
                exact_next_piece=_safe_source_text(row.get("exact_next_piece")),
                account_or_rights_gates=_safe_source_text(row.get("account_or_rights_gates")),
                fields=fields,
            ))
        ids = [int(item.source_id) for item in methods]
        if not methods or sorted(ids) != list(range(1, len(ids) + 1)):
            raise CatalogFormatError("The source ledger IDs must form a contiguous sequence starting at 1")
        return tuple(sorted(methods, key=lambda item: int(item.source_id)))

    def receipt(self) -> dict[str, Any]:
        """Return content identity and count evidence for the loaded local inputs."""
        return {
            "catalog_path": str(self.catalog_path),
            "catalog_sha256": self.catalog_sha256,
            "source_ledger_path": str(self.source_ledger_path),
            "source_ledger_sha256": self.source_ledger_sha256,
            "skill_count": len(self.skills),
            "repo_reference_count": len(self.repos),
            "tool_declaration_count": len(self.tools),
            "source_method_count": len(self.source_methods),
            "read_only": True,
            "skills_or_tools_executed": False,
        }

    def source_method(self, source_id: str | int) -> SourceMethodRecord:
        key = str(source_id)
        try:
            return self._method_by_source_id[key]
        except KeyError as error:
            raise KeyError(f"Unknown source_id: {key}") from error

    def search(
        self,
        query: str = "",
        *,
        kinds: tuple[EntityKind, ...] | list[EntityKind] | None = None,
        source_id: str | int | None = None,
        classification: str | None = None,
        review_status: str | None = None,
        include_excluded: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search typed metadata records with deterministic ranking and filters."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("limit must be an integer from 1 to 500")
        accepted = {"skill", "repo", "tool", "source_method"}
        selected = tuple(("skill", "repo", "tool", "source_method") if kinds is None else kinds)
        if not selected or any(kind not in accepted for kind in selected):
            raise ValueError("kinds must contain skill, repo, tool, or source_method")
        if source_id is not None and "source_method" not in selected:
            raise ValueError("source_id filtering is available for source_method records")
        selected_source_id = str(source_id) if source_id is not None else None
        selected_classification = classification.casefold() if classification is not None else None
        terms = _tokens(query)
        ranked: list[tuple[int, str, str, dict[str, Any]]] = []
        for kind in selected:
            if kind == "skill":
                for item in self.skills:
                    if item.review_status == "excluded" and not include_excluded:
                        continue
                    if review_status is not None and item.review_status != review_status:
                        continue
                    title_terms = set(_tokens(item.name))
                    body_terms = set(_tokens(item.searchable_text))
                    score = sum(5 if term in title_terms else 1 for term in terms if term in body_terms)
                    if terms and score == 0:
                        continue
                    ranked.append((-score, item.name.casefold(), item.id, item.as_dict()))
            elif kind == "repo":
                for item in self.repos:
                    searchable = _tokens(" ".join((item.name, item.url or "", item.commit or "")))
                    score = sum(5 if term in set(_tokens(item.name)) else 1 for term in terms if term in searchable)
                    if terms and score == 0:
                        continue
                    ranked.append((-score, item.name.casefold(), item.id, item.as_dict()))
            elif kind == "tool":
                for item in self.tools:
                    searchable = set(_tokens(item.name))
                    score = sum(5 if term in searchable else 0 for term in terms)
                    if terms and score == 0:
                        continue
                    ranked.append((-score, item.name.casefold(), item.id, item.as_dict()))
            else:
                for item in self.source_methods:
                    if selected_source_id is not None and item.source_id != selected_source_id:
                        continue
                    if selected_classification is not None and item.classification.casefold() != selected_classification:
                        continue
                    searchable = set(_tokens(" ".join((item.method, item.classification, item.shortcode))))
                    score = sum(5 if term in set(_tokens(item.method)) else 1 for term in terms if term in searchable)
                    if terms and score == 0:
                        continue
                    ranked.append((-score, item.method.casefold(), item.id, item.as_dict()))
        ranked.sort(key=lambda row: (row[0], row[1], row[2], row[3]["kind"]))
        return [row[3] for row in ranked[:limit]]

    def _skill_match_score(self, query: str, item: SkillRecord) -> int:
        terms = _tokens(query)
        title_terms = set(_tokens(item.name))
        body_terms = set(_tokens(item.searchable_text))
        return sum(5 if term in title_terms else 1 for term in terms if term in body_terms)

    def _candidate(self, item: SkillRecord, score: int, match_kind: str) -> dict[str, Any]:
        repo_items = [
            {
                "kind": "repo", "id": repo.id, "name": repo.name,
                "url": repo.url, "commit": repo.commit,
                "status": "metadata reference only; repository code is not executed",
            }
            for ident in item.repo_ids if (repo := self._repo_by_id.get(ident)) is not None
        ]
        tool_items = [
            {
                "kind": "tool", "id": tool.id, "name": tool.name,
                "status": "declared capability reference only; availability and credentials are unverified",
                "credential_check_required_before_execution": True,
                "execution_authorized": False,
            }
            for ident in item.tool_ids if (tool := self._tool_by_id.get(ident)) is not None
        ]
        return {
            "kind": "skill",
            "skill_id": item.id,
            "name": item.name,
            "description": item.description,
            "score": score,
            "match_kind": match_kind,
            "route_status": "suggestion_only",
            "review_status": item.review_status,
            "review_scope": item.review_scope,
            "exclusion_reason": item.exclusion_reason,
            "skill_provenance": item.provenance,
            "license_status": item.license_status,
            "availability": item.availability,
            "requirements": item.requirements,
            "related_entities": {"repos": repo_items, "tools": tool_items},
            "evidence_limit": "Catalog metadata is a discovery hint, not evidence that this skill fits or is safe for the source method.",
            "execution_allowed": False,
        }

    def route_source(self, source_id: str | int, *, limit: int = 5) -> dict[str, Any]:
        """Return deterministic candidate references for one actual source ID."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 20:
            raise ValueError("limit must be an integer from 1 to 20")
        source = self.source_method(source_id)
        classification = source.classification.casefold()
        query = source.method
        candidates: list[tuple[int, int, str, dict[str, Any]]] = []

        if classification in _HELD_CLASSIFICATIONS:
            route_state = "held_for_source_evidence"
            hold_reason = "The source matrix requires evidence or visual review before a candidate skill can be routed."
        elif classification not in _ACTIONABLE_CLASSIFICATIONS:
            route_state = "no_automation_route"
            hold_reason = "The source matrix does not classify this row as a reusable actionable method."
        else:
            route_state = "candidate_suggestions_only" if classification == "actionable_method" else "partial_method_requires_source_review"
            hold_reason = None if classification == "actionable_method" else "Complete the source-faithful method and resolve evidence gaps before using an adaptation suggestion."
            for item in self.skills:
                if item.review_status == "excluded":
                    continue
                score = self._skill_match_score(query, item)
                in_scope = item.review_status == "bounded_static_review" and 139 in item.task_ids
                if item.review_status == "bounded_static_review" and not in_scope:
                    continue
                if score < _MIN_METADATA_MATCH_SCORE and not in_scope:
                    continue
                match_kind = "bounded_workstream_scope" if in_scope else "metadata_similarity"
                # Explicitly reviewed workstream scope wins ties; raw metadata
                # similarity can never outrank its provenance or imply safety.
                priority = 0 if in_scope else 1
                candidates.append((priority, -score, item.id, self._candidate(item, score, match_kind)))
            candidates.sort(key=lambda row: (row[0], row[1], row[3]["name"].casefold(), row[2]))
        return {
            "kind": "source_route",
            "source_id": source.source_id,
            "source_method_id": source.id,
            "shortcode": source.shortcode,
            "method": source.method,
            "classification": source.classification,
            "task_ids": [139],
            "route_state": route_state,
            "hold_reason": hold_reason,
            "evidence_status": source.evidence_status,
            "exact_next_piece": source.exact_next_piece,
            "account_or_rights_gates": source.account_or_rights_gates,
            "requirements": {
                "source_faithful_method_must_be_recorded_separately": True,
                "human_review_before_adaptation": True,
                "owner_rights_and_account_gates_must_be_resolved": bool(source.account_or_rights_gates),
                "budget_constraint": "Paid actions require exact MARVIN approval; this router grants no paid or external-action approval.",
                "publication_or_external_actions_authorized": False,
                "installation_or_execution_authorized": False,
            },
            "candidates": [row[3] for row in candidates[:limit]],
            "suggestion_only": True,
            "execution_allowed": False,
            "provenance": {
                "catalog_sha256": self.catalog_sha256,
                "source_ledger_sha256": self.source_ledger_sha256,
                "source_row_id": source.id,
                "basis": "Source ledger summary and local skill metadata only; inspect source evidence and the exact skill manifest before relying on a candidate.",
            },
        }

    def route_all_sources(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return one deterministic route receipt for every ledger source ID."""
        return [self.route_source(item.source_id, limit=limit) for item in self.source_methods]


def load_router(
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    source_ledger_path: Path | str = DEFAULT_SOURCE_LEDGER_PATH,
    *,
    review_manifest_root: Path | str | None = DEFAULT_REVIEW_MANIFEST_ROOT,
) -> SkillRouter:
    """Convenience factory for adapters that want the read-only router."""
    return SkillRouter(catalog_path, source_ledger_path, review_manifest_root=review_manifest_root)
