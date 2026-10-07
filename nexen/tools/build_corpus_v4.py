"""Build the combined MARVIN training corpus: the existing master dataset (read-only) plus the V4 spine shard.

The master dataset at H:\\NEXEN\\finetune\\marvin-dataset belongs to another session and is never modified. This writes a NEW
corpus folder the existing trainer can read with --corpus. The spine shard is behavior data (diagnosis, premortem, rules,
identity), repeated a few times so 192 rows are not drowned by 30,000. Eval is the master eval plus the spine's held-out rows.
It does not start training: the trainer honors global STOP and needs a free GPU.
"""
import json
import sys
import time
from pathlib import Path

MASTER = Path(r"H:\NEXEN\finetune\marvin-dataset")
SHARD = Path(r"H:\NEXEN-ENTERPRISE\Data\V4\finetune")
OUT = Path(r"H:\NEXEN-ENTERPRISE\Data\V4\finetune\corpus-v4")


def main(repeat=4):
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {"master_train": 0, "spine_sft": 0, "master_eval": 0, "spine_eval": 0}
    with open(OUT / "train.jsonl", "w", encoding="utf-8", newline="\n") as out:
        with open(MASTER / "train.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                out.write(line if line.endswith("\n") else line + "\n")
                counts["master_train"] += 1
        rows = (SHARD / "spine_sft.jsonl").read_text(encoding="utf-8").splitlines()
        for _ in range(repeat):
            for line in rows:
                out.write(line + "\n")
                counts["spine_sft"] += 1
    with open(OUT / "eval.jsonl", "w", encoding="utf-8", newline="\n") as out:
        with open(MASTER / "eval.jsonl", "r", encoding="utf-8") as fh:
            for line in fh:
                out.write(line if line.endswith("\n") else line + "\n")
                counts["master_eval"] += 1
        for line in (SHARD / "spine_eval.jsonl").read_text(encoding="utf-8").splitlines():
            out.write(line + "\n")
            counts["spine_eval"] += 1
    (OUT / "menu_eval.json").write_bytes((MASTER / "menu_eval.json").read_bytes())
    manifest = {"built": time.strftime("%Y-%m-%d %H:%M:%S"), "counts": counts, "spine_repeat": repeat, "master": str(MASTER),
                "dpo_pairs": str(SHARD / "spine_dpo.jsonl"), "train_command": r"H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe H:\NEXEN\finetune\train_qlora.py --corpus " + str(OUT),
                "note": "Training is not started. The trainer honors global STOP (H:\\NEXEN\\loop\\STOP) and the eval gate: a tuned model ships only if it beats the base."}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 4), indent=2))
