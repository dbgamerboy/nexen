import subprocess, sys, os

# Wrapper for QLoRA fine‑tuning. It forwards arguments to the existing package_master_finetune.py script.
# Expected args (as used by run_ingest.py):
#   --model <model_name> --data <jsonl_path> --output <out_dir> --epochs <int> --lr <float> --lora_rank <int>

if __name__ == "__main__":
    # Resolve the path to the real script (located in the repo under tools)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script_path = os.path.join(base_dir, "tools", "package_master_finetune.py")
    if not os.path.isfile(script_path):
        sys.stderr.write(f"[ERROR] package_master_finetune.py not found at {script_path}\n")
        sys.exit(1)
    # Build the command: python package_master_finetune.py <original args>
    cmd = [sys.executable, script_path] + sys.argv[1:]
    # Run synchronously, streaming output to stdout/stderr
    proc = subprocess.run(cmd, check=False)
    sys.exit(proc.returncode)
