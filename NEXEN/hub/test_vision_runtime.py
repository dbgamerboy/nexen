"""Synthetic image bytes and stubbed loopback transport; no real screen capture."""
from contextlib import contextmanager
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import zlib

from discord_voice_bridge import parse_intent
from vision_runtime import MAX_IMAGE_BYTES, OllamaLocal, VisionError, VisionObserver, fixture_status, validate_image


class VisionTests(unittest.TestCase):
    def setUp(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        self.image = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 24, 24, 8, 2, 0, 0, 0))
                      + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([255, 0, 0]) * 24) * 24)) + chunk(b"IEND", b""))
        self.calls = []
        self.captures = []
        self.reservation = []
        self.model = "fixture-model:local"
        self.digest = "a" * 64
        self.qualification = {"status": "passed", "actual_image_input": True,
            "model": self.model, "model_digest": self.digest, "fixture_sha256": "b" * 64,
            "receipt_id": "synthetic-receipt-not-a-real-model-qualification"}
        self.client = OllamaLocal(transport=self.transport)
        self.observer = VisionObserver(self.client, self.model, self.qualification,
            self.capture, self.reserve)
        self.intent = parse_intent("MARVIN what is on screen")

    def transport(self, path, body):
        self.calls.append((path, body))
        if path == "/api/tags": return {"models": [{"name": self.model, "digest": self.digest}]}
        if path == "/api/show": return {"capabilities": ["completion", "vision"]}
        if path == "/api/ps": return {"models": []}
        if path == "/api/generate":
            self.assertEqual(self.reservation, ["held"])
            return {"done": True, "response": "A red synthetic square."}
        raise AssertionError(path)

    def capture(self, cancel, deadline):
        self.assertEqual(self.reservation, ["held"])
        self.captures.append(True)
        return self.image

    @contextmanager
    def reserve(self, model, deadline):
        self.reservation.append("held")
        try: yield
        finally: self.reservation.clear()

    def run_observer(self):
        return self.observer(self.intent, threading.Event(), time.monotonic() + 10)

    def test_external_endpoints_credentials_and_redirect_surfaces_rejected(self):
        for url in ("https://example.com", "http://192.168.77.5:11434", "http://127.0.0.1:11434/other",
                    "http://name:pass@127.0.0.1:11434", "http://127.0.0.1:11434/?x=1"):
            with self.subTest(url=url), self.assertRaises(VisionError): OllamaLocal(url)
        with self.assertRaises(VisionError): self.client.request("/api/pull", {"model": "new"})

    def test_inventory_does_not_run_inference(self):
        result = self.client.inventory()
        self.assertFalse(result["inference_performed"])
        self.assertEqual([x[0] for x in self.calls], ["/api/tags", "/api/ps"])

    def test_metadata_without_fixture_cannot_capture(self):
        self.observer.qualification["actual_image_input"] = False
        with self.assertRaisesRegex(VisionError, "fixture_not_verified"): self.run_observer()
        self.assertEqual(self.captures, [])
        self.assertEqual(self.calls, [])

    def test_changed_model_digest_revokes_qualification(self):
        self.observer.qualification["model_digest"] = "c" * 64
        with self.assertRaisesRegex(VisionError, "digest_changed"): self.run_observer()
        self.assertEqual(self.captures, [])

    def test_text_only_model_cannot_observe(self):
        original = self.transport
        self.client._transport = lambda p,b: {"capabilities": ["completion"]} if p == "/api/show" else original(p,b)
        with self.assertRaisesRegex(VisionError, "no_vision"): self.run_observer()
        self.assertEqual(self.captures, [])

    def test_valid_image_input_payload_is_local_bounded_and_read_only(self):
        result = self.run_observer()
        self.assertEqual(result["summary"], "A red synthetic square.")
        self.assertFalse(result["authentication_verified"])
        body = next(b for p,b in self.calls if p == "/api/generate")
        self.assertEqual(body["options"]["num_gpu"], 0)
        self.assertLessEqual(body["options"]["num_ctx"], 2048)
        self.assertTrue(body["images"])
        self.assertIn("untrusted", body["prompt"])
        self.assertEqual(self.reservation, [])

    def test_invalid_or_oversized_image_is_rejected(self):
        for image in (b"fake", b"\x89PNG\r\n\x1a\ninvalid", b"x" * (MAX_IMAGE_BYTES + 1)):
            with self.assertRaises(VisionError): validate_image(image)

    def test_cancelled_or_expired_operation_never_captures(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(VisionError, "cancelled"):
            self.observer(self.intent, cancel, time.monotonic() + 10)
        with self.assertRaisesRegex(VisionError, "cancelled"):
            self.observer(self.intent, threading.Event(), time.monotonic() - 1)
        self.assertEqual(self.captures, [])

    def test_busy_scheduler_blocks_before_capture(self):
        @contextmanager
        def blocked(*args):
            raise VisionError("resource_busy")
            yield
        self.observer.scheduler_permit = blocked
        with self.assertRaisesRegex(VisionError, "resource_busy"): self.run_observer()
        self.assertEqual(self.captures, [])

    def test_incomplete_model_result_is_not_observation_success(self):
        original = self.transport
        self.client._transport = lambda p,b: {"done": False, "response": "partial"} if p == "/api/generate" else original(p,b)
        with self.assertRaisesRegex(VisionError, "incomplete"): self.run_observer()

    def test_sign_in_prompt_requires_uncertainty_and_no_account_identification(self):
        self.intent = parse_intent("MARVIN is this page signed in")
        self.run_observer()
        body = next(b for p,b in self.calls if p == "/api/generate")
        self.assertIn("unknown", body["prompt"])
        self.assertIn("not authentication verification", body["prompt"])

    def test_readiness_distinguishes_attempted_passed_and_live_accuracy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.json"
            self.assertFalse(fixture_status(path)["image_fixture_passed"])
            evidence = dict(self.qualification)
            evidence["status"] = "blocked"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertTrue(fixture_status(path)["actual_image_input"])
            self.assertFalse(fixture_status(path)["image_fixture_passed"])
            evidence["status"] = "passed"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertTrue(fixture_status(path)["image_fixture_passed"])
            self.assertFalse(fixture_status(path)["screen_accuracy_verified"])


if __name__ == "__main__":
    unittest.main()
