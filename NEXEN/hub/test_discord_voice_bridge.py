"""Synthetic identities and observers only: no Discord login/sends or PC actions."""
from dataclasses import replace
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from discord_voice_bridge import (BridgeError, CommandBridge, CONFIRMATION_CATEGORIES,
    FasterWhisperCPU, IngressSigner, MAX_PCM_BYTES, Policy, ReceiptStore, parse_intent, speech_fixture_status)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.tick = 100.0
        self.signer = IngressSigner()
        self.policy = Policy("100001", "200001", frozenset({"300001", "300002"}))
        self.path = Path(self.temp.name) / "commands.sqlite"
        self.store = ReceiptStore(self.path)
        self.bridge = CommandBridge(self.policy, self.signer, self.store,
            clock=lambda: self.tick, wall_clock=lambda: self.now)
        self.counter = 0

    def envelope(self, text="MARVIN start", **changes):
        self.counter += 1
        payload = text.encode() if isinstance(text, str) else text
        params = dict(event_id=f"evt-{self.counter}", connection_id="connection-1",
                      user_id="100001", guild_id="200001", channel_id="300001",
                      issued_at=self.now, payload=payload, kind="text")
        params.update(changes)
        return self.signer.seal(**params), payload

    def send(self, text, **changes):
        return self.bridge.handle(*self.envelope(text, **changes))

    def test_missing_owner_guild_or_channel_fails_closed(self):
        for args in [("0", "200001", frozenset({"300001"})),
                     ("100001", "0", frozenset({"300001"})), ("100001", "200001", frozenset())]:
            with self.subTest(args=args), self.assertRaises(BridgeError):
                Policy(*args)

    def test_timeouts_reject_nan_bool_and_unbounded_values(self):
        for timeout in (float("nan"), True, 0, 301):
            with self.subTest(timeout=timeout), self.assertRaises(BridgeError):
                replace(self.policy, operation_seconds=timeout)

    def test_unknown_identity_guild_channel_bot_and_webhook_rejected_before_stt(self):
        calls = []
        self.bridge.transcriber = lambda pcm: calls.append(pcm)
        for change in ({"user_id": "999999"}, {"guild_id": "999999"},
                       {"channel_id": "999999"}, {"bot": True}, {"webhook": True}):
            with self.subTest(change=change), self.assertRaisesRegex(BridgeError, "unauthorized"):
                self.bridge.handle(*self.envelope(b"\x00\x00", kind="pcm", **change))
        self.assertEqual(calls, [])

    def test_tampered_signature_payload_and_event_rejected(self):
        env, payload = self.envelope()
        for altered in (replace(env, signature="a" * 64), replace(env, user_id="999999")):
            with self.assertRaisesRegex(BridgeError, "untrusted"):
                self.bridge.handle(altered, payload)
        with self.assertRaisesRegex(BridgeError, "payload_mismatch"):
            self.bridge.handle(env, b"MARVIN stop")

    def test_expired_and_future_events_rejected(self):
        for stamp in (self.now - 31, self.now + 3):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(BridgeError, "stale_or_future"):
                self.bridge.handle(*self.envelope(issued_at=stamp))

    def test_replay_is_persistent_across_restart_and_reconnect(self):
        env, payload = self.envelope()
        self.bridge.handle(env, payload)
        restarted = CommandBridge(self.policy, self.signer, ReceiptStore(self.path), wall_clock=lambda: self.now)
        with self.assertRaisesRegex(BridgeError, "replayed"):
            restarted.handle(env, payload)
        altered, _ = self.envelope(event_id=env.event_id, connection_id="connection-2")
        with self.assertRaisesRegex(BridgeError, "replayed"):
            restarted.handle(altered, payload)
        self.assertFalse(restarted.status()["armed"])

    def test_parallel_duplicate_claim_runs_once(self):
        env, payload = self.envelope()
        outcomes = []
        def run():
            try:
                outcomes.append(self.bridge.handle(env, payload)["status"])
            except BridgeError as exc:
                outcomes.append(str(exc))
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertCountEqual(outcomes, ["armed", "replayed_event"])

    def test_wake_phrase_and_exact_commands_only(self):
        self.assertEqual(self.send("what is on screen")["reason"], "wake_phrase_required")
        self.assertEqual(self.send("MARVIN what is on screen and send it")["reason"], "ambiguous_or_unsupported_command")
        self.assertEqual(parse_intent("Hey MARVIN, what is on screen?").action, "describe_screen")
        self.assertEqual(parse_intent("!nexen start").action, "arm")
        self.assertEqual(parse_intent("stop").action, "stop")

    def test_nexen_and_marvin_wake_names_normalize_to_same_intent(self):
        for command in ("start", "what is on screen", "tell me whether this page is signed in", "stop"):
            self.assertEqual(parse_intent("NEXEN " + command), parse_intent("MARVIN " + command))
            self.assertEqual(parse_intent("hey nexen, " + command), parse_intent("!marvin " + command))

    def test_observation_requires_armed_same_channel_and_connection(self):
        self.assertEqual(self.send("MARVIN what is on screen")["reason"], "session_not_armed")
        self.send("MARVIN start")
        for changes in ({"channel_id": "300002"}, {"connection_id": "connection-2"}):
            self.assertEqual(self.send("MARVIN what is on screen", **changes)["reason"], "session_not_armed")

    def test_observer_unavailable_is_not_success(self):
        self.send("MARVIN start")
        result = self.send("MARVIN what is on screen")
        self.assertEqual(result["reason"], "screen_observer_not_connected")
        self.assertFalse(result["executed"])

    def test_observation_receipt_does_not_store_transcript_or_result(self):
        secret = "private synthetic page text"
        self.bridge.observer = lambda *args: {"summary": secret}
        self.send("MARVIN start")
        result = self.send("MARVIN what is on screen")
        self.assertEqual(result["summary"], secret)
        self.assertEqual(result["speech_text"], secret)
        self.assertTrue(result["executed"])
        self.assertFalse(result["external_action"])
        self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.assertNotIn(b"MARVIN what", self.path.read_bytes())
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM discord_command_receipts").fetchone()[0], 2)
        conn.close()

    def test_all_consequential_categories_need_review_and_spend_always_blocked(self):
        commands = ("send a message", "publish this", "buy a product", "change account", "delete a file", "change security", "submit the form")
        self.send("MARVIN start")
        actions = []
        for command in commands:
            result = self.send("MARVIN " + command)
            self.assertEqual(result["status"], "review_required")
            self.assertFalse(result["executed"])
            actions.append(result["intent"]["action"])
        self.assertCountEqual(actions, CONFIRMATION_CATEGORIES)
        self.assertEqual(self.send("MARVIN buy this")["reason"], "zero_spend_policy")
        self.assertEqual(self.send("MARVIN confirm")["reason"], "confirmation_executor_not_enabled")

    def test_reversible_actions_remain_disabled(self):
        for command in ("click five", "scroll down", "open chrome", "type hello"):
            self.assertEqual(self.send("MARVIN " + command)["reason"], "reversible_actions_not_enabled")

    def test_inactivity_heartbeat_and_max_age_disarm(self):
        for advance, policy in ((46, self.policy), (16, self.policy),
                                (6, replace(self.policy, max_session_seconds=5))):
            self.bridge.policy = policy
            self.send("MARVIN start")
            self.tick += advance
            self.assertTrue(self.bridge.watchdog())
            self.assertFalse(self.bridge.status()["armed"])
        self.bridge.heartbeat("connection-1")
        self.assertFalse(self.bridge.status()["armed"])

    def test_heartbeat_does_not_extend_inactivity_limit(self):
        self.send("MARVIN start")
        for _ in range(4):
            self.tick += 10
            self.bridge.heartbeat("connection-1")
        self.tick += 6
        self.assertTrue(self.bridge.watchdog())

    def test_disconnect_disarms_and_reconnect_requires_new_start(self):
        self.send("MARVIN start")
        self.bridge.disconnect("connection-1")
        self.assertEqual(self.send("MARVIN what is on screen", connection_id="connection-2")["reason"], "session_not_armed")

    def test_stop_interrupts_wait_and_discards_late_result(self):
        started, release = threading.Event(), threading.Event()
        def observer(intent, cancel, deadline):
            started.set()
            release.wait(2)
            return {"summary": "late synthetic observation"}
        self.bridge.observer = observer
        self.send("MARVIN start")
        results = []
        request = self.envelope("MARVIN what is on screen")
        thread = threading.Thread(target=lambda: results.append(self.bridge.handle(*request)))
        thread.start()
        self.assertTrue(started.wait(1))
        before = time.monotonic()
        self.assertEqual(self.send("stop")["status"], "stopped")
        thread.join(1)
        self.assertLess(time.monotonic() - before, 1)
        self.assertEqual(results[0]["status"], "cancelled")
        self.assertNotIn("late synthetic", results[0]["summary"])
        self.assertEqual(self.send("MARVIN start")["reason"], "operation_draining")
        release.set()

    def test_operation_timeout_has_no_unbounded_queue(self):
        started, release = threading.Event(), threading.Event()
        self.bridge.observer = lambda *args: (started.set(), release.wait(2), {"summary": "late"})[-1]
        self.send("MARVIN start")
        request, results = self.envelope("MARVIN what is on screen"), []
        thread = threading.Thread(target=lambda: results.append(self.bridge.handle(*request)))
        thread.start()
        self.assertTrue(started.wait(1))
        self.tick += 21
        thread.join(1)
        self.assertEqual(results[0]["reason"], "operation_timeout")
        self.assertEqual(self.send("MARVIN start")["reason"], "operation_draining")
        release.set()

    def test_low_confidence_audio_and_format_are_rejected(self):
        self.bridge.transcriber = lambda pcm: {"text": "MARVIN start", "confidence": 0.69}
        for confidence in (0.69, None, True, float("nan"), 2):
            self.bridge.transcriber = lambda pcm, c=confidence: {"text": "MARVIN start", "confidence": c}
            self.assertEqual(self.send(b"\x00\x00", kind="pcm")["reason"], "low_speech_confidence")
        self.assertEqual(self.send(b"x", kind="pcm")["reason"], "pcm_format_required")
        self.assertEqual(self.send(b"RIFF0000", kind="pcm")["reason"], "pcm_format_required")

    def test_valid_audio_uses_local_transcriber_and_same_parser(self):
        self.bridge.transcriber = lambda pcm: {"text": "MARVIN start", "confidence": .92}
        self.assertEqual(self.send(b"\x00\x00", kind="pcm")["status"], "armed")
        self.assertFalse(self.send("MARVIN status")["audio_saved"])

    def test_observed_stt_hallucination_suffix_remains_rejected(self):
        # Actual stock-voice fixture result from STT-DIAGNOSTIC-TRANSCRIPT.json.
        # Its mean score clears the threshold, but the extra word must not execute.
        self.bridge.transcriber = lambda pcm: {"text": "Marvin what is on screen swollen", "confidence": 0.7068356270892835}
        calls = []
        self.bridge.observer = lambda *args: calls.append(True)
        self.send("NEXEN start")
        result = self.send(b"\x00\x00", kind="pcm")
        self.assertEqual(result["reason"], "ambiguous_or_unsupported_command")
        self.assertFalse(result["executed"])
        self.assertEqual(calls, [])

    def test_speech_readiness_does_not_confuse_returned_transcript_with_accuracy(self):
        path = Path(self.temp.name) / "speech-evidence.json"
        evidence = {"status": "failed", "actual_audio_input": True, "recognizer_returned": True,
                    "command_accuracy_passed": False, "text": "private content must not be returned"}
        path.write_text(json.dumps(evidence), encoding="utf-8")
        state = speech_fixture_status(path)
        self.assertTrue(state["actual_audio_input"])
        self.assertTrue(state["recognizer_returned"])
        self.assertFalse(state["synthetic_fixture_passed"])
        self.assertFalse(state["live_speech_accuracy_verified"])
        self.assertNotIn("private content", json.dumps(state))

    def test_pcm_adapter_rejects_bad_input_without_loading_model(self):
        adapter = FasterWhisperCPU(Path(self.temp.name) / "missing")
        for payload in (b"", b"x", b"RIFF0000", b"\x00" * (MAX_PCM_BYTES + 2)):
            with self.assertRaises(BridgeError): adapter(payload)
        with self.assertRaisesRegex(BridgeError, "checkpoint_missing"):
            adapter(b"\x00\x00")
        self.assertIsNone(adapter._model)

    def test_message_adapter_copies_gateway_identity_and_rejects_dm(self):
        message = SimpleNamespace(id=500001, author=SimpleNamespace(id=100001, bot=False),
            guild=SimpleNamespace(id=200001), channel=SimpleNamespace(id=300001), webhook_id=None,
            content="MARVIN start", created_at=datetime.fromtimestamp(self.now, timezone.utc))
        envelope, payload = self.signer.message(message, "connection-1")
        self.assertEqual(self.bridge.handle(envelope, payload)["status"], "armed")
        message.guild = None
        with self.assertRaisesRegex(BridgeError, "guild_required"):
            self.signer.message(message, "connection-1")

    def test_inert_http_preview_enforces_origin_size_and_text_only_schema(self):
        from fastapi import FastAPI
        import httpx
        from discord_voice_bridge import register
        async def run():
            app = FastAPI()
            register(app)
            headers = {"Origin": "http://127.0.0.1:8788", "X-Nexen-Action": "launch"}
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 55555))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8788") as client:
                denied = await client.post("/api/discord-voice/preview", json={"text": "NEXEN start"})
                self.assertEqual(denied.status_code, 403)
                preview = await client.post("/api/discord-voice/preview", headers=headers, json={"text": "NEXEN what is on screen"})
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.json()["executed"])
                self.assertTrue(preview.json()["preview_only"])
                for body in ({"text": "NEXEN start", "user_id": "100001"}, ["NEXEN start"], {"text": 7}):
                    response = await client.post("/api/discord-voice/preview", headers=headers, json=body)
                    self.assertEqual(response.status_code, 422)
                oversized = await client.post("/api/discord-voice/preview", headers=headers, content=b"x" * 2049)
                self.assertEqual(oversized.status_code, 413)
                status = (await client.get("/api/discord-voice/status")).json()
                self.assertEqual(status["wake_names"], ["NEXEN", "MARVIN"])
                self.assertFalse(status["live_discord_verified"])
        asyncio.run(run())

    def test_stop_cancels_inflight_transcription_without_queue_growth(self):
        started, release = threading.Event(), threading.Event()
        def transcriber(pcm):
            started.set()
            release.wait(2)
            return {"text": "NEXEN start", "confidence": .95}
        self.bridge.transcriber = transcriber
        request, results = self.envelope(b"\x00\x00", kind="pcm"), []
        thread = threading.Thread(target=lambda: results.append(self.bridge.handle(*request)))
        thread.start()
        self.assertTrue(started.wait(1))
        self.assertEqual(self.send(b"\x00\x00", kind="pcm")["reason"], "stt_busy")
        self.send("stop")
        thread.join(1)
        self.assertEqual(results[0]["reason"], "stt_cancelled_or_timeout")
        self.assertFalse(self.bridge.status()["armed"])
        release.set()


if __name__ == "__main__":
    unittest.main()
