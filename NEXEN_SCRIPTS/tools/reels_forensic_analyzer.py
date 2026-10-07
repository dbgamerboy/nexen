"""
NEXEN Reels Forensic Multimodal Reconstruction Engine
=====================================================
Performs strict 4-pass forensic reverse-engineering of short-form AI / marketing tutorials.
Passes:
- PASS A: SOURCE LEDGER (Timestamps, Speaker, Spoken Content, Visible UI Action)
- PASS B: TRANSCRIPT (Timestamped Verbatim Transcript)
- PASS C: ON-SCREEN TEXT (Extracted Prompts, Parameters, Headings, UI Settings)
- PASS D: PROMPT-GUIDELINE EXTRACTION (Role, Context, Task, Constraints, Schema, Model)
"""

import os
import sys
import json
import re
from typing import Dict, List, Any

class ReelsForensicAnalyzer:
    def __init__(self, output_dir: str = r"H:\NEXEN\knowledge\forensic_reconstructions"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def format_timestamp(self, seconds: float) -> str:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def generate_forensic_dossier(self, video_title: str, audio_segments: List[Dict], visual_ocr_data: List[Dict], reconstructed_system: Dict) -> str:
        """Compiles the four forensic passes into a unified analytical artifact."""
        dossier_lines = []
        dossier_lines.append(f"# FORENSIC RECONSTRUCTION DOSSIER: {video_title.upper()}")
        dossier_lines.append("`Role`: Forensic Multimodal Analyst")
        dossier_lines.append("`Standard`: Extreme Fidelity Reconstruction (Source Ledger + Verbatim + On-Screen Text + Schema)")
        dossier_lines.append("\n---\n")

        # PASS A — SOURCE LEDGER
        dossier_lines.append("## PASS A — SOURCE LEDGER")
        dossier_lines.append("| Start | End | Speaker | Spoken Audio Summary | Visible UI / On-Screen Action |")
        dossier_lines.append("|---|---|---|---|---|")
        for seg in audio_segments:
            start_ts = self.format_timestamp(seg.get("start", 0))
            end_ts = self.format_timestamp(seg.get("end", 0))
            speaker = seg.get("speaker", "Speaker 1")
            spoken = seg.get("text", "").replace("|", "-")
            ui_action = seg.get("ui_action", "Video demonstration / talking head").replace("|", "-")
            dossier_lines.append(f"| {start_ts} | {end_ts} | {speaker} | {spoken} | {ui_action} |")
        dossier_lines.append("\n---\n")

        # PASS B — VERBATIM TRANSCRIPT
        dossier_lines.append("## PASS B — TIMESTAMPED VERBATIM TRANSCRIPT")
        for seg in audio_segments:
            start_ts = self.format_timestamp(seg.get("start", 0))
            speaker = seg.get("speaker", "Speaker 1")
            dossier_lines.append(f"**[{start_ts}] {speaker}:** {seg.get('text', '')}")
        dossier_lines.append("\n---\n")

        # PASS C — ON-SCREEN TEXT & PROMPT EXTRACTION
        dossier_lines.append("## PASS C — ON-SCREEN TECHNICAL TEXT")
        dossier_lines.append("```yaml")
        dossier_lines.append("# Extracted verbatim prompts, URLs, models, and parameters")
        for idx, ocr in enumerate(visual_ocr_data):
            dossier_lines.append(f"segment_{idx+1}:")
            dossier_lines.append(f"  timestamp: \"{ocr.get('timestamp', '00:00')}\"")
            dossier_lines.append(f"  element_type: \"{ocr.get('type', 'prompt')}\"")
            dossier_lines.append(f"  raw_text: |")
            for line in ocr.get("text", "").splitlines():
                dossier_lines.append(f"    {line}")
        dossier_lines.append("```")
        dossier_lines.append("\n---\n")

        # PASS D — PROMPT-GUIDELINE EXTRACTION
        dossier_lines.append("## PASS D — PROMPT-GUIDELINE RECONSTRUCTED SYSTEM")
        dossier_lines.append("```markdown")
        dossier_lines.append("<role>")
        dossier_lines.append(reconstructed_system.get("role", "Autonomous AI Operator"))
        dossier_lines.append("</role>\n")
        dossier_lines.append("<context>")
        dossier_lines.append(reconstructed_system.get("context", "Reconstructed from verified video source."))
        dossier_lines.append("</context>\n")
        dossier_lines.append("<instructions>")
        for step in reconstructed_system.get("instructions", []):
            dossier_lines.append(f"- {step}")
        dossier_lines.append("</instructions>\n")
        dossier_lines.append("<constraints>")
        for c in reconstructed_system.get("constraints", []):
            dossier_lines.append(f"- {c}")
        dossier_lines.append("</constraints>\n")
        dossier_lines.append("<output_schema>")
        dossier_lines.append(reconstructed_system.get("output_schema", "JSON object with status and receipts."))
        dossier_lines.append("</output_schema>")
        dossier_lines.append("```")

        output_path = os.path.join(self.output_dir, f"{re.sub(r'[^a-zA-Z0-9_]', '_', video_title)}.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dossier_lines))
        
        return output_path

if __name__ == "__main__":
    analyzer = ReelsForensicAnalyzer()
    sample_segments = [
        {"start": 0, "end": 4.5, "speaker": "Speaker 1", "text": "Stop scrolling if you want to make money while you sleep with AI personas in 2026.", "ui_action": "Camera zooms in, text overlay displays high bold yellow font"},
        {"start": 4.5, "end": 15.2, "speaker": "Speaker 1", "text": "I literally generated this model on my laptop using open source FLUX and Higgsfield motion transfer.", "ui_action": "Split screen showing original TikTok dance on left, AI generated render on right"},
        {"start": 15.2, "end": 30.0, "speaker": "Speaker 1", "text": "The entire bio links to Unlockt and Fanvue where subscribers pay 20 dollars a month on complete autopilot.", "ui_action": "Screen recording showing Fanvue dashboard and Stripe balance payout"}
    ]
    sample_ocr = [
        {"timestamp": "00:04", "type": "on_screen_hook", "text": "HOW I MAKE $10K/MO WITH AI GIRLS (STEP BY STEP)"},
        {"timestamp": "00:12", "type": "prompt_extract", "text": "Photo of 24yo athletic woman, natural studio lighting, 35mm lens, high realism, 8k --ar 9:16"}
    ]
    sample_system = {
        "role": "Autonomous Virtual Influencer Marketing Director",
        "context": "Short-form video acquisition engine converting TikTok/Reels scrollers into Fanvue/Unlockt subscribers.",
        "instructions": [
            "Source high-velocity TikTok reference dances using TikTok Trend Tracker.",
            "Align persona Frame 0 using image-to-image facial pose conditioning.",
            "Transfer temporal motion via open-source motion model at 60fps.",
            "Post during peak retention windows with trending native audio."
        ],
        "constraints": [
            "Never use static text without visual motion interrupts.",
            "Ensure 100% photorealistic facial consistency across all posts.",
            "Route traffic exclusively through high-conversion bridge landing page."
        ],
        "output_schema": "Structured short-form creative blueprint with exact caption, hashtag cluster, and bridge URL."
    }
    path = analyzer.generate_forensic_dossier("demo_ai_girl_reel", sample_segments, sample_ocr, sample_system)
    print(f"Generated sample forensic dossier at: {path}")
