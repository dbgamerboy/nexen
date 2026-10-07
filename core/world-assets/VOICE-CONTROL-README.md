# Local NEXEN voice UI

Files: `world-assets/voice-control.js`, `world-assets/voice-control.css`, and `voice.html`. The existing `problems.html` was also connected to the voice-question flow, with a `problems.html.before-voice` backup. No backend, hub or game files were changed by this subtask.

## Integration

Serve `voice.html` at authenticated `/voice`. Include this module on a main page or the game to mount its minimizable floating panel:

```html
<script type="module" src="/world-assets/voice-control.js"></script>
```

To place the panel inline, add `<div data-nexen-voice></div>` before the module. The module loads its local stylesheet if needed. Same-origin embedded games reuse the parent's controller to avoid multiple microphones.

The controller is available as `window.NexenVoice`. Methods: `open()`, `refresh()`, `interpret(text)`, `showNumbers()`, `stop()`, `getState()`. `getState()` reports readiness, mode, microphone activity, current state and target count; it always reports `desktopControl: false`. The separate agent-assisted Windows computer-use capability is not integrated into this widget.

Optional typed form: `[data-nexen-voice-form]` containing one input/textarea and a submit button. Optional engine-refresh button: `[data-nexen-voice-refresh]`. The supplied `/voice` page includes both.

## Backend contract

- `GET /api/voice/status`: `{ready: boolean, engine: string, detail: string, desktop_control: ...}`. Only `ready === true` enables microphone recording; typed interpretation remains available.
- `POST /api/voice/transcribe`: raw **signed 16-bit little-endian mono PCM at 16,000 Hz**, at most 20 seconds / 640,000 bytes. Headers: `Content-Type: application/octet-stream`, `X-Nexen-Action: launch`. Response: `{text, confidence?, command}`.
- `POST /api/voice/interpret`: JSON `{text}`, `Content-Type: application/json`, `X-Nexen-Action: launch`. Response: `{command}`.
- All fetches use same-origin session cookies. No provider URL or key is sent from the browser. A locked session produces a clear message without attempting a credential action.

Supported command discriminators:

| `command.type` | Fields / behavior |
|---|---|
| `navigate` | `path`: exact client-allowlisted app route; no external origin, API endpoint, query or arbitrary hash. |
| `scroll` | `direction`: `up` or `down`; scrolls the NEXEN window or open dialog. |
| `show_numbers` | Numbers visible safe local navigation links and explicit workspace-opening buttons. |
| `focus_target` | `number`: integer 1â€“100 from the current visible target set. Shows an in-app focus ring. |
| `click_target` | Same number rules; revalidates the target before requesting its safe action. |
| `stop` | Stops/discards capture, cancels the browser request and invalidates its pending result. |
| `unknown` | Displays `message` as text. |
| `complete_current`, `do_current`, `read_current` | On `/next` only, emits `CustomEvent('nexen:voice-intent', {detail: {type}})` on the owning window. No task ID is inferred or trusted from the transcript. Other pages direct the user to select a task on `/next`. |

The `/next` controller must validate that the user has explicitly selected a current task, own any confirmation/adapter rules, and report its real result. This module never marks a task complete or starts a workflow directly, and it does not generate completion audio or confetti.

## Ask MARVIN mode

The visible mode selector separates Command from Ask MARVIN. On `/problems`, Ask MARVIN is the initial mode. A recognized question in Ask mode ignores any navigation/task command returned by transcription and emits `nexen:voice-intent` with `{type: 'ask_marvin', text}`; the problem page still accepts the legacy `ask_marvin` payload. Typed questions in Ask mode do not call the command-interpretation endpoint.

`problems.html` accepts this event, fills the question field, snapshots the selected photo and local model, and submits the existing `/api/photos` and `/api/life/analyze` flow. It reads a successful draft only through a `speechSynthesis` voice reporting `localService: true`. Remote voices are excluded. If no local voice exists or playback is blocked, the answer stays visible and the page reports that read-aloud is unavailable. A new question never marks the associated task complete or automatically saves the generated suggestion into the reviewed plan.

The page emits `nexen:marvin-state` with `{busy, message}` while its local analysis runs; the widget still accepts the old `nexen:marvin-state` event as a compatibility alias. It prevents starting another Ask recording while busy. Errors preserve the question/photo selection. Stop cancels local voice playback and microphone capture; it does not pretend to terminate a model request already running on the server.

Outside `/problems`, Ask mode stores the recognized text under the tab-scoped `sessionStorage` key `nexen.voice.pending_question`, then opens `/problems`. This entry is valid for five minutes, is consumed when restored, and contains text rather than audio. Restoration does **not** automatically submit: the user can select a photo/model first. If storage is unavailable, the transcript remains visible with an Open MARVIN link instead of silently dropping the question.

## Capture and lifecycle

Push-to-talk only. Record command requests microphone access. Finish & transcribe stops capture and sends exactly one bounded request. Recording auto-finishes after 20 seconds. Stop / discard sends no new audio. After transcription, the transcript and available confidence are displayed before a safe interpreted action.

The implementation uses local AudioContext capture with ScriptProcessorNode and performs weighted resampling to PCM. ScriptProcessorNode is a deprecated but currently supported browser path; if unavailable, the UI falls back to typed commands instead of using cloud speech recognition. Audio lives in browser memory only, with no audio file or localStorage recording. The backend owns its own retention policy.

Microphone denial, unsupported capture, timeout and unavailable-engine states are visible. Hiding/leaving the page or minimizing the panel stops capture. An already-submitted transcription may finish on the local server after Stop; its returned command cannot execute because the request epoch has been invalidated.

## Safe target scope and limits

Only visible DOM links with approved local routes and named, nonmutating workspace controls are numbered. All forms, submit controls, disabled/hidden targets, payment/approval/delete/run/scan/compile/launch controls and external links are excluded. Targets are rechecked when used, so a changed or stale number cannot select an unrelated action. Anchor navigation uses the validated destination directly, not an arbitrary link click handler.

The marker is a NEXEN DOM pointer, not the physical Windows mouse. This increment does not provide hands-free continuous listening, keyboard injection, game movement, 3D-object selection or arbitrary desktop automation. The standalone `/voice` page provides the simplest complete verification surface. Native top-layer dialogs/fullscreen may obscure a body-mounted floating panel; use `/voice` or close the dialog when the panel is not visible.

## Verification

`node --check world-assets/voice-control.js` passed.

`F:/NEXEN_GAME/frontend-development/test_voice_frontend.mjs` passed **58 checks** for allowed navigation, rejected sensitive/form/mutating targets, signed little-endian output, resampling, finite-value clipping, the 20-second cap and Ask-mode isolation from command execution.

`F:/NEXEN_GAME/frontend-development/test_problems_voice.mjs` passed **6 flow fixtures** for the selected photo/model request, local-only readback, cross-page question preservation without auto-submission, model-error preservation, unsupported-photo rejection and busy-request behavior. Those tests execute the actual inline page script with fixture DOM/fetch/voice objects, not a real browser or model.

Actual microphone permission, capture/transcription quality, device-voice playback, browser target overlays and the `/next` event handler still require root's browser verification with the backend running. No microphone was enabled, no audio was recorded and no live transcription/model endpoint was called by this subtask.

