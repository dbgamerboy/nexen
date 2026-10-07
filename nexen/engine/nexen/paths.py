"""Every path V4 touches, in one place. Environment variables override for tests."""
import os
from pathlib import Path


def _p(env, default):
    return Path(os.environ.get(env, default))


HOME = _p("NEXEN_HOME", r"H:\NEXEN-ENTERPRISE")
APP = _p("NEXEN_APP", str(Path(__file__).resolve().parents[2]))
DATA = _p("NEXEN_DATA", str(HOME / "Data" / "V4"))
MODULES = _p("NEXEN_MODULES", str(APP / "modules"))
UI = _p("NEXEN_UI", str(APP / "ui"))
LEARNING_DB = DATA / "learning.db"
STATE_DB = DATA / "state.db"
AUDIT_LOG = DATA / "audit.jsonl"

# V3 and shared sources: read-only for V4.
V3_APP = _p("NEXEN_V3_APP", r"H:\NEXEN\v1\app")
CANON_DB = _p("NEXEN_CANON_DB", str(V3_APP / "data" / "nexen.db"))
STOP_FILE = _p("NEXEN_STOP_FILE", r"H:\NEXEN\loop\STOP")
H_NEXEN = _p("NEXEN_H_NEXEN", r"H:\NEXEN")
KNOWLEDGE = _p("NEXEN_KNOWLEDGE", r"H:\NEXEN\knowledge")
HANDOFFS = _p("NEXEN_HANDOFFS", r"H:\NEXEN\handoffs")
VAULT_CANDIDATES = [
    Path(os.environ["NEXEN_VAULT"]) if "NEXEN_VAULT" in os.environ else Path(r"F:\NEXEN_MEMORY"),
    Path(r"H:\NEXEN\obsidian\NEXEN-Recovered-20261005"),
]
BIZ_OPS = _p("NEXEN_BIZOPS", str(HOME / "Apps" / "BusinessOperations"))
BIZ_INVENTORY = _p("NEXEN_BIZ_INVENTORY", r"H:\NEXEN\handoffs\business-operations-20261004")
PYTHON = _p("NEXEN_PYTHON", r"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe")
OLLAMA_URL = os.environ.get("NEXEN_OLLAMA", "http://127.0.0.1:11434")
N8N_URL = os.environ.get("NEXEN_N8N", "http://localhost:5678")
V3_CORE_URL = os.environ.get("NEXEN_V3_CORE", "http://127.0.0.1:8788")
PORT = int(os.environ.get("NEXEN_PORT", "8794"))

# Vector memory lives on the Google Drive mount so every machine sees the same index.
VECTOR_DIR = _p("NEXEN_VECTOR_DIR", r"G:\My Drive\NEXEN_VECTOR_DB")
QDRANT_DIR = _p("NEXEN_QDRANT_DIR", str(VECTOR_DIR / "Qdrant"))
GRAPHRAG_DIR = _p("NEXEN_GRAPHRAG_DIR", str(VECTOR_DIR / "GraphRAG"))
# Read-only ingest source for the new index.
INGEST_SRC = _p("NEXEN_INGEST_SRC", r"F:\05_AI")

# Older NEXEN lines on F: (metadata only; the drive is failing, reads are slow).
F_LEGACY = [
    r"F:\NEXEN", r"F:\NEXEN 1.1.2", r"F:\NEXEN master plan", r"F:\NEXEN_THIS_PC_ONLY_v4",
    r"F:\NEXEN_REV2", r"F:\NEXEN_MASTER", r"F:\NEXEN_CORE_20260907", r"F:\NEXEN_GAME",
    r"F:\NEXEN_AUTONOMY", r"F:\NEXEN_Autonomy_v0.1", r"F:\NEXEN_PLAN", r"F:\NEXEN_RECOVERY",
    r"F:\NEXEN_REINSTALL", r"F:\NEXEN_REALITY_COMPILER_V1", r"F:\NEXEN_WORK_SESSION_PACK_2026-09-11",
]


def vault():
    for candidate in VAULT_CANDIDATES:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def ensure_data():
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA
