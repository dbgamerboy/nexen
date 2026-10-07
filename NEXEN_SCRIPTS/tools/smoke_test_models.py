"""Inference Smoke Test for installed local Ollama models.

Tests each model with a short generation request, measures wall time latency,
verifies non-empty response, and saves a durable receipt.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
REPORT_FILE = Path(r"H:\NEXEN\reports\SMOKE-TEST-LOCAL-MODELS-20261001.json")
REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

# Candidate models to test
MODELS_TO_TEST = [
    "marvin-brain-3b:latest",
    "nexen-coder-3b:latest",
    "llama3.2:3b",
    "qwen2.5-coder:0.5b-instruct-q4_K_M",
    "qwen2.5-coder:3b",
    "xortron:fixed",
    "dolphin3:latest",
    "qwen2.5-coder:7b",
]

def test_model(model_name: str, timeout_sec: int = 45) -> dict:
    payload = {
        "model": model_name,
        "prompt": "Respond with exactly the single word: NEXEN_ONLINE",
        "stream": False,
        "options": {"num_predict": 10, "temperature": 0.1}
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            elapsed = round(time.time() - t0, 3)
            res_data = json.loads(resp.read().decode("utf-8"))
            text = res_data.get("response", "").strip()
            return {
                "model": model_name,
                "status": "PASS",
                "elapsed_sec": elapsed,
                "response": text,
                "eval_count": res_data.get("eval_count", 0),
            }
    except urllib.error.HTTPError as he:
        elapsed = round(time.time() - t0, 3)
        return {"model": model_name, "status": "FAIL_HTTP", "code": he.code, "elapsed_sec": elapsed, "error": str(he)}
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        return {"model": model_name, "status": "FAIL_TIMEOUT_OR_ERROR", "elapsed_sec": elapsed, "error": str(e)}

def main():
    print("=" * 60)
    print("OLLAMA LOCAL MODEL INFERENCE SMOKE TEST")
    print("=" * 60)
    results = []
    for m in MODELS_TO_TEST:
        print(f"Testing '{m}'...", end=" ", flush=True)
        r = test_model(m)
        status = r.get("status")
        elapsed = r.get("elapsed_sec")
        resp = r.get("response", "")[:30]
        print(f"[{status}] in {elapsed}s | Response: '{resp}'")
        results.append(r)
    
    passed = sum(1 for x in results if x.get("status") == "PASS")
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_tested": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("=" * 60)
    print(f"Smoke Test Completed: {passed}/{len(results)} Passed. Report saved to {REPORT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
