"""Research to workflow, under the rules.

A research item (a learned fact, a YouTube transcript note, a world signal) becomes a workflow DRAFT with its lane,
steps, accounts, daily volume, spend and gates. The draft is checked against the rules engine before it is saved,
and it is saved INACTIVE with the verdict attached. A draft that would break a rule is not discarded: it is rewritten
to the lawful alternative (test account experiment, next window, other platform) and says why. Nothing here posts,
spends or sends; activation is an owner step recorded elsewhere.
"""
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from nexen.core import paths
from nexen.shared.utils import textsim

LANE_HINTS = [
    ("services", r"upwork|fiverr|client|proposal|gig|freelanc|landing page|automation service"),
    ("clipping", r"clip|shorts|whop|reel|caption"),
    ("dropship", r"product|dropship|store|tiktok shop|supplier|lumipaw|curviana"),
    ("youtube", r"youtube|channel|faceless|kids"),
    ("persona", r"persona|ai girl|influencer"),
    ("affiliate", r"affiliate|amazon|commission"),
]

SCHEMA = "nexen.v4.research-workflow-draft.v2"
MAX_DRAFT_BYTES = 256 * 1024
MAX_TEXT_CHARS = 20_000


class DraftInputError(ValueError):
    """No draft was published: its bounded request or rule result was invalid."""


class DraftConflict(ValueError):
    """A saved draft changed or conflicts; preserve it for explicit review."""


class DraftStorageError(OSError):
    """Publication could not be verified; never substitute an overwrite."""


def _json(value, pretty=False):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          indent=2 if pretty else None,
                          separators=None if pretty else (",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise DraftInputError("Draft data must be finite, bounded JSON.") from exc


def _text(value, label, limit, allow_empty=False):
    if not isinstance(value, str):
        raise DraftInputError(label + " must be text.")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > limit or any(
            ord(c) < 32 and c not in "\n\t" for c in value):
        raise DraftInputError("Invalid bounded " + label + ".")
    return value


def _inputs(item_text, source_ids, rules, platform, account, daily_posts, spend, name):
    text = _text(item_text, "research text", MAX_TEXT_CHARS)
    platform = _text(platform, "platform", 40)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", platform):
        raise DraftInputError("Invalid platform identifier.")
    if type(daily_posts) is not int or not 1 <= daily_posts <= 1000:
        raise DraftInputError("Daily volume must be an integer from 1 to 1000; rules still govern it.")
    if type(spend) not in (int, float) or not math.isfinite(spend) or not 0 <= spend <= 1_000_000:
        raise DraftInputError("Spend must be a finite nonnegative planning amount.")
    if not isinstance(source_ids, (list, tuple)) or len(source_ids) > 64:
        raise DraftInputError("Use at most 64 source identifiers.")
    sources = []
    for source in source_ids:
        source = _text(source, "source identifier", 2048)
        if "\n" in source or "\t" in source:
            raise DraftInputError("Source identifiers must occupy one line.")
        if source not in sources:
            sources.append(source)
    cfg = getattr(rules, "cfg", None)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("accounts"), list):
        raise DraftInputError("Rules must provide their current account configuration.")
    config = _json(cfg)
    if len(config) > MAX_DRAFT_BYTES:
        raise DraftInputError("Rule configuration exceeds the planning read cap.")
    accts = []
    for entry in cfg["accounts"]:
        if not isinstance(entry, dict):
            raise DraftInputError("Malformed rule account configuration.")
        if entry.get("platform") == platform:
            accts.append(entry)
    main = next((a for a in accts if a.get("role") == "main" and a.get("status") != "not_created"), None)
    acct = account if account is not None else (main.get("id") if main else None)
    if acct is not None:
        acct = _text(acct, "account identifier", 128)
        if "\n" in acct or "\t" in acct:
            raise DraftInputError("Account identifier must occupy one line.")
    title = _text(name, "draft name", 200) if name is not None else text[:70]
    amount = format(Decimal(str(spend)).normalize(), "f")
    scope = {"schema": SCHEMA, "text": text, "source_ids": sources,
             "platform": platform, "account": acct, "daily_posts": daily_posts,
             "spend_decimal": amount, "name": title,
             "rules_config_sha256": hashlib.sha256(config).hexdigest()}
    return scope


def _guard(path, root):
    """All publication and readback paths are local, lexically confined, no-reparse."""
    path, root = Path(path), Path(root)
    if not path.is_absolute() or not root.is_absolute() or any(p in (".", "..") for p in path.parts):
        raise DraftStorageError("Draft storage requires an absolute confined path.")
    if str(path).startswith(("\\\\", "//")):
        raise DraftStorageError("Remote draft storage is outside this local contract.")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DraftStorageError("Draft path is outside its configured data store.") from exc
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DraftStorageError("Reparse or symlink draft paths are not allowed.")
    return path


def _store():
    data = Path(paths.DATA)
    out = _guard(data / "workflows", data)
    data.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    _guard(out, data)
    if not out.is_dir():
        raise DraftStorageError("The existing workflow store is not a directory.")
    return out, data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DraftConflict("Saved draft has duplicate JSON keys.")
        result[key] = value
    return result


def _without_created(plan):
    return {key: value for key, value in plan.items() if key not in {"created", "plan_sha256"}}


def _read_saved(target, root, expected):
    _guard(target, root)
    before = target.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_DRAFT_BYTES:
        raise DraftConflict("Saved draft is not a bounded regular file.")
    with target.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_DRAFT_BYTES + 1)
        after_open = os.fstat(stream.fileno())
    _guard(target, root)
    after = target.stat()
    signature = lambda s: (s.st_size, s.st_mtime_ns, s.st_ino)
    if (len(raw) != before.st_size or len(raw) > MAX_DRAFT_BYTES or
            any(signature(s) != signature(before) for s in (opened, after_open, after))):
        raise DraftConflict("Saved draft changed during readback.")
    try:
        saved = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DraftConflict("Saved draft is malformed; it was preserved.") from exc
    if not isinstance(saved, dict) or not isinstance(saved.get("created"), str):
        raise DraftConflict("Saved draft has no valid creation metadata.")
    payload = {key: value for key, value in saved.items() if key != "plan_sha256"}
    if saved.get("plan_sha256") != hashlib.sha256(_json(payload)).hexdigest():
        raise DraftConflict("Saved draft integrity changed; it was preserved.")
    if raw != _json(saved, pretty=True) + b"\n":
        raise DraftConflict("Saved draft bytes changed; it was preserved.")
    if _without_created(saved) != _without_created(expected):
        raise DraftConflict("Saved draft or current rule verdict conflicts; explicit review is required.")
    return saved


def _publish(plan):
    """An atomic create-if-absent admits one writer; exact repeats read its receipt.

    The temporary body is fsynced before a same-filesystem hard link exposes the
    final name. No existing JSON is replaced. Unsupported link filesystems fail
    explicitly; orphaned crash temporaries stay hidden and are not auto-deleted.
    This guarantees whole-body publication, not power-loss directory durability.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("id"), str) or not re.fullmatch(r"WF-[0-9a-f]{64}", plan["id"]):
        raise DraftInputError("Publication requires the code-owned scoped draft ID.")
    raw = _json(plan, pretty=True) + b"\n"
    if len(raw) > MAX_DRAFT_BYTES:
        raise DraftInputError("Draft exceeds the publication cap.")
    out, data = _store()
    target = _guard(out / (plan["id"] + ".json"), data)
    try:
        return _read_saved(target, data, plan)
    except FileNotFoundError:
        pass
    fd, name = tempfile.mkstemp(prefix="." + plan["id"] + "-", suffix=".tmp", dir=out)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _guard(temporary, data)
        _guard(target, data)
        try:
            os.link(temporary, target)
        except FileExistsError:
            # A concurrent writer won the same atomic namespace admission.
            pass
        except OSError as exc:
            raise DraftStorageError("Atomic draft publication failed; no overwrite fallback was used.") from exc
        return _read_saved(target, data, plan)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _lane(text):
    for lane, rx in LANE_HINTS:
        if re.search(rx, text, re.I):
            return lane
    return "research"


def draft(item_text, source_ids, rules, platform="tiktok", account=None, daily_posts=1, spend=0.0, name=None):
    """Return a workflow draft with rule verdicts. `account` defaults to the first main account on the platform."""
    scope = _inputs(item_text, source_ids, rules, platform, account, daily_posts, spend, name)
    item_text, source_ids, platform, acct = scope["text"], scope["source_ids"], scope["platform"], scope["account"]
    lane = _lane(item_text)
    scope_sha256 = hashlib.sha256(_json(scope)).hexdigest()
    wid = "WF-" + scope_sha256
    steps = ["Read the source note and restate the method in one paragraph (faithful version first).",
             "Write the NEXEN-stack variant mapped to the same steps, labeled separately.",
             "Produce original content only; no copied media; disclose AI and affiliate content.",
             "Run the rules check for every post, spend and message before it is queued.",
             "Queue for owner approval with the exact payload; publish only after approval; read the provider receipt back.",
             "Record the metric after 48 hours as an experiment run."]
    action = {"type": "post", "platform": platform, "account": acct, "workflow": wid, "count": daily_posts, "mirrors": False}
    verdict = rules.check(action)
    if not isinstance(verdict, dict) or verdict.get("status") not in {"allow", "allow_with_approval", "blocked"}:
        raise DraftInputError("Rules returned a malformed verdict.")
    plan = {"id": wid, "name": scope["name"], "lane": lane, "platform": platform, "status": "draft-inactive", "source_ids": source_ids,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "requested": action, "verdict": verdict, "steps": steps, "spend": spend,
            "gates": ["owner approval to publish", "rules engine per post"] + (["MARVIN approval for spend"] if spend else [])}
    if spend:
        plan["spend_verdict"] = rules.check({"type": "spend", "spend": spend, "approved": False})
    if verdict["status"] == "blocked":
        lawful = [a for a in verdict.get("alternatives", []) if a["status"] != "blocked"]
        # an untested idea should become an experiment on a test account; waiting is the fallback
        pick = next((a for a in lawful if "test account" in a["option"].lower()), lawful[0] if lawful else None)
        plan["rewritten_as"] = pick["option"] if pick else "hold until a rule allows it"
        plan["status"] = "draft-rewritten-by-rules"
        plan["why"] = verdict["blocks"][:3]
    plan.update(schema=SCHEMA, input_scope=scope, scope_sha256=scope_sha256,
                legacy_text_id="WF-" + hashlib.sha256(textsim.normalize(item_text).encode()).hexdigest()[:8])
    plan["spend"] = float(scope["spend_decimal"])
    plan["plan_sha256"] = hashlib.sha256(_json(plan)).hexdigest()
    return _publish(plan)


def list_drafts():
    out = paths.DATA / "workflows"
    rows = []
    if out.is_dir():
        for p in sorted(out.glob("WF-*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                rows.append({"id": d["id"], "name": d["name"], "lane": d["lane"], "status": d["status"], "verdict": d["verdict"]["status"],
                             "rewritten_as": d.get("rewritten_as"), "created": d["created"], "sources": d.get("source_ids", [])[:2]})
            except (OSError, ValueError, KeyError):
                continue
    return rows
