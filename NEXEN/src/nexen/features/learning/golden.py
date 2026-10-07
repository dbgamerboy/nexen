"""Golden gate cases. Used by tests and as the regression wall for self-tuning:
a parameter change is rejected if it breaks any of these."""
from nexen.features.learning.ledger import Ledger, DEFAULT_PARAMS
from nexen.features.learning.novel import NovelLearner

F = "file:/notes/a.md#x@1"
F2 = "file:/notes/b.md#y@2"

# Each case: setup candidates (ingested first, in order), the probe, expected operation.
CASES = [
    {"name": "empty", "setup": [], "probe": {"text": "   "}, "expect": "REJECT"},
    {"name": "first fact", "setup": [],
     "probe": {"text": "The clipping pipeline renders vertical clips with burned captions using ffmpeg and whisper small.", "source_ids": [F]},
     "expect": "ADD"},
    {"name": "no provenance", "setup": [],
     "probe": {"text": "The money lane ranks Upwork service offers ahead of dropshipping for the current week."},
     "expect": "HOLD"},
    {"name": "exact duplicate new source", "setup": [{"text": "n8n runs locally on port 5678 with one active health workflow.", "source_ids": [F]}],
     "probe": {"text": "n8n runs locally on port 5678 with one active health workflow.", "source_ids": [F2]}, "expect": "REINFORCE"},
    {"name": "exact duplicate same source", "setup": [{"text": "n8n runs locally on port 5678 with one active health workflow.", "source_ids": [F]}],
     "probe": {"text": "n8n runs locally on port 5678 with one active health workflow.", "source_ids": [F]}, "expect": "NOOP"},
    {"name": "value change supersedes", "setup": [{"text": "Local n8n holds 29 workflows and one active health schedule.", "source_ids": [F], "observed_at": "2026-09-25T10:00:00"}],
     "probe": {"text": "Local n8n holds 38 workflows and one active health schedule.", "source_ids": [F2], "observed_at": "2026-09-26T10:00:00"},
     "expect": "UPDATE"},
    {"name": "weak contradiction held", "setup": [{"text": "MARVIN speaks in Discord voice through the local text to speech engine.", "source_ids": [F, F2]}],
     "probe": {"text": "MARVIN does not speak in Discord voice through the local text to speech engine.", "source_ids": ["chat:unverified"]},
     "expect": "HOLD"},
    {"name": "unrelated fact added", "setup": [{"text": "The Ollama server listens on port 11434 and serves local models.", "source_ids": [F]}],
     "probe": {"text": "Upwork project catalog offers priced at 250, 450 and 650 dollars were approved by the owner.", "source_ids": [F2]},
     "expect": "ADD"},
    {"name": "low quality held", "setup": [], "probe": {"text": "ok fine", "source_ids": [F]}, "expect": "HOLD"},
]


def run_golden(params=None):
    """Return (passed, total, failures) for the given parameter dict."""
    passed, failures = 0, []
    for case in CASES:
        led = Ledger()
        for k, v in (params or {}).items():
            if k in DEFAULT_PARAMS:
                led.set_param(k, v, "golden")
        learner = NovelLearner(led)
        for s in case["setup"]:
            learner.ingest(s)
        got = learner.assess(case["probe"])["op"]
        if got == case["expect"]:
            passed += 1
        else:
            failures.append({"case": case["name"], "expected": case["expect"], "got": got})
        led.close()
    return passed, len(CASES), failures
