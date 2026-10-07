"""Fail-closed Discord command core. No login, network sends, or desktop input.

The trusted Discord transport supplies gateway-derived identity to IngressSigner.
Do not expose the signer or accept caller-provided Discord identity on an HTTP route.
Sessions are memory-only (restart disarms); replay claims and receipts are durable.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import importlib.util
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Callable


MAX_PCM_BYTES = 16000 * 2 * 20
CONFIRMATION_CATEGORIES = (
    "send_message", "publish", "purchase", "account_change", "delete_file",
    "security_change", "submit_form",
)
_ID = re.compile(r"[1-9][0-9]{5,24}\Z")
_EVENT = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class BridgeError(ValueError):
    """Reason codes are safe to record; exception payloads are never persisted."""


@dataclass(frozen=True)
class Policy:
    owner_id: str
    guild_id: str
    channel_ids: frozenset[str]
    inactivity_seconds: float = 45
    freshness_seconds: float = 30
    max_session_seconds: float = 300
    operation_seconds: float = 20
    heartbeat_seconds: float = 15

    def __post_init__(self):
        if not _ID.fullmatch(self.owner_id) or not _ID.fullmatch(self.guild_id):
            raise BridgeError("owner_and_guild_required")
        if not self.channel_ids or any(not _ID.fullmatch(x) for x in self.channel_ids):
            raise BridgeError("private_channel_allowlist_required")
        if not isinstance(self.channel_ids, frozenset):
            raise BridgeError("immutable_channel_allowlist_required")
        for field in ("inactivity_seconds", "freshness_seconds", "max_session_seconds",
                      "operation_seconds", "heartbeat_seconds"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 1 <= value <= 300:
                raise BridgeError("invalid_timeout")


@dataclass(frozen=True)
class Envelope:
    event_id: str
    connection_id: str
    user_id: str
    guild_id: str
    channel_id: str
    issued_at: float
    kind: str
    payload_sha256: str
    bot: bool = False
    webhook: bool = False
    signature: str = ""


def _canonical(envelope):
    data = asdict(envelope)
    data.pop("signature")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class IngressSigner:
    """An in-process capability for a reviewed, authenticated transport only.

    Its key is freshly generated in memory and is never a Discord token. A caller
    who can invoke this object is already in the trusted transport boundary.
    """

    def __init__(self, key: bytes | None = None):
        self._key = key if key is not None else secrets.token_bytes(32)
        if not isinstance(self._key, bytes) or len(self._key) < 32:
            raise BridgeError("ingress_key_too_short")

    def seal(self, *, event_id, connection_id, user_id, guild_id, channel_id,
             issued_at, payload: bytes, kind="text", bot=False, webhook=False):
        envelope = Envelope(str(event_id), str(connection_id), str(user_id),
                            str(guild_id), str(channel_id), issued_at, kind,
                            hashlib.sha256(payload).hexdigest(), bot, webhook)
        return replace(envelope, signature=hmac.new(self._key, _canonical(envelope), hashlib.sha256).hexdigest())

    def valid(self, envelope):
        try:
            expected = hmac.new(self._key, _canonical(envelope), hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, envelope.signature)
        except (ValueError, TypeError, AttributeError):
            return False

    def message(self, message, connection_id, *, pcm: bytes | None = None):
        """Bind a discord.py Message from on_message; never a deserialized body.

        PCM must be locally decoded from that same message's bounded attachment.
        Channel privacy/permission setup must be reviewed before allowlisting it.
        This method does not fetch an attachment or send a reply.
        """
        if message.guild is None:
            raise BridgeError("guild_required")
        payload = pcm if pcm is not None else message.content.encode("utf-8")
        return self.seal(event_id=str(message.id), connection_id=connection_id,
                         user_id=str(message.author.id), guild_id=str(message.guild.id),
                         channel_id=str(message.channel.id), issued_at=message.created_at.timestamp(),
                         payload=payload, kind="pcm" if pcm is not None else "text",
                         bot=bool(message.author.bot), webhook=message.webhook_id is not None), payload


@dataclass(frozen=True)
class Intent:
    action: str
    target_application: str
    expected_result: str
    risk: str
    confirmation_required: bool = False


def parse_intent(text: str) -> Intent:
    """Exact grammar only; observations never become action instructions."""
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise BridgeError("invalid_command")
    clean = " ".join(text.lower().strip().split()).rstrip(".?!")
    # Stop is the sole command permitted without the wake phrase, after identity checks.
    if clean in ("stop", "cancel", "stop listening"):
        return Intent("stop", "nexen", "Session disarmed and pending observation cancelled.", "control")
    match = re.fullmatch(r"(?:(?:hey )?(?:nexen|marvin)[, :]\s*|!(?:nexen|marvin)\s+)(.+)", clean)
    if not match:
        raise BridgeError("wake_phrase_required")
    command = match[1].strip()
    fixed = {
        "start": Intent("arm", "nexen", "A short read-only session is armed.", "control"),
        "start listening": Intent("arm", "nexen", "A short read-only session is armed.", "control"),
        "stop": Intent("stop", "nexen", "Session disarmed and pending observation cancelled.", "control"),
        "cancel": Intent("stop", "nexen", "Session disarmed and pending observation cancelled.", "control"),
        "status": Intent("status", "nexen", "Report local bridge state.", "read_only"),
        "what is on screen": Intent("describe_screen", "authorized_screen", "Describe visible content with uncertainty.", "read_only"),
        "describe the screen": Intent("describe_screen", "authorized_screen", "Describe visible content with uncertainty.", "read_only"),
        "tell me whether this page is signed in": Intent("check_sign_in", "authorized_screen", "Report visible sign-in evidence; unknown if ambiguous.", "read_only"),
        "is this page signed in": Intent("check_sign_in", "authorized_screen", "Report visible sign-in evidence; unknown if ambiguous.", "read_only"),
    }
    if command in fixed:
        return fixed[command]
    # Categories are review-only classification. No action payload or executor exists.
    prefixes = {
        "send ": "send_message", "message ": "send_message", "publish ": "publish",
        "post ": "publish", "buy ": "purchase", "purchase ": "purchase",
        "change account": "account_change", "change password": "account_change",
        "delete ": "delete_file", "change security": "security_change",
        "disable security": "security_change", "submit ": "submit_form",
    }
    for prefix, category in prefixes.items():
        if command.startswith(prefix):
            return Intent(category, "unresolved", "Prepare exact target and payload for separate owner review.", "consequential", True)
    if command.startswith("confirm"):
        raise BridgeError("confirmation_executor_not_enabled")
    if command.startswith(("click ", "scroll ", "open ", "type ")):
        raise BridgeError("reversible_actions_not_enabled")
    raise BridgeError("ambiguous_or_unsupported_command")


class ReceiptStore:
    """Private local ledger: hashes and outcomes only, no audio/transcript/screen text."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS discord_event_claims (
                    event_hash TEXT PRIMARY KEY, claimed_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS discord_command_receipts (
                    correlation_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
                    event_hash TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT NOT NULL, action TEXT,
                    executed INTEGER NOT NULL CHECK(executed IN (0,1)));
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def event_hash(envelope):
        # Stable across reconnects; changing connection ID cannot replay an event.
        text = ":".join((envelope.guild_id, envelope.channel_id, envelope.event_id))
        return hashlib.sha256(text.encode()).hexdigest()

    def claim(self, envelope, now):
        try:
            with self._connect() as conn:
                conn.execute("INSERT INTO discord_event_claims VALUES (?,?)", (self.event_hash(envelope), now))
            return True
        except sqlite3.IntegrityError:
            return False

    def write(self, receipt, envelope):
        with self._connect() as conn:
            conn.execute("INSERT INTO discord_command_receipts VALUES (?,?,?,?,?,?,?,?)", (
                receipt["correlation_id"], receipt["created_at"], self.event_hash(envelope),
                envelope.payload_sha256, receipt["status"], receipt["reason"],
                receipt.get("intent", {}).get("action"), int(receipt["executed"])))


@dataclass
class _Session:
    connection_id: str
    channel_id: str
    started_at: float
    last_activity: float
    heartbeat: float
    cancelled: threading.Event


class CommandBridge:
    """One owner/session and one bounded observation at a time.

    observer(intent, cancel_event, deadline_monotonic) must be read-only and bounded.
    A timed-out operation retains the busy slot until it returns; no queue grows.
    Runtime supervisors call heartbeat/watchdog and disconnect from gateway events.
    """

    def __init__(self, policy: Policy, signer: IngressSigner, store: ReceiptStore,
                 observer: Callable | None = None, transcriber: Callable | None = None,
                 clock=time.monotonic, wall_clock=time.time):
        self.policy, self.signer, self.store = policy, signer, store
        self.observer, self.transcriber = observer, transcriber
        self.clock, self.wall_clock = clock, wall_clock
        self._lock = threading.RLock()
        self._busy = threading.Lock()
        self._stt_busy = threading.Lock()
        self._generation = threading.Event()
        self._session = None

    def _disarm(self):
        self._generation.set()
        self._generation = threading.Event()
        if self._session:
            self._session.cancelled.set()
        self._session = None

    def watchdog(self):
        with self._lock:
            session, now = self._session, self.clock()
            if session and (now - session.last_activity >= self.policy.inactivity_seconds
                            or now - session.started_at >= self.policy.max_session_seconds
                            or now - session.heartbeat >= self.policy.heartbeat_seconds):
                self._disarm()
                return True
            return False

    def heartbeat(self, connection_id):
        """Trusted gateway heartbeat ACK callback only; cannot re-arm expired sessions."""
        with self._lock:
            self.watchdog()
            if self._session and self._session.connection_id == connection_id:
                self._session.heartbeat = self.clock()

    def disconnect(self, connection_id):
        with self._lock:
            if self._session and self._session.connection_id == connection_id:
                self._disarm()

    def status(self):
        with self._lock:
            self.watchdog()
            return {"armed": self._session is not None, "busy": self._busy.locked(),
                    "stt_busy": self._stt_busy.locked(),
                    "mode": "read_only", "observer_connected": self.observer is not None,
                    "transcriber_connected": self.transcriber is not None,
                    "consequential_actions_enabled": False}

    def _result(self, envelope, status, reason, summary, intent=None, executed=False):
        receipt = dict(correlation_id=secrets.token_hex(12), created_at=self.wall_clock(),
                       status=status, reason=reason, summary=summary[:1500], speech_text=summary[:800],
                       executed=executed, external_action=False, audio_saved=False,
                       transcript_saved=False, screenshot_saved=False)
        if intent:
            receipt["intent"] = asdict(intent)
        self.store.write(receipt, envelope)
        return receipt

    def _authenticate(self, envelope, payload):
        if not isinstance(envelope, Envelope) or not self.signer.valid(envelope):
            raise BridgeError("untrusted_ingress")
        if not isinstance(payload, bytes) or len(payload) > MAX_PCM_BYTES:
            raise BridgeError("payload_limit")
        if (not _EVENT.fullmatch(envelope.event_id) or not _EVENT.fullmatch(envelope.connection_id)
                or envelope.kind not in ("text", "pcm") or type(envelope.bot) is not bool
                or type(envelope.webhook) is not bool):
            raise BridgeError("invalid_envelope")
        if (envelope.user_id != self.policy.owner_id or envelope.guild_id != self.policy.guild_id
                or envelope.channel_id not in self.policy.channel_ids or envelope.bot or envelope.webhook):
            raise BridgeError("unauthorized_identity_or_channel")
        if not hmac.compare_digest(envelope.payload_sha256, hashlib.sha256(payload).hexdigest()):
            raise BridgeError("payload_mismatch")
        stamp = envelope.issued_at
        if (isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp)
                or not -2 <= self.wall_clock() - stamp <= self.policy.freshness_seconds):
            raise BridgeError("stale_or_future_event")
        if not self.store.claim(envelope, self.wall_clock()):
            raise BridgeError("replayed_event")

    def handle(self, envelope: Envelope, payload: bytes):
        # Authentication failures raise before persisting caller-controlled data.
        self._authenticate(envelope, payload)
        try:
            if envelope.kind == "pcm":
                if not payload or len(payload) % 2 or payload.startswith((b"RIFF", b"OggS")):
                    raise BridgeError("pcm_format_required")
                if self.transcriber is None:
                    raise BridgeError("local_stt_unavailable")
                if not self._stt_busy.acquire(blocking=False):
                    raise BridgeError("stt_busy")
                with self._lock:
                    generation = self._generation
                completed, stt_result = threading.Event(), {}

                def transcribe():
                    try:
                        stt_result["value"] = self.transcriber(payload)
                    except Exception:
                        stt_result["error"] = True
                    finally:
                        self._stt_busy.release()
                        completed.set()

                threading.Thread(target=transcribe, daemon=True, name="nexen-local-stt").start()
                deadline = self.clock() + self.policy.operation_seconds
                while not completed.wait(0.02):
                    self.watchdog()
                    if generation.is_set() or self.clock() >= deadline:
                        raise BridgeError("stt_cancelled_or_timeout")
                if generation.is_set() or self.clock() >= deadline:
                    raise BridgeError("stt_cancelled_or_timeout")
                if stt_result.get("error"):
                    raise BridgeError("local_stt_failed")
                transcript = stt_result["value"]
                confidence = transcript.get("confidence")
                if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                        or not math.isfinite(confidence) or not 0.70 <= confidence <= 1):
                    raise BridgeError("low_speech_confidence")
                text = transcript.get("text", "")
            else:
                text = payload.decode("utf-8", errors="strict")
            intent = parse_intent(text)
        except (BridgeError, UnicodeError) as exc:
            reason = str(exc) if isinstance(exc, BridgeError) else "invalid_text_encoding"
            return self._result(envelope, "rejected", reason, "Command rejected; check the exact wake phrase and supported command.")
        except Exception:
            return self._result(envelope, "blocked", "local_stt_failed", "Local speech recognition failed; no action was taken.")

        with self._lock:
            self.watchdog()
            if intent.action == "stop":
                self._disarm()
                return self._result(envelope, "stopped", "owner_stop", intent.expected_result, intent)
            if intent.action == "status":
                return self._result(envelope, "observed", "bridge_status", "Read-only session " + ("armed." if self._session else "disarmed."), intent)
            if intent.action == "arm":
                if self._busy.locked():
                    return self._result(envelope, "blocked", "operation_draining", "The previous observation is still ending. Retry shortly.", intent)
                self._disarm()
                now = self.clock()
                self._session = _Session(envelope.connection_id, envelope.channel_id, now, now, now, threading.Event())
                return self._result(envelope, "armed", "read_only_armed", intent.expected_result, intent)
            session = self._session
            if session is None or session.connection_id != envelope.connection_id or session.channel_id != envelope.channel_id:
                return self._result(envelope, "blocked", "session_not_armed", "Say NEXEN start in the approved channel, then give a read-only command.", intent)
            if intent.confirmation_required:
                reason = "zero_spend_policy" if intent.action == "purchase" else "exact_owner_confirmation_and_executor_required"
                return self._result(envelope, "review_required", reason, "This consequential action is disabled. Its exact target and payload need a separately reviewed executor and owner approval.", intent)
            if self.observer is None:
                return self._result(envelope, "blocked", "screen_observer_not_connected", "Authorized screen capture and a verified vision model are not connected.", intent)
            if not self._busy.acquire(blocking=False):
                return self._result(envelope, "blocked", "observer_busy", "One observation is already running. Stop remains available.", intent)
            session.last_activity = self.clock()
            deadline = self.clock() + self.policy.operation_seconds

        completed = threading.Event()
        outcome = {}

        def observe():
            try:
                outcome["value"] = self.observer(intent, session.cancelled, deadline)
            except Exception:
                outcome["error"] = True
            finally:
                self._busy.release()
                completed.set()

        threading.Thread(target=observe, daemon=True, name="nexen-read-only-observer").start()
        while not completed.wait(0.02):
            self.watchdog()
            if session.cancelled.is_set() or self.clock() >= deadline:
                with self._lock:
                    if self._session is session:
                        self._disarm()
                reason = "cancelled" if self.clock() < deadline else "operation_timeout"
                return self._result(envelope, "cancelled", reason, "The observation was cancelled; its late result will be discarded.", intent)
        with self._lock:
            self.watchdog()
            if session.cancelled.is_set() or self._session is not session or self.clock() >= deadline:
                return self._result(envelope, "cancelled", "late_result_discarded", "The observation ended after its session was cancelled or expired.", intent)
            if outcome.get("error"):
                return self._result(envelope, "blocked", "observer_failed", "Screen observation failed; no computer action was taken.", intent)
            value = outcome.get("value", {})
            if not isinstance(value, dict) or not isinstance(value.get("summary"), str) or not value["summary"].strip():
                return self._result(envelope, "blocked", "invalid_observation", "No supported observation was returned.", intent)
            return self._result(envelope, "observed", "read_only_result", value["summary"], intent, executed=True)


class FasterWhisperCPU:
    """Reuse an installed local checkpoint; imports lazily, no download fallback.

    Run with the existing transcription or MARVIN environment where faster-whisper
    and numpy are installed. Input is mono 16 kHz signed 16-bit raw PCM.
    """

    def __init__(self, model_path=Path("H:/NEXEN/models/whisper/small.en")):
        self.model_path = Path(model_path)
        self._model = None
        self._lock = threading.Lock()

    def status(self):
        files = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
        return {"engine": "faster-whisper-cpu-int8", "local_checkpoint_present": all((self.model_path / f).is_file() for f in files),
                "dependency_present": importlib.util.find_spec("faster_whisper") is not None,
                "speech_accuracy_verified": False, "download_allowed": False, "audio_saved": False}

    def __call__(self, pcm: bytes):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM_BYTES or pcm.startswith((b"RIFF", b"OggS")):
            raise BridgeError("pcm_format_required")
        if not self._lock.acquire(blocking=False):
            raise BridgeError("stt_busy")
        try:
            if not self.model_path.is_absolute() or not self.status()["local_checkpoint_present"]:
                raise BridgeError("local_stt_checkpoint_missing")
            import numpy as np
            from faster_whisper import WhisperModel
            if self._model is None:
                self._model = WhisperModel(str(self.model_path), device="cpu", compute_type="int8",
                                          cpu_threads=2, num_workers=1, local_files_only=True)
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            segments, _ = self._model.transcribe(audio, language="en", beam_size=1, word_timestamps=True,
                                                  condition_on_previous_text=False, vad_filter=True)
            parts, confidence = [], []
            for segment in segments:
                parts.append(segment.text.strip())
                confidence.extend(word.probability for word in (segment.words or [])
                                  if math.isfinite(word.probability) and 0 <= word.probability <= 1)
            return {"text": " ".join(parts)[:500], "confidence": sum(confidence) / len(confidence) if confidence else None}
        finally:
            self._lock.release()


def speech_fixture_status(path=None):
    """Expose saved qualification outcome without importing/loading the speech model."""
    path = Path(path) if path is not None else Path("H:/NEXEN/enterprise/20260927/voice/STT-DIAGNOSTIC-RECEIPT.json")
    result = {"synthetic_fixture_passed": False, "actual_audio_input": False,
              "live_speech_accuracy_verified": False, "fixture_receipt": str(path)}
    try:
        if path.stat().st_size > 64000:
            return dict(result, fixture_state="invalid_receipt")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            return dict(result, fixture_state="invalid_receipt")
        passed = (evidence.get("status") == "passed" and evidence.get("actual_audio_input") is True
                  and evidence.get("parsed_action") == "describe_screen")
        return dict(result, synthetic_fixture_passed=passed,
                    actual_audio_input=evidence.get("actual_audio_input") is True,
                    recognizer_returned=evidence.get("recognizer_returned") is True or passed,
                    fixture_state="passed" if passed else "not_passed")
    except (OSError, ValueError):
        return dict(result, fixture_state="unavailable")


def register(app, db=None, bridge=None):
    """Readiness and inert parsing only; inherit the hub's private auth middleware.

    There is intentionally no HTTP ingress that accepts a Discord user ID. The
    trusted bot transport invokes CommandBridge in process after Discord auth.
    """
    from fastapi import HTTPException, Request

    @app.get("/api/discord-voice/status")
    def status():
        from vision_runtime import fixture_status
        evidence = fixture_status()
        blockers = ["trusted_discord_transport", "owner_guild_channel_allowlist",
                    "authorized_screen_capture", "screen_accuracy_receipt"] if bridge is None else []
        if not evidence["image_fixture_passed"]:
            blockers.append("vision_image_fixture")
        return dict(state="connected_to_local_core" if bridge else "prepared",
                    live_discord_verified=False, read_only=True,
                    confirmation_categories=list(CONFIRMATION_CATEGORIES),
                    wake_names=["NEXEN", "MARVIN"],
                    supported_commands=["NEXEN start", "NEXEN what is on screen",
                                        "NEXEN tell me whether this page is signed in", "stop"],
                    bridge=bridge.status() if bridge else None,
                    image_fixture=evidence, speech_fixture=speech_fixture_status(), blockers=blockers,
                    external_actions_enabled=False)

    # Keep request annotation resolvable when FastAPI inspects this local function.
    async def preview(request):
        from pc_control import validate_request
        validate_request(request, mutation=True)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2048:
                raise HTTPException(413, "Command preview is limited to 2048 bytes.")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"text"}:
                raise BridgeError("text_only_preview")
            intent = parse_intent(body["text"])
        except (ValueError, TypeError):
            raise HTTPException(422, "Use one supported command with the NEXEN or MARVIN wake phrase.")
        return {"intent": asdict(intent), "executed": False, "preview_only": True}
    preview.__annotations__["request"] = Request
    app.post("/api/discord-voice/preview")(preview)
