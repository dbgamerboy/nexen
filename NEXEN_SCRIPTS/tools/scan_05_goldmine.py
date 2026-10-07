"""Ultra-Fast 05_AI Goldmine Scanner & Training Dataset Extractor.

Scans the high-signal curated directories in F:\\05_AI in seconds:
1. F:\\05_AI\\01_EXACT_PROMPTS_AND_CHATS (Winning prompts and master packs)
2. F:\\05_AI\\04_BUSINESS (Dropshipping, money projects, inventory)
3. F:\\05_AI\\OnlyScams Ingest (Make N8N Workflows Uncensored) (172 automation methods)
4. F:\\05_AI\\03_NEXEN (Approval loops, autopilot systems, configs)

Formats the text into structured JSONL chat completion training pairs
ready for immediate QLoRA / LoRA fine-tuning tonight.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DATASET = Path(r"H:\NEXEN\models\heavy\datasets\05_goldmine_training.jsonl")
OUTPUT_DATASET.parent.mkdir(parents=True, exist_ok=True)

TARGET_DIRS = [
    r"F:\05_AI\01_EXACT_PROMPTS_AND_CHATS",
    r"F:\05_AI\04_BUSINESS",
    r"F:\05_AI\OnlyScams Ingest (Make N8N Workflows Uncensored)",
    r"F:\05_AI\03_NEXEN",
]


def extract_training_pairs() -> list[dict]:
    pairs = []
    scanned_files = 0
    total_bytes = 0

    print("=" * 65)
    print("FAST 05_AI GOLDMINE SCANNER")
    print("=" * 65)

    for target in TARGET_DIRS:
        if not os.path.exists(target):
            print(f"Skipping (not found): {target}")
            continue
        print(f"Scanning: {target}...")
        for root, dirs, files in os.walk(target):
            # Skip hidden or redundant folders
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".trash"]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in [".md", ".txt", ".json", ".csv"]:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        # Skip giant raw dumps > 10MB to keep dataset high-density
                        if 100 < sz < 5_000_000:
                            scanned_files += 1
                            total_bytes += sz
                            with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                                content = fh.read().strip()
                            
                            if not content:
                                continue
                            
                            # Clean and format into instruction pair
                            prompt_title = f.replace("_", " ").replace("-", " ")
                            if ext == ".csv":
                                # Extract sample prompts from CSV
                                try:
                                    reader = csv.reader(content.splitlines())
                                    for row in list(reader)[:15]:
                                        if row and len(" ".join(row)) > 20:
                                            pairs.append({
                                                "messages": [
                                                    {"role": "system", "content": "You are NEXEN-CORE, an autonomous operations and money engine for the owner."},
                                                    {"role": "user", "content": f"Execute prompt from {f}: " + row[0][:200]},
                                                    {"role": "assistant", "content": " ".join(row[1:])[:600] if len(row) > 1 else "Deterministic workflow initialized."}
                                                ]
                                            })
                                except Exception:
                                    pass
                            else:
                                # Standard Markdown/Text chunks
                                chunks = [content[i:i+2500] for i in range(0, min(len(content), 10000), 2500)]
                                for idx, chunk in enumerate(chunks, 1):
                                    pairs.append({
                                        "messages": [
                                            {"role": "system", "content": "You are NEXEN-MASTER, specialized in autonomous business execution, uncensored workflows, and e-commerce systems."},
                                            {"role": "user", "content": f"Retrieve knowledge and workflow specs for: {prompt_title} (Section {idx})"},
                                            {"role": "assistant", "content": chunk}
                                        ]
                                    })
                    except Exception:
                        pass

    print("=" * 65)
    print(f"Scanned {scanned_files} high-signal files ({total_bytes / (1024*1024):.2f} MB).")
    print(f"Extracted {len(pairs)} formatted fine-tuning training pairs.")
    print("=" * 65)

    with open(OUTPUT_DATASET, "w", encoding="utf-8") as out:
        for p in pairs:
            out.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"✅ Training dataset generated at: {OUTPUT_DATASET} ({os.path.getsize(OUTPUT_DATASET)/(1024*1024):.2f} MB)")
    return pairs


if __name__ == "__main__":
    extract_training_pairs()
