"""MARVIN's evidence-backed practice, research queue, and memory coverage.

Practice runs exercise existing local retrieval interfaces and store metadata
only. They never save recalled private excerpts or execute imported workflows.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

BASE = Path(__file__).resolve().parent
PAUSE_MARKER = BASE / "data" / "PAUSE_AUTONOMY"
INTEGRATIONS = Path("H:/NEXEN/integrations")
MEMSEARCH_PYTHON = INTEGRATIONS / "memsearch-venv/Scripts/python.exe"
MEMSEARCH_ADAPTER = INTEGRATIONS / "memsearch_adapter.py"
VECTOR_QUERY = "What is the current NEXEN stem export plan?"
VECTOR_EXPECTED_SOURCE = "NEXEN-stem-export-plan-2026-09-09.md"
VECTOR_ALLOWED_SOURCES = {
    "canary.md", "WDR-City-build-2026-09-09.md",
    "NEXEN-stem-export-plan-2026-09-09.md", "NEXEN-H-storage-transition-2026-09-09.md",
}
VECTOR_TIMEOUT_SECONDS = 90

MEMORY_DRILLS = {
    "commerce": ("LumiPaw checkout supplier dropshipping product ads", "workflow"),
    "music": ("FL Studio stems mix mastering music release", "code"),
    "life": ("current housing rent task benefits stability", "code"),
    "game": ("WDR City game clothes lookbook avatar", "code"),
    "voice": ("MARVIN voice speech microphone TTS", "automation"),
    "automation": ("n8n workflow orchestration Ollama automation", "workflow"),
    "engineering": ("Python code architecture regression tests refactor", "code"),
}

# This is the current NEXEN revenue order. Each drill asks for evidence already
# indexed locally; the separate research action queues current, cited research.
BUSINESS_TRACKS = (
    {"id": "clipping_campaign", "name": "Paid clipping and campaign work",
     "query": "paid clipping campaigns current approved campaign terms creator deliverables payout receipts",
     "task_type": "workflow"},
    {"id": "lumipaw", "name": "LumiPaw organic marketing",
     "query": "LumiPaw product facts supplier fulfillment organic content current approvals",
     "task_type": "workflow"},
    {"id": "curivana", "name": "Curivana organic marketing",
     "query": "Curivana product facts jeans supplier fulfillment organic content current approvals",
     "task_type": "workflow"},
    {"id": "youtube", "name": "YouTube production",
     "query": "YouTube original production channel niche upload evidence workflow",
     "task_type": "automation"},
    {"id": "youtube_kids", "name": "YouTube Kids production",
     "query": "YouTube Kids original production age suitability child safety adult review",
     "task_type": "automation"},
    {"id": "ai_personas", "name": "AI personas",
     "query": "fictional adult AI personas platform rules disclosure business research",
     "task_type": "automation"},
    {"id": "service_marketplace", "name": "NEXEN automation and service marketplace",
     "query": "service marketplace n8n automation offer portfolio lead evidence client workflow",
     "task_type": "workflow"},
    {"id": "wdr_creative", "name": "WDR creative brand and music",
     "query": "WDR brand music releases merchandise creative production current status",
     "task_type": "code"},
)


class PracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["full", "memory", "businesses", "orchestration", "vector_rag"]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["all_businesses", "one_business"]
    business_id: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status(citations: list, warnings: list) -> str:
    if not citations:
        return "no_evidence"
    return "partial" if warnings else "pass"


def _retrieval_drill(track_id: str, query: str, task_type: str, pool: str | None) -> dict:
    from memory_runtime import context_for

    try:
        packet = context_for(query, task_type=task_type, pool=pool, max_chars=16000, limit=8)
        citations = packet.get("citations") or []
        warnings = [str(item)[:240] for item in (packet.get("warnings") or [])[:12]]
        return {
            "track_id": track_id,
            "status": _status(citations, warnings),
            "citation_count": len(citations),
            "citation_kinds": sorted({str(item.get("kind", "unknown")) for item in citations}),
            "source_ids": [str(item.get("source_id", ""))[:160] for item in citations[:12]],
            "warnings": warnings,
            "data_sufficiency": packet.get("data_sufficiency", "unknown"),
            "pool": packet.get("pool", {}).get("label") if isinstance(packet.get("pool"), dict) else None,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:  # one unavailable pool should not erase the others
        return {"track_id": track_id, "status": "error", "citation_count": 0,
                "citation_kinds": [], "source_ids": [],
                "warnings": [f"Retrieval failed: {type(exc).__name__}"],
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest()}


def _vector_drill() -> dict:
    """Run one fixed, local-only semantic search against the existing Milvus DB."""
    if not (MEMSEARCH_PYTHON.is_file() and MEMSEARCH_ADAPTER.is_file()):
        return {"track_id": "vector_rag", "status": "unavailable", "local_only": True,
                "citation_count": 0, "sources": [], "warnings": ["Existing local adapter is unavailable."]}
    env = os.environ.copy()
    env.update({
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "TEMP": "H:/NEXEN/temp",
        "TMP": "H:/NEXEN/temp",
        "HF_HOME": "H:/NEXEN/cache/huggingface",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DO_NOT_TRACK": "1",
    })
    command = [str(MEMSEARCH_PYTHON), "-B", str(MEMSEARCH_ADAPTER), "--query", VECTOR_QUERY]
    try:
        completed = subprocess.run(command, cwd=str(INTEGRATIONS), env=env, shell=False,
                                   capture_output=True, text=True, timeout=VECTOR_TIMEOUT_SECONDS,
                                   check=False)
    except subprocess.TimeoutExpired:
        return {"track_id": "vector_rag", "status": "timeout", "local_only": True,
                "citation_count": 0, "sources": [], "warnings": ["Local vector search exceeded its 90 second limit."]}
    except OSError as exc:
        return {"track_id": "vector_rag", "status": "unavailable", "local_only": True,
                "citation_count": 0, "sources": [], "warnings": [f"Local vector search could not start: {type(exc).__name__}"]}
    if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
        return {"track_id": "vector_rag", "status": "error", "local_only": True,
                "citation_count": 0, "sources": [], "warnings": ["Local vector adapter returned an unusable result."]}
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError):
        return {"track_id": "vector_rag", "status": "error", "local_only": True,
                "citation_count": 0, "sources": [], "warnings": ["Local vector adapter returned invalid JSON."]}
    results = payload.get("results") if isinstance(payload, dict) else None
    results = results if isinstance(results, list) else []
    # Only metadata is retained. Recalled text stays inside the local adapter.
    sources = [Path(str(item.get("source", ""))).name for item in results[:5]
               if isinstance(item, dict) and Path(str(item.get("source", ""))).name in VECTOR_ALLOWED_SOURCES]
    passed = payload.get("local_only") is True and bool(sources) and sources[0] == VECTOR_EXPECTED_SOURCE
    return {"track_id": "vector_rag", "status": "pass" if passed else ("no_evidence" if not sources else "partial"),
            "local_only": payload.get("local_only") is True, "citation_count": len(sources),
            "sources": sources, "expected_top_source": VECTOR_EXPECTED_SOURCE,
            "warnings": [] if passed else ["Top result did not match the bounded source-grounded exercise."]}


def _orchestration_drill(db) -> dict:
    """Practice workflow readiness checks against the real catalog, without running cards."""
    evidence = _retrieval_drill(
        "orchestration", "workflow prepared versus executed task receipt and stop evidence",
        "workflow", "automation")
    try:
        from workflow_workspace import WorkflowWorkspace

        catalog = WorkflowWorkspace(db).catalog(compact=True)
        cards = catalog.get("cards") if isinstance(catalog, dict) else None
        cards = cards if isinstance(cards, list) else []
        missing_run_action = gate_mismatches = missing_disabled_reason = 0
        run_enabled = run_blocked = 0
        for card in cards:
            if not isinstance(card, dict):
                missing_run_action += 1
                continue
            actions = card.get("actions")
            action = next((item for item in actions if isinstance(item, dict) and item.get("id") == "run"), None) \
                if isinstance(actions, list) else None
            if action is None:
                missing_run_action += 1
                continue
            local = card.get("local_execution") or {}
            expected_enabled = bool(local.get("enabled")) if local else bool(card.get("launch_ready"))
            actual_enabled = bool(action.get("enabled"))
            if actual_enabled != expected_enabled:
                gate_mismatches += 1
            if actual_enabled:
                run_enabled += 1
            else:
                run_blocked += 1
                if not str(action.get("reason") or "").strip():
                    missing_disabled_reason += 1

        coverage = catalog.get("coverage") if isinstance(catalog, dict) else {}
        catalog_errors = coverage.get("errors") if isinstance(coverage, dict) else None
        catalog_error_count = len(catalog_errors) if isinstance(catalog_errors, list) else 0
        executed = bool(catalog.get("executed", False)) if isinstance(catalog, dict) else True
        passed = bool(cards) and not (missing_run_action or gate_mismatches or missing_disabled_reason) \
            and not executed and catalog_error_count == 0 and evidence.get("status") == "pass"
        status = "pass" if passed else ("error" if not cards or missing_run_action or gate_mismatches
                                        or missing_disabled_reason or executed else "partial")
        warnings = list(evidence.get("warnings", []))
        if catalog_error_count:
            warnings.append(f"Workflow catalog reports {catalog_error_count} metadata errors.")
        if missing_run_action:
            warnings.append(f"{missing_run_action} catalog cards lack a Run action.")
        if gate_mismatches:
            warnings.append(f"{gate_mismatches} Run actions do not match their readiness gate.")
        if missing_disabled_reason:
            warnings.append(f"{missing_disabled_reason} disabled Run actions lack a reason.")
        if executed:
            warnings.append("Catalog reported an execution; read-only practice requires zero executions.")
        return {
            **{key: value for key, value in evidence.items() if key != "status"},
            "track_id": "orchestration", "status": status,
            "catalog_card_count": len(cards), "run_enabled": run_enabled,
            "run_blocked": run_blocked, "missing_run_action": missing_run_action,
            "gate_mismatches": gate_mismatches,
            "missing_disabled_reason": missing_disabled_reason,
            "catalog_error_count": catalog_error_count,
            "execution_performed": False, "warnings": warnings,
            "evidence_note": "Checked readiness and reason gates on the real workflow catalog; no workflow was executed.",
        }
    except Exception as exc:
        return {**{key: value for key, value in evidence.items() if key != "status"},
                "track_id": "orchestration", "status": "error",
                "catalog_card_count": 0, "run_enabled": 0, "run_blocked": 0,
                "missing_run_action": 0, "gate_mismatches": 0,
                "missing_disabled_reason": 0, "catalog_error_count": 1,
                "execution_performed": False,
                "warnings": [f"Read-only workflow catalog drill failed: {type(exc).__name__}"],
                "evidence_note": "No workflow was executed."}


def _memory_base_coverage_drill(db) -> dict:
    """Report every known memory base and surface anything MARVIN cannot retrieve."""
    try:
        bases = _memory_bases(db)
        vector = _vector_inventory()
        unavailable = [item["id"] for item in bases if not item.get("available")]
        disconnected = [item["id"] for item in bases
                        if item.get("available") and not item.get("connected_to_shared_retrieval")]
        if not vector.get("installed") or not vector.get("adapter_available"):
            unavailable.append("vector_db")
        passed = not unavailable and not disconnected
        warnings = []
        if disconnected:
            warnings.append("Available memory bases are not connected to MARVIN shared retrieval: "
                            + ", ".join(disconnected) + ".")
        if unavailable:
            warnings.append("Memory bases or adapters could not be verified: " + ", ".join(unavailable) + ".")
        if vector.get("installed") and vector.get("adapter_available") and not vector.get("connected_to_marvin_chat"):
            warnings.append("The local vector index is practice-only and is not connected to MARVIN chat.")
        return {"track_id": "memory_base_coverage", "status": "pass" if passed else "partial",
                "citation_count": 0, "base_count": len(bases) + 1,
                "available_base_count": sum(bool(item.get("available")) for item in bases)
                    + int(bool(vector.get("installed")) and bool(vector.get("adapter_available"))),
                "retrieval_connected_bases": [item["id"] for item in bases
                    if item.get("available") and item.get("connected_to_shared_retrieval")],
                "disconnected_bases": disconnected,
                "unavailable_bases": unavailable,
                "vector_db": {key: vector.get(key) for key in
                    ("installed", "records", "adapter_available", "connected_to_marvin_chat")},
                "warnings": warnings,
                "evidence_note": "Inventory check only; disconnected or unverified stores remain excluded from MARVIN chat."}
    except Exception as exc:
        return {"track_id": "memory_base_coverage", "status": "error", "citation_count": 0,
                "base_count": 0, "available_base_count": 0, "retrieval_connected_bases": [],
                "disconnected_bases": [], "unavailable_bases": [],
                "warnings": [f"Memory base inventory failed: {type(exc).__name__}"],
                "evidence_note": "Memory base coverage is unverified."}


def _ensure_schema(db) -> None:
    with db.connect() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS marvin_training_runs(
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, status TEXT NOT NULL,
          result_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_marvin_training_runs_created
          ON marvin_training_runs(created_at DESC);
        CREATE TABLE IF NOT EXISTS marvin_training_task_links(
          seed_key TEXT PRIMARY KEY, task_id INTEGER NOT NULL,
          kind TEXT NOT NULL, track_id TEXT NOT NULL, created_at TEXT NOT NULL);
        """)


def _record_run(db, scope: str, drills: list[dict]) -> dict:
    statuses = [item.get("status") for item in drills]
    overall = "pass" if statuses and all(item == "pass" for item in statuses) else (
        "error" if statuses and all(item == "error" for item in statuses) else "partial")
    result = {"drills": drills, "drill_count": len(drills), "pass_count": statuses.count("pass"),
              "partial_count": statuses.count("partial"),
              "no_evidence_count": statuses.count("no_evidence"),
              "error_count": statuses.count("error") + statuses.count("timeout") + statuses.count("unavailable")}
    run_id = str(uuid.uuid4())
    with db.connect() as connection:
        connection.execute("INSERT INTO marvin_training_runs(id,scope,status,result_json,created_at) VALUES(?,?,?,?,?)",
                           (run_id, scope, overall, json.dumps(result, ensure_ascii=False), _now()))
    return {"id": run_id, "scope": scope, "status": overall, **result}


def _run_practice(db, scope: str) -> dict:
    drills: list[dict] = []
    if scope in ("full", "memory"):
        from memory_pools import POOLS
        for pool_id, (query, task_type) in MEMORY_DRILLS.items():
            if pool_id not in POOLS:
                drills.append({"track_id": pool_id, "status": "error", "citation_count": 0,
                               "citation_kinds": [], "source_ids": [], "warnings": ["Pool is not registered."]})
            else:
                drills.append(_retrieval_drill(pool_id, query, task_type, pool_id))
        drills.append(_memory_base_coverage_drill(db))
    if scope in ("full", "businesses"):
        for business in BUSINESS_TRACKS:
            item = _retrieval_drill(business["id"], business["query"], business["task_type"], "all")
            item["business"] = business["name"]
            drills.append(item)
    if scope in ("full", "orchestration"):
        drills.append(_orchestration_drill(db))
    if scope in ("full", "vector_rag"):
        drills.append(_vector_drill())
    return _record_run(db, scope, drills)


def _memory_bases(db) -> list[dict]:
    bases = []
    try:
        with db.connect() as connection:
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, label, used in (("files", "Indexed source files", True),
                                       ("chunks", "Searchable file chunks", True),
                                       ("completion_memory", "Completion history", True),
                                       ("knowledge_items", "Additional knowledge records", False)):
                count = int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) if table in table_names else None
                bases.append({"id": table, "name": label, "available": table in table_names,
                              "records": count, "connected_to_shared_retrieval": used})
    except Exception as exc:
        bases.append({"id": "app_memory", "name": "NEXEN app memory", "available": False,
                      "records": None, "connected_to_shared_retrieval": False,
                      "note": type(exc).__name__})
    try:
        from memory_bridge import readonly
        from memory_runtime import shared_memory
        exports = shared_memory().export_db
        with readonly(exports) as connection:
            count = int(connection.execute("SELECT count(*) FROM messages").fetchone()[0])
        bases.append({"id": "conversation_exports", "name": "Conversation exports", "available": True,
                      "records": count, "connected_to_shared_retrieval": True})
    except Exception as exc:
        bases.append({"id": "conversation_exports", "name": "Conversation exports", "available": False,
                      "records": None, "connected_to_shared_retrieval": True,
                      "note": type(exc).__name__})
    try:
        from memory_runtime import shared_memory
        note_index = shared_memory().vault / "NEXEN Shared Memory" / "manual-index.json"
        if note_index.is_file() and not note_index.is_symlink() and note_index.stat().st_size <= 8 * 1024 * 1024:
            payload = json.loads(note_index.read_text(encoding="utf-8"))
            notes = payload.get("notes") if payload.get("owner") == "nexen-memory-bridge-v1" else []
            bases.append({"id": "manual_notes", "name": "Approved manual notes", "available": True,
                          "records": len(notes) if isinstance(notes, list) else 0,
                          "connected_to_shared_retrieval": True})
        else:
            bases.append({"id": "manual_notes", "name": "Approved manual notes", "available": False,
                          "records": None, "connected_to_shared_retrieval": True})
    except Exception as exc:
        bases.append({"id": "manual_notes", "name": "Approved manual notes", "available": False,
                      "records": None, "connected_to_shared_retrieval": True,
                      "note": type(exc).__name__})
    return bases


def _vector_inventory() -> dict:
    collection = INTEGRATIONS / "memsearch-data/nexen-derived.db/collections/nexen_owned_notes_v1"
    manifest_path = collection / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        count = int(manifest.get("current_seq", 0))
        ready = MEMSEARCH_PYTHON.is_file() and MEMSEARCH_ADAPTER.is_file() and count > 0
        return {"installed": True, "collection": "nexen_owned_notes_v1", "records": count,
                "local_embedding_model": "nexen-embedding-cpu:latest", "adapter_available": ready,
                "query_scope": "Four allowlisted Markdown notes; not the full NEXEN corpus.",
                "connected_to_marvin_chat": False,
                "practice_route": "Local read-only RAG drill is available." if ready else "Adapter is not ready."}
    except (OSError, ValueError, TypeError):
        installed = MEMSEARCH_PYTHON.is_file()
        return {"installed": installed, "collection": "nexen_owned_notes_v1", "records": None,
                "local_embedding_model": "nexen-embedding-cpu:latest", "adapter_available": False,
                "query_scope": "Unverified", "connected_to_marvin_chat": False,
                "practice_route": "Unavailable until the existing index is verified."}


def _ingestion_inventory(db) -> dict:
    counts = {}
    total = 0
    try:
        with db.connect() as connection:
            rows = connection.execute("SELECT state,count(*) FROM source_queue GROUP BY state").fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        total = sum(counts.values())
    except Exception:
        pass
    paused = PAUSE_MARKER.is_file()
    reason = ""
    if paused:
        try:
            reason = PAUSE_MARKER.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            reason = "Main source indexing remains paused."
    indexed = counts.get("indexed", 0) + counts.get("indexed_partial", 0)
    return {"paused": paused, "pause_reason": reason, "tracked_items": total,
            "states": counts, "indexed_items": indexed, "coverage_complete": False,
            "complete_claim": False,
            "next_gate": "Keep indexing held until the F: preservation and storage-recovery receipt is verified.",
            "automatic_resume": False}


def _recent_runs(db) -> list[dict]:
    try:
        with db.connect() as connection:
            rows = connection.execute("SELECT id,scope,status,result_json,created_at FROM marvin_training_runs ORDER BY created_at DESC LIMIT 12").fetchall()
        return [{"id": row[0], "scope": row[1], "status": row[2],
                 "result": json.loads(row[3]), "created_at": row[4]} for row in rows]
    except Exception:
        return []


def _recent_tasks(db) -> list[dict]:
    try:
        with db.connect() as connection:
            rows = connection.execute("""SELECT r.id,r.text,r.status,l.kind,l.track_id,l.created_at
                FROM marvin_training_task_links l JOIN hub_requests r ON r.id=l.task_id
                ORDER BY l.created_at DESC LIMIT 12""").fetchall()
        return [{"id": int(row[0]), "text": str(row[1]), "status": str(row[2]),
                 "kind": str(row[3]), "track_id": str(row[4]), "created_at": str(row[5])} for row in rows]
    except Exception:
        return []


def _create_linked_task(db, kind: str, track_id: str, title: str, next_step: str) -> dict:
    from task_tracking import TaskCreate, Tracker

    seed = f"marvin-training-{kind}-{track_id}-v1"
    task_id = Tracker(db).create(TaskCreate(text=title, priority="normal", next_step=next_step),
                                 seed_key=seed, initial_status="planned")
    with db.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO marvin_training_task_links(seed_key,task_id,kind,track_id,created_at) VALUES(?,?,?,?,?)",
                           (seed, int(task_id), kind, track_id, _now()))
    task = Tracker(db).get(int(task_id))
    return {"id": int(task_id), "text": task["text"], "status": task["status"], "track_id": track_id}


def _research_selection(scope: str, business_id: str | None) -> list[dict]:
    if scope == "all_businesses":
        return list(BUSINESS_TRACKS)
    selected = [item for item in BUSINESS_TRACKS if item["id"] == business_id]
    if not selected:
        raise HTTPException(422, "Choose a registered MARVIN business track.")
    return selected


def register(app, db):
    from pc_control import validate_request

    _ensure_schema(db)

    @app.get("/marvin/training", response_class=HTMLResponse)
    def marvin_training_page(request: Request):
        validate_request(request)
        return HTMLResponse((BASE / "marvin-training.html").read_text(encoding="utf-8"))

    @app.get("/api/marvin/training/state")
    def marvin_training_state(request: Request):
        validate_request(request)
        from memory_pools import POOLS
        pools = [{"id": key, "name": value["label"], "query_ready": key in MEMORY_DRILLS}
                 for key, value in POOLS.items()]
        workflows = {"cards": None, "executions": None}
        try:
            with db.connect() as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "workflows" in tables:
                    workflows["cards"] = int(connection.execute("SELECT count(*) FROM workflows").fetchone()[0])
                if "workflow_local_runs" in tables:
                    workflows["executions"] = int(connection.execute("SELECT count(*) FROM workflow_local_runs").fetchone()[0])
        except Exception:
            pass
        return {"identity": "MARVIN", "memory_pools": pools, "memory_bases": _memory_bases(db),
                "business_tracks": [{"id": item["id"], "name": item["name"]} for item in BUSINESS_TRACKS],
                "vector_db": _vector_inventory(), "ingestion": _ingestion_inventory(db),
                "orchestration": {**workflows, "execution_scope": "Read-only practice; no workflow executed."},
                "runs": _recent_runs(db), "tasks": _recent_tasks(db),
                "training_is": "repeatable local drills with citation metadata; this does not fine-tune a model.",
                "business_research_is": "persistent research tasks; queued tasks are not completed research."}

    @app.post("/api/marvin/training/practice")
    def marvin_training_practice(body: PracticeRequest, request: Request):
        validate_request(request, mutation=True)
        try:
            return _run_practice(db, body.scope)
        except Exception as exc:
            raise HTTPException(500, f"MARVIN practice could not finish ({type(exc).__name__}).") from exc

    @app.post("/api/marvin/training/research")
    def marvin_training_research(body: ResearchRequest, request: Request):
        validate_request(request, mutation=True)
        selected = _research_selection(body.scope, body.business_id)
        tasks = []
        for item in selected:
            title = f"MARVIN research and practice: {item['name']}"
            next_step = ("Review current NEXEN decisions and task evidence, retrieve the related indexed knowledge, "
                         "then research current external facts with dated citations. Record unknowns and conflicts. "
                         "Do not spend, publish, contact people, or claim research complete without saved evidence.")
            tasks.append(_create_linked_task(db, "research", item["id"], title, next_step))
        return {"status": "planned", "tasks": tasks,
                "message": "Persistent tasks created or reused. No external research has run yet."}

    @app.post("/api/marvin/training/code-practice")
    def marvin_code_practice(request: Request):
        validate_request(request, mutation=True)
        title = "MARVIN coding practice: bounded validator challenge with regression evidence"
        next_step = ("Use a synthetic fixture to implement a small bounded citation/input validator; include valid, "
                     "malformed, oversized, timeout, and redaction cases; run the focused tests and inspect outputs. "
                     "Return a patch and test evidence. Do not deploy or alter production state.")
        task = _create_linked_task(db, "code", "validator_challenge", title, next_step)
        return {"status": task["status"], "task": task,
                "message": "Coding drill is in the task queue; it has not run yet."}

    return {"state": _recent_runs, "practice": _run_practice}
