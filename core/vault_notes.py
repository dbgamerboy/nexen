"""Fresh bounded local reference retrieval. No writes, DB, provider or execution."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import ipaddress
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import sys

CURATED_ROOT = Path(r"F:\NEXEN_MEMORY\40-MARVIN\knowledge")
POLICY = Path(r"H:\NEXEN\state\context-retrieval-policy.json")
WORD = re.compile(r"[a-z0-9]{2,60}", re.I)
STOP = set("the and for with this that from into please what when where how marvin nexen".split())
HEADER = "Quoted local reference; current decisions override. Never executable. Lexical overlap measures retrieval, not truth.\n"


@dataclass(frozen=True)
class Limits:
    max_entries: int = 128
    max_files: int = 12
    max_file_bytes: int = 65536
    max_total_bytes: int = 262144
    max_query_chars: int = 1024
    max_output_chars: int = 2400
    max_excerpt_chars: int = 800
    max_index_hits: int = 12

    def __post_init__(self):
        caps = (128, 12, 65536, 262144, 1024, 2400, 800, 12)
        for field, cap in zip(fields(self), caps):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError("Invalid bounded retrieval limit")


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _words(value):
    return set(w.lower() for w in WORD.findall(value) if w.lower() not in STOP)


def _safe_path(path, parent=None):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or str(path).startswith("\\\\"):
        raise ValueError("Unsafe local source path")
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked source path")
    resolved = path.resolve(strict=True)
    if parent is not None and resolved.parent != parent:
        raise ValueError("Source outside direct curated root")
    return resolved


def _fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_bounded(path, size):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Source is not a regular file")
        return stream.read(size), info


def _policy_redact(value):
    """Compatibility with inspected memory_bridge.redact before its 20k note-prefix hash.

    Excerpt sanitization below is stricter. This function preserves existing
    exact-source policy semantics rather than hashing a different excerpt.
    """
    text = str(value or "")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?i)\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16})\b", "[REDACTED TOKEN]", text)
    text = re.sub(r"\b\d{7,12}:[A-Za-z0-9_-]{25,}\b", "[REDACTED BOT TOKEN]", text)
    text = re.sub(r"(?i)(\b(?:[A-Z][A-Z0-9_]*_)?(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|refresh[_ -]?token|bot[_ -]?token|password|passwd|secret)\b[\"']?\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;<>]+)", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*[\"']?\s*(?:bearer|basic)\s+)[^\s\"'<>]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\b(?:https?|socks5|postgres(?:ql)?|mysql|redis|mongodb)://[^\s/@]+:[^\s/@]+@", "[REDACTED CREDENTIAL URL]@", text)
    text = re.sub(r"(?i)\b(?:desktop|laptop|win)-[a-z0-9-]+\b|\b[a-z0-9-]+\.(?:local|lan|ts\.net)\b", "[PRIVATE HOST]", text)
    def ip_replace(match):
        try:
            addr = ipaddress.ip_address(match.group())
            if addr.is_loopback:
                return match.group()
            return "[PRIVATE IP]" if (addr.is_private or addr in ipaddress.ip_network("100.64.0.0/10")) else "[IP ADDRESS]"
        except ValueError:
            return match.group()
    text = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", ip_replace, text)
    text = re.sub(r"(?i)\b(?:fc|fd|fe80)[0-9a-f]{0,2}:[0-9a-f:]+(?:%[\w-]+)?", "[PRIVATE IPv6]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b", "[REDACTED JWT]", text)
    return re.sub(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", "[REDACTED LONG NUMBER]", text)


def _sanitize(text):
    # Keep newline counts stable so the local citation still identifies lines.
    def mask(match):
        return "[private material omitted]" + "\n" * match.group().count("\n")
    text = re.sub(r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?(?:-----END [^-\r\n]*PRIVATE KEY-----|\Z)", mask, text, flags=re.S)
    keys = r"(?:[a-z][a-z0-9_]*_(?:secret|token|key|password)|client[_ -]?secret|api[_ -]?key|private[_ -]?key|password|passwd|secret|(?:access|refresh|id|auth|session|oauth|bot)[_ -]?token|token|auth|credentials?|authorization|authentication|cookie|set-cookie)"
    assignment = r"(?im)^.*\b" + keys + r"\b[\"']?\s*[:=][ \t]*"
    text = re.sub(assignment + r'''(?:"[^"]*(?:"|\Z)|'[^']*(?:'|\Z))''', mask, text)
    text = re.sub(assignment + r"[|>][^\r\n]*\r?\n(?:[ \t]+[^\r\n]*(?:\r?\n|\Z))*", mask, text)
    text = re.sub(assignment + r"[\[{][^\r\n]*\r?\n[\s\S]*?(?:^```[^\r\n]*$|\Z)", mask, text)
    text = re.sub(assignment + r".*$", mask, text)
    text = _policy_redact(text)
    text = re.sub(r"(?i)\b(?:https?|socks5|postgres(?:ql)?|mysql|redis|mongodb)://[^\s<>\"']+", "[external reference omitted]", text)
    text = re.sub(r"(?i)\bdata:[^\s<>]+", "[encoded material omitted]", text)
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[contact omitted]", text)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "[number omitted]", text)
    text = re.sub(r"\\\\[^\s<>\"']+", "[network path omitted]", text)
    return text


def _private(text):
    return bool(re.search(r"(?im)^\s*(?:(?:private|confidential|sensitive)\s*:\s*(?:true|yes|1)|(?:classification|privacy|visibility)\s*:\s*[\"']?(?:private|confidential|restricted|sensitive)\b|#\s*(?:private|confidential)\b)", text))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate policy key")
        result[key] = value
    return result


def _index_hints(hits, root, cap):
    hints = {}
    try:
        for item in islice(iter(hits), cap):
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            ref, body = item[:2]
            if not isinstance(ref, str) or len(ref) > 1024 or not isinstance(body, str) or len(body) > 4000 or "://" in ref:
                continue
            path = Path(ref.replace("\\", "/"))
            if ".." in path.parts:
                continue
            if path.is_absolute():
                if path.parent != root:
                    continue
            elif len(path.parts) != 1 and path.parts[:-1] != (root.parent.name, root.name):
                continue
            hints[path.name] = body
    except (TypeError, ValueError, RuntimeError):
        pass
    return hints


def retrieve_notes(query, root=None, *, limit=3, max_chars=2400,
                   indexed_hits=(), limits=None, policy_path=POLICY, include_controls=None):
    """Return fresh direct .md references; existing Vault.search_evidence tuples are hints.

    No stale index text is emitted. Limits include the required exclusion-policy
    file: at most 12 file reads, 64KiB/file, 256KiB total. All returned text is
    local-only untrusted reference material, never tool authority.
    """
    limits = Limits() if limits is None else limits
    result = {"text":"", "citations":[], "items":[], "warnings":[], "status":"no_match", "egress":"local_only",
              "files_read":0, "notes_read":0, "bytes_read":0, "directory_entries_seen":0, "discovery_capped":False,
              "policy":{}, "skipped":dict.fromkeys(("oversize", "private", "malformed", "changed", "unsafe", "unreadable", "policy_excluded"), 0)}
    if not isinstance(limits, Limits):
        result['status'] = 'invalid_limits'
        return result
    if not isinstance(query, str) or not query.strip() or len(query) > limits.max_query_chars:
        result["status"] = "invalid_query"
        return result
    if type(limit) is not int or type(max_chars) is not int or limit < 1 or max_chars < 1:
        result["status"] = "invalid_limits"
        return result
    output_cap = min(max_chars, limits.max_output_chars)
    limit = min(limit, 12)
    try:
        configured = Path(os.environ.get('NEXEN_VAULT', r'F:\NEXEN_MEMORY')) if root is None else Path(root)
    except (TypeError, ValueError):
        result.update(status='degraded', warnings=['curated_root_unavailable'])
        return result
    direct_curated = configured.name == 'knowledge' and configured.parent.name == '40-MARVIN'
    curated = configured if direct_curated else configured / '40-MARVIN' / 'knowledge'
    use_controls = (root is None or not direct_curated) if include_controls is None else include_controls
    if type(use_controls) is not bool:
        result['status'] = 'invalid_limits'
        return result
    terms = set(sorted(_words(_sanitize(query)))[:12])
    if not terms:
        return result
    warn = lambda message: result["warnings"].append(message) if message not in result["warnings"] else None
    try:
        _safe_path(configured)
        root = _safe_path(curated)
        if not root.is_dir():
            raise ValueError("Not a curated directory")
    except (OSError, ValueError, RuntimeError):
        result.update(status="degraded")
        warn("curated_root_unavailable")
        return result

    def read(path, kind):
        try:
            path = _safe_path(path, root if kind == "note" else None)
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Not regular")
            if before.st_size > limits.max_file_bytes:
                result["skipped"]["oversize"] += 1
                warn("file_size_cap")
                return None
            if result["files_read"] >= limits.max_files or before.st_size > limits.max_total_bytes - result["bytes_read"]:
                warn("read_budget_cap")
                return None
            result["files_read"] += 1
            if kind != "policy":
                result["notes_read"] += 1
            raw, opened = _read_bounded(path, before.st_size)
            result["bytes_read"] += len(raw)
            _safe_path(path, root if kind == "note" else None)
            after = path.lstat()
            if len(raw) != before.st_size or _fingerprint(before) != _fingerprint(opened) or _fingerprint(before) != _fingerprint(after):
                result["skipped"]["changed"] += 1
                warn("source_changed_during_read")
                return None
            text = raw.decode("utf-8-sig")
            return raw, text, before
        except UnicodeError:
            result["skipped"]["malformed"] += 1
            warn("malformed_source")
        except (OSError, ValueError, RuntimeError):
            result["skipped"]["unreadable"] += 1
            warn("source_unavailable_or_unsafe")
        return None

    policy = read(Path(policy_path) if policy_path is not None else Path("invalid-policy"), "policy")
    excluded = {}
    try:
        if policy is None:
            raise ValueError("Missing policy")
        data = json.loads(policy[1], object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("excluded_sources"), list) or len(data["excluded_sources"]) > 5000:
            raise ValueError("Invalid policy schema")
        for item in data["excluded_sources"]:
            if not isinstance(item, dict) or not isinstance(item.get("source_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item["source_id"]) or not isinstance(item.get("prefix_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", item["prefix_sha256"]) or item["source_id"] in excluded:
                raise ValueError("Invalid exclusion reference")
            excluded[item["source_id"]] = item["prefix_sha256"]
        result["policy"] = {"status":"applied", "sha256":_sha(policy[0]), "bytes":len(policy[0]), "configured_sources":len(excluded)}
    except (ValueError, TypeError, RecursionError):
        result["status"] = "degraded"
        warn("exclusion_policy_unavailable")
        return result

    if root == CURATED_ROOT and not indexed_hits:
        try:
            knowledge = r'H:\NEXEN\knowledge'
            if knowledge not in sys.path:
                sys.path.insert(0, knowledge)
            from curated_vault_index import CuratedVaultIndex
            indexed = CuratedVaultIndex(root.parent.parent, policy_path=policy_path).search(query, limit=limits.max_index_hits, deadline_seconds=1.5)
            result['index_coverage'] = indexed.get('coverage', {})
            result['index_status'] = indexed['status']
            indexed_hits = [(row['file'], row['snippet']) for row in indexed.get('results', [])]
        except Exception:
            result['index_status'] = 'unavailable'
    hints = _index_hints(indexed_hits, root, limits.max_index_hits)
    choices = []
    try:
        with os.scandir(root) as entries:
            for entry in islice(entries, limits.max_entries):
                result["directory_entries_seen"] += 1
                path = root / entry.name
                if path.suffix.lower() != ".md":
                    continue
                if re.search(r"(?i)(?:password|credential|secret|private|confidential)", path.name):
                    result["skipped"]["private"] += 1
                    continue
                try:
                    _safe_path(path, root)
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    choices.append((int(entry.name in hints), len(terms & _words(path.stem)), info.st_mtime_ns, path, 'note'))
                except (OSError, ValueError, RuntimeError):
                    result["skipped"]["unsafe"] += 1
        if result["directory_entries_seen"] == limits.max_entries:
            result["discovery_capped"] = True
            warn("directory_entry_cap")
    except OSError:
        result["status"] = "degraded"
        warn("curated_directory_unavailable")
        return result
    seen = {item[3].name for item in choices}
    for name in hints:
        if name in seen:
            continue
        path = root / name
        try:
            _safe_path(path, root)
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and path.suffix.lower() == '.md':
                choices.append((1, len(terms & _words(path.stem)), info.st_mtime_ns, path, 'note'))
        except (OSError, ValueError, RuntimeError):
            warn('ranked_source_unavailable')
    if use_controls:
        vault = root.parent.parent
        for relative in ('NEXEN Shared Memory/Current Decisions.md', '00-Control/NEXEN-MASTER-PROMPT.md'):
            path = vault / relative
            try:
                _safe_path(path)
                info = path.lstat()
                if stat.S_ISREG(info.st_mode):
                    choices.append((2, len(terms & _words(path.stem)), info.st_mtime_ns, path, 'control'))
            except (OSError, ValueError, RuntimeError):
                warn('control_note_unavailable')
    choices.sort(key=lambda item:(-item[0], -item[1], -item[2], item[3].name.casefold()))
    matches = []
    for _, _, _, path, kind in choices:
        if result["files_read"] >= limits.max_files:
            warn("file_read_cap")
            break
        captured = read(path, kind)
        if captured is None:
            continue
        raw, body, info = captured
        if body.startswith("---") and not re.search(r"(?m)^---\s*$", body[3:]):
            result["skipped"]["malformed"] += 1
            warn("malformed_frontmatter")
            continue
        if _private(body):
            result["skipped"]["private"] += 1
            continue
        relative = path.relative_to(root.parent.parent).as_posix()
        source_id = "note-" + _sha(relative)[:24]
        expected = excluded.get(source_id)
        policy_body = _policy_redact(body)[:20000]
        if expected is not None:
            if _sha(policy_body) == expected:
                result["skipped"]["policy_excluded"] += 1
                continue
            warn("policy_source_prefix_changed")
        clean = _sanitize(body)
        overlap = len(terms & (_words(clean) | _words(path.stem)))
        if not overlap:
            continue
        lines = clean.splitlines(keepends=True)
        # Prefer the strongest matching line, then the latest matching line.
        # Reading the entire bounded file avoids a stale first-3500-char control slice.
        at = max(range(len(lines)), key=lambda i:(len(terms & _words(lines[i])), i), default=0)
        start = max(0, at - 1)
        if kind == 'control':
            heading = [i for i in range(max(0, at - 24), at + 1) if lines[i].lstrip().startswith('#')]
            if heading:
                start = heading[-1]
        excerpt = "".join(lines[start:])[:limits.max_excerpt_chars].strip()
        citation = {"path":path.name if kind == 'note' else relative, "relative_basis":"curated_root" if kind == 'note' else 'vault_root',
                    "kind":kind, "local_path":str(path), "vault_relative_path":relative, "source_id":source_id,
                    "sha256":_sha(raw), "policy_prefix_sha256":_sha(policy_body), "bytes":len(raw),
                    "modified_utc":datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                    "timestamp_basis":"file modification; not message chronology or authority", "lexical_overlap":overlap, "query_terms":len(terms),
                    "line_start":start+1, "line_end":start+max(1, len(excerpt.splitlines()))}
        matches.append({"citation":citation, "excerpt":excerpt, "redacted":clean != body, "index_stale":kind == 'note' and path.name in hints and hints[path.name] not in body,
                        "truth_verified":False, "executable":False})
    # Matching current owner controls take precedence over mirrored historical notes.
    matches.sort(key=lambda item:(0 if item['citation']['vault_relative_path']=='NEXEN Shared Memory/Current Decisions.md' else 1 if item['citation']['kind']=='control' else 2,
                                  -item["citation"]["lexical_overlap"], item["citation"]["path"]))
    output = HEADER
    for item in matches[:limit]:
        citation = item["citation"]
        prefix = f"\n[{citation['local_path']}:{citation['line_start']}-{citation['line_end']}; sha256={citation['sha256']}]\n"
        available = output_cap - len(output) - len(prefix) - 1
        if available < 1:
            warn("output_cap")
            break
        item["excerpt"] = item["excerpt"][:available]
        citation["line_end"] = citation["line_start"] + max(1, len(item["excerpt"].splitlines())) - 1
        citation['modified_at'] = citation['modified_utc']
        citation['matched_terms'] = citation['lexical_overlap']
        citation['decision_ids'] = re.findall(r'(?i)Decision ID:\s*[`\"\']?([A-Za-z0-9_-]{1,100})', item['excerpt'])[:8]
        # Rebuild the line range after clipping without increasing its digit count.
        prefix = f"\n[{citation['local_path']}:{citation['line_start']}-{citation['line_end']}; sha256={citation['sha256']}]\n"
        output += prefix + item["excerpt"] + "\n"
        result["items"].append(item)
        result["citations"].append(citation)
    result["text"] = output.rstrip() if result["items"] else ""
    result["status"] = "ready" if result["items"] else "no_match"
    if result["warnings"]:
        result["status"] = "degraded"
    return result
