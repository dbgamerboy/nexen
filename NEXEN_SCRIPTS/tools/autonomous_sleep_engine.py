"""Local sleep-engine preflight; remote training/registration/shutdown are unconnected.

This patch produces truthful local status only. It never rents, trains remotely,
registers a placeholder model, or claims provider termination. Local ticket
execution is disabled by default pending admission through canonical NEXEN.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(r"H:\NEXEN\state")
SLEEP_STATUS_FILE = STATE_DIR / "sleep_engine_status.json"
SLEEP_RECEIPTS_FILE = STATE_DIR / "sleep_mode_receipts.jsonl"


class AutonomousSleepEngine:
    def __init__(self, rental_hours=2.0, cloud_host="", base_model="Qwen2.5-Coder-7B-Instruct",
                 *, state_dir=None, dataset_path=None, allow_local_tickets=False,
                 python_exe=None, ticket_engine=None):
        if isinstance(rental_hours, bool) or not math.isfinite(float(rental_hours)) or float(rental_hours) <= 0:
            raise ValueError("rental_hours must be a finite positive number")
        self.rental_seconds = int(float(rental_hours) * 3600)
        self.start_time = time.time()
        self.deadline_time = self.start_time + self.rental_seconds - 300
        self.cloud_host = cloud_host
        self.base_model = base_model
        self.state_dir = Path(state_dir) if state_dir is not None else STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.state_dir / "sleep_engine_status.json"
        self.receipts_file = self.state_dir / "sleep_mode_receipts.jsonl"
        self.dataset_path = Path(dataset_path) if dataset_path is not None else Path(
            r"H:\NEXEN\models\heavy\datasets\05_goldmine_master_v3_supercharged.jsonl")
        self.python_exe = Path(python_exe) if python_exe is not None else Path(sys.executable)
        self.ticket_engine = Path(ticket_engine) if ticket_engine is not None else Path(r"H:\NEXEN\tickets\ticket_engine.py")
        self.allow_local_tickets = allow_local_tickets is True
        self.outcomes = {}
        self.tickets_to_run = ["bbl_jeans_ecom_deployment", "content_viral_optimizer",
                               "dropshipping_product_research", "synthetic_phone_farm_orchestrator",
                               "model_finetuning_dataset"]

    def log_receipt(self, task_name, status, details):
        self.outcomes[task_name] = status
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "epoch": time.time(),
                 "task": task_name, "status": status, "details": details}
        with self.receipts_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def update_status(self, phase, progress_pct, msg):
        remaining = max(0, int(self.deadline_time - time.time()))
        status = {"phase": phase, "progress_percent": progress_pct, "message": msg,
                  "remaining_seconds": remaining,
                  "remaining_formatted": f"{remaining // 3600}h {(remaining % 3600) // 60}m {remaining % 60}s",
                  "cloud_host_configured": bool(self.cloud_host), "base_model": self.base_model,
                  "active": remaining > 0 and phase not in {"BLOCKED", "FAILED", "CANCELLED", "COMPLETED"},
                  "cloud_training_verified": False, "model_registration_verified": False,
                  "provider_shutdown_verified": False, "outcomes": dict(self.outcomes)}
        status['updated_at'] = datetime.now(timezone.utc).isoformat()
        # The existing dashboard reads this JSON concurrently. Publish complete
        # status or preserve the previous generation if replace fails.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.state_dir,
                                             prefix='.sleep-status-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(status, indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.status_file)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return status

    def run_local_revenue_tickets(self):
        if not self.allow_local_tickets:
            self.log_receipt("local_ticket_dispatch", "blocked", {"reason": "Canonical admission required; legacy dispatch disabled by default"})
            return
        if not self.python_exe.is_file() or not self.ticket_engine.is_file():
            self.log_receipt("local_ticket_dispatch", "blocked", {"reason": "Local executable or ticket engine missing"})
            return
        for idx, ticket_id in enumerate(self.tickets_to_run):
            remaining = self.deadline_time - time.time()
            if remaining <= 0:
                self.log_receipt(ticket_id, "skipped_time_limit", {"reason": "Deadline cutoff"})
                break
            self.update_status("RUNNING_LOCAL_TICKETS", 0, "Admitted local ticket attempt; result unverified")
            try:
                result = subprocess.run([str(self.python_exe), str(self.ticket_engine), "run", ticket_id],
                                        shell=False, capture_output=True, text=True, timeout=min(120, remaining))
                # The current legacy ticket engine prints model text and can exit 0 on
                # swallowed errors. A zero exit is NOT canonical task completion.
                self.log_receipt(ticket_id, "executed_unverified" if result.returncode == 0 else "failed",
                                 {"returncode": result.returncode, "stdout_chars": len(result.stdout or ""),
                                  "stderr_chars": len(result.stderr or "")})
            except subprocess.TimeoutExpired:
                self.log_receipt(ticket_id, "failed", {"reason": "Local subprocess timeout"})
            except OSError as exc:
                self.log_receipt(ticket_id, "failed", {"reason": type(exc).__name__})

    def orchestrate_cloud_finetuning(self):
        # Metadata/format inspection is not dataset rights review or training proof.
        try:
            digest = hashlib.sha256()
            records = 0
            with self.dataset_path.open("rb") as f:
                for line in f:
                    digest.update(line)
                    if line.strip():
                        item = json.loads(line)
                        if not isinstance(item, dict):
                            raise ValueError("Dataset record is not an object")
                        records += 1
            if records == 0:
                raise ValueError("Empty dataset")
            self.log_receipt("dataset_verification", "inspected", {"sha256": digest.hexdigest(),
                             "bytes": self.dataset_path.stat().st_size, "records": records,
                             "rights_reviewed": False, "training_verified": False})
        except (OSError, ValueError, UnicodeError) as exc:
            self.log_receipt("dataset_verification", "blocked", {"reason": type(exc).__name__})
        self.log_receipt("cloud_qlora_training", "blocked", {"reason": "No authenticated trainer/job/output adapter; no cloud operation performed"})
        self.update_status("BLOCKED", 0, "Cloud training unconnected; dataset inspection is local only")

    def register_local_model(self):
        self.log_receipt("ollama_registration", "blocked", {"reason": "No verified returned artifact/hash and evaluated model; placeholder registration disabled"})
        self.update_status("BLOCKED", 0, "No trained artifact registered")

    def safe_shutdown_and_serve(self):
        self.log_receipt("provider_shutdown", "unknown", {"reason": "No provider termination adapter or receipt; rental shutdown NOT VERIFIED"})
        phase = "FAILED" if "failed" in self.outcomes.values() else "BLOCKED"
        self.log_receipt("overnight_completion", phase.lower(), {"reason": "Required stages are not independently verified"})
        self.update_status(phase, 0, "Local cycle ended; cloud training, registration and rental termination are unverified")
        return 1 if phase == "FAILED" else 2

    def execute_all(self):
        self.update_status("INITIALIZING", 0, "Local preflight; cloud operations unconnected")
        try:
            self.run_local_revenue_tickets()
            self.orchestrate_cloud_finetuning()
            self.register_local_model()
            return self.safe_shutdown_and_serve()
        except KeyboardInterrupt:
            self.log_receipt("overnight_completion", "cancelled", {"reason": "Local interruption; provider termination unverified"})
            self.update_status("CANCELLED", 0, "Interrupted locally; cloud rental state unknown")
            return 130


if __name__ == "__main__":
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    host = sys.argv[2] if len(sys.argv) > 2 else ""
    model = sys.argv[3] if len(sys.argv) > 3 else "Qwen2.5-Coder-7B-Instruct"
    sys.exit(AutonomousSleepEngine(hours, host, model).execute_all())
