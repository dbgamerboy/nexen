"""Hardware-Aware Adaptive Brain Tier Controller for NEXEN / MARVIN.

Continuously senses live CPU utilization, system RAM pressure, and NVIDIA GPU VRAM,
dynamically selecting the highest-capability brain tier that fits without
causing OOM crashes or frame drops.
"""
from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

STATE_DIR = Path(r"H:\NEXEN\state\model_router")
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATUS_FILE = STATE_DIR / "adaptive_brain_tier.json"
LOG_FILE = STATE_DIR / "adaptive_brain.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.adaptive_brain")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class AdaptiveBrainTier:
    """Monitors live hardware constraints and routes requests to the optimal model tier."""

    def __init__(self) -> None:
        pass

    def get_system_ram(self) -> Tuple[float, float, int]:
        """Returns (total_ram_gb, avail_ram_gb, memory_load_percent)."""
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_gb = round(stat.ullTotalPhys / (1024**3), 2)
        avail_gb = round(stat.ullAvailPhys / (1024**3), 2)
        load_pct = stat.dwMemoryLoad
        return total_gb, avail_gb, load_pct

    def get_gpu_vram(self) -> Tuple[int, int, int, int]:
        """Returns (total_vram_mb, free_vram_mb, used_vram_mb, gpu_util_pct)."""
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.free,memory.used,utilization.gpu", "--format=csv,nounits,noheader"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                parts = [int(p.strip()) for p in res.stdout.strip().split(",")]
                return parts[0], parts[1], parts[2], parts[3]
        except Exception as e:
            log.warning("Could not query nvidia-smi: %s", e)
        return 8192, 0, 8192, 100

    def is_gaming_active(self) -> bool:
        """Checks if a known gaming process or heavyweight GPU consumer is active."""
        try:
            # Query active processes for gaming executables (exclude background services and coding agents like codex)
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Process | Where-Object { $_.ProcessName -match '(?i)^(witcher|cyberpunk2077|forza|r5apex|valorant|fortnite|gta5|overwatch|cs2|warzone|starfield|eldenring)$' } | Select-Object -ExpandProperty ProcessName"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode == 0 and res.stdout.strip():
                games = [g.strip() for g in res.stdout.strip().splitlines() if g.strip()]
                return len(games) > 0
        except Exception:
            pass
        return False
        return False

    def select_optimal_brain(self) -> Dict[str, Any]:
        """Dynamically evaluates hardware conditions and selects the best model tier."""
        total_ram, avail_ram, mem_load = self.get_system_ram()
        total_vram, free_vram, used_vram, gpu_util = self.get_gpu_vram()
        gaming = self.is_gaming_active()

        log.info(
            "Hardware Telemetry: Free VRAM: %d MB | Avail RAM: %.2f GB (Load: %d%%) | GPU Util: %d%% | Gaming: %s",
            free_vram, avail_ram, mem_load, gpu_util, gaming
        )

        # LEVEL 4: Gaming / High Resource Contention Safe-Mode
        if gaming or free_vram < 1500:
            tier_name = "LEVEL_4_GAMING_LOW_RESOURCE"
            model_id = "qwen2.5-coder:0.5b-instruct-q4_K_M"
            coder_id = "qwen2.5-coder:0.5b-instruct-q4_K_M"
            rationale = "Gaming process or low VRAM detected. Preserving GPU frames, running lightweight model on CPU."
            target_device = "CPU"

        # LEVEL 1: Maximum Precision Beast Mode (Free VRAM >= 5200 MB AND available RAM >= 3.0 GB)
        elif free_vram >= 5200 and avail_ram >= 3.0:
            tier_name = "LEVEL_1_MAX_PRECISION_7B"
            model_id = "marvin-brain:latest"
            coder_id = "nexen-coder-v3:latest"
            rationale = "High VRAM headroom (>=5.2GB) and ample RAM. 7B high-capacity model selected for maximum reasoning depth."
            target_device = "GPU"

        # LEVEL 2: GPU-Accelerated Balanced Mode (VRAM >= 2200 MB)
        # 3B models reside 100% inside GPU VRAM (2.2GB), completely bypassing tight system RAM.
        elif free_vram >= 2200:
            tier_name = "LEVEL_2_GPU_ACCELERATED_BALANCED"
            model_id = "marvin-brain-3b:latest"
            coder_id = "nexen-coder-3b:latest"
            rationale = "GPU VRAM healthy (>=2.2GB). Tuned 3B models run 100% in GPU VRAM with 0.46s latency, zero RAM spillover."
            target_device = "100% GPU"

        else:
            tier_name = "LEVEL_3_BALANCED_FALLBACK"
            model_id = "llama3.2:3b"
            coder_id = "qwen2.5-coder:3b"
            rationale = "Moderate resource availability. Running compact 3B model."
            target_device = "GPU/CPU Split"

        # Check for active user override
        override_model = self.get_active_override()
        if override_model:
            model_id = override_model
            coder_id = override_model
            tier_name = "USER_SWAP_OVERRIDE"
            rationale = f"User explicitly requested or triggered model swap to {override_model}."

        decision = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": tier_name,
            "primary_model": model_id,
            "coder_model": locals().get("coder_id", model_id),
            "target_device": target_device,
            "rationale": rationale,
            "is_override": bool(override_model),
            "telemetry": {
                "free_vram_mb": free_vram,
                "total_vram_mb": total_vram,
                "avail_ram_gb": avail_ram,
                "total_ram_gb": total_ram,
                "ram_load_pct": mem_load,
                "gpu_util_pct": gpu_util,
                "gaming_active": gaming,
            },
        }

        # Save decision receipt
        STATUS_FILE.write_text(json.dumps(decision, indent=2), encoding="utf-8")
        return decision

    # Brain Rings for dynamic swapping
    HEAVY_RING = [
        "marvin-brain:latest",
        "dolphin3:latest",
        "nexen-clipping-master:latest",
        "nexen-dropshipping-master:latest",
        "nexen-persona-master:latest",
        "samsung-brain:latest",
        "trm:latest",
        "qwen2.5-coder:7b",
        "nexen-coder-v3:latest",
    ]

    PEER_RING = [
        "marvin-brain-3b:latest",
        "xortron:fixed",
        "llama3.2:3b",
        "nexen-coder-3b:latest",
    ]

    OVERRIDE_FILE = Path(r"H:\NEXEN\state\active_brain_override.json")

    def get_active_override(self) -> Optional[str]:
        if self.OVERRIDE_FILE.exists():
            try:
                data = json.loads(self.OVERRIDE_FILE.read_text(encoding="utf-8"))
                return data.get("active_model")
            except Exception:
                pass
        return None

    def swap_brain(self, reason: str = "user_trigger", target_category: str = "escalate") -> Dict[str, Any]:
        """Swaps the current brain to a bigger one and/or an alternate peer model."""
        current = self.get_active_override() or "marvin-brain-3b:latest"
        new_model = None

        # If currently on 3B/peer, escalate to heavy tier
        if current in self.PEER_RING:
            if target_category == "escalate" or "stupid" in reason.lower():
                new_model = self.HEAVY_RING[0]
            else:
                idx = (self.PEER_RING.index(current) + 1) % len(self.PEER_RING)
                new_model = self.PEER_RING[idx]
        elif current in self.HEAVY_RING:
            # Cycle to the next heavy brain (e.g. dolphin3, clipping, dropshipping, samsung)
            idx = (self.HEAVY_RING.index(current) + 1) % len(self.HEAVY_RING)
            new_model = self.HEAVY_RING[idx]
        else:
            # Fallback entry into heavy ring
            new_model = self.HEAVY_RING[0]

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_model": current,
            "active_model": new_model,
            "reason": reason,
            "category": "heavyweight" if new_model in self.HEAVY_RING else "peer",
        }
        self.OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.OVERRIDE_FILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
        log.info("Hot-swapped brain from %s to %s (Reason: %s)", current, new_model, reason)
        return record


if __name__ == "__main__":
    controller = AdaptiveBrainTier()
    result = controller.select_optimal_brain()
    print("Optimal:", json.dumps(result, indent=2))
    swap = controller.swap_brain(reason="CLI test")
    print("Swap result:", json.dumps(swap, indent=2))

