# NEXEN quality plan

Checked September 9, 2026. This plan defines observable improvements to the working NEXEN app. Suggested thresholds below are proposed NEXEN acceptance targets, not measurements already achieved or requirements imposed by the cited sources.

The aim is to finish real creative and operational tasks with understandable state, reliable knowledge, bounded resource use and recoverable actions. Google PAIR recommends starting with the user's problem and an explicit definition of success, including the downstream effects of the chosen metrics. [PAIR: User Needs + Defining Success](https://pair.withgoogle.com/chapter/user-needs/)

## Local evidence and scope

- Retrieved a bounded SharedMemory context packet for NEXEN/LIFE OS quality, workflow completion, source knowledge and tests. It returned three citations: the authored WDR City plan, an archived assistant conversation and an indexed inventory mapping. Archived assistant text remains historical evidence; checked boxes inside it do not establish that work happened.
- The authored `F:\NEXEN_MEMORY\Plans\WDR-City-build-2026-09-09.md` explicitly calls for one shared state across practical GUI and game workstations, real progress, and a distinction between game XP and real revenue. Its retrieved SHA-256 was `173d2c718d00052a13b09872f8c1cf859c4de9001947aee26f2a8cf509693620`; its timestamp is file metadata, not proof of message chronology.
- Relevant sections of `F:\05_AI\01_EXACT_PROMPTS_AND_CHATS\ALL_COMBINED_PROMPTS_MASTER.txt` call for inventory before file changes, verified backups, retained originals, confidence labels, actionable project boards and bounded concurrency. The earlier exact-folder import recorded its full-read hash and source metadata in `data/exact-prompt-packages/source-report.json`.
- Inspected current contracts in `plan_compiler.py`, `memory_runtime.py`, `harness_bridge.py`, the persistent job queue/recovery methods in `nexen.py`, and the previously verified task/daily/authentication interfaces. This is a scoped review, not an exhaustive code or security audit.
- Research used the primary sources cited below. The parent task also completed a logged-in Perplexity Pro query using a generic architecture prompt without uploading private KB content. Its synthesis reinforced persisted status evidence, idempotent recovery, scoped citations, explicit conflicts, voice state/stop controls, accessible daily focus, resource budgets and end-to-end evaluation. That answer is supporting synthesis rather than a substitute for the primary references; its numerical suggestions are proposed targets, not verified NEXEN performance. [Perplexity research conversation](https://www.perplexity.ai/search/ef4d0bf2-d19e-48ff-ad82-df8ec7fd397d)
- The parent task separately verified one native desktop interaction in Notepad. A successful native-tool test does not establish that the NEXEN autonomous desktop bridge is integrated; that remains a separate implementation and acceptance step.

## 1. Make every action's readiness and result clear — P0

Microsoft's HAX guidance emphasizes communicating capability, likely limitations and the consequences of actions. [Microsoft: Guidelines for Human-AI Interaction](https://www.microsoft.com/en-us/research/uploads/prod/2019/03/AI_Guidelines_Poster_PrintQuality.pdf)

**NEXEN requirement:** Use one action state across `/connections`, `/tasks`, `/plans`, the main GUI and game terminals: prepared, awaiting input, queued, running, succeeded with evidence, failed, or uncertain. Preserve the existing explicit distinction between user-marked completion and independently verified execution. A service being online is separate from an action succeeding.

**Acceptance:** For one fixture action, every view displays the same persistent task ID and status. A prepared WDR brief cannot appear as a generated image. A failed provider call cannot increment a success or revenue counter. A missing login has one specific next step. The housing task remains the first urgent real-life action until its actual task is resolved.

**Current basis:** Prepared/not-executed plans, task history and daily completion history already exist. Consistent action state across every adapter and game interaction remains to be demonstrated.

## 2. Bound waiting and explain uncertain outcomes — P0

HAX recommends efficient recovery when the system is wrong; W3C explains that progress, waiting and error status should be available to assistive technology without moving focus. [Microsoft HAX](https://www.microsoft.com/en-us/research/uploads/prod/2019/03/AI_Guidelines_Poster_PrintQuality.pdf), [W3C: Status Messages, SC 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

**Implemented increment:** `plan_compiler.py` previously used unbounded browser fetches and initially left the status empty. It now displays loading status, bounds plan reads to 15 seconds and compilation waits to 45 seconds, distinguishes authentication failure, clears timers, and restores controls. A compile timeout says the server may still finish. The new Refresh plans control only reloads saved state; it never automatically resubmits a POST. Existing displayed packets are retained if a refresh fails.

**Acceptance:** A stalled read reaches an actionable timeout state. A stalled compilation makes its outcome uncertainty explicit and allows a read-only refresh. No automatic duplicate compilation occurs. Apply this request lifecycle to the other local pages after measuring their actual response times. Aborting a browser wait must never be presented as proof that server work was cancelled.

**Verification:** The deterministic Node regression exercises initial loading, stalled reads, stalled compilation, control recovery, read-only refresh, no POST retry, 401 handling and timer cleanup. Three existing plans/auth/aggregation tests also pass. This does not establish whole-app response-time targets or full browser accessibility conformance.

## 3. Define durable operation IDs before expanding unattended side effects — P0

AWS's durable execution guidance explains that retries/replay can repeat operations, recommends reusing the same idempotency token for a logical effect, and gives conditional writes, transactional checks and deterministic event IDs as database techniques. [AWS: Idempotency and retries](https://docs.aws.amazon.com/durable-execution/patterns/best-practices/idempotency/)

**NEXEN requirement:** Give each logical action a persistent operation key, input hash, attempt number, adapter, state and evidence location. Claim jobs atomically. Where an external provider supports idempotency, persist its token before the first attempt and reuse it. An uncertain non-idempotent write must stop for reconciliation instead of automatically switching providers and repeating the effect.

**Acceptance:** Simulate a process crash after a fake external effect succeeds but before acknowledgement is stored. Restart and retry: the fake provider records one logical effect, with the same key on every attempt. Two workers cannot claim one queued operation. A read-only model fallback does not reuse authorization to publish, call, buy or spend. Verify the fixed Lumipaw limits at the execution boundary before any real ad executor is enabled.

**Current basis:** The existing queue persists attempts and supports recovery/backoff. `harness_bridge.py` already distinguishes uncertain timeouts and declines automatic retries. This review did not establish a complete durable side-effect contract for every adapter.

## 4. Make memory provenance correct and retrieval useful — P1

HAX calls for contextually relevant information and continuity across interactions. The actual retrieval and provenance targets here are NEXEN-specific engineering requirements. [Microsoft HAX](https://www.microsoft.com/en-us/research/uploads/prod/2019/03/AI_Guidelines_Poster_PrintQuality.pdf)

**NEXEN requirement:** Preserve opaque source IDs, hashes and timestamps as structured metadata while redacting credential values. Keep current user decisions distinguishable from authored notes, archived assistant claims and machine-generated inventory rows. Display source coverage and conflicts beside generated plans.

**Observed issue for a separate patch:** The retrieved packet visibly contained `[REDACTED LONG NUMBER]` inside an opaque conversation ID and an archive hash. Blanket string redaction can therefore damage provenance. This task did not change `memory_bridge.py`.

**Acceptance:** A regression fixture preserves legitimate SHA-256/UUID source identifiers while removing API keys, passwords and private endpoints. The original source can be located from every returned citation. Build 20 hand-reviewed questions from the user's actual LIFE OS/WDR tasks; at least 18 should retrieve an expected supporting source within the top five results. “Not indexed” must remain an explicit answer when support is absent. Test one edited manual note after refresh and one conflict between a current instruction and an old export.

## 5. Make corrections, pauses and human completion persist — P1

PAIR recommends allowing users to adjust output, control automation and use a manual fallback; it also cautions against promising feedback effects that the product cannot deliver. [PAIR: Feedback + Control](https://pair.withgoogle.com/guidebook-v2/chapter/feedback-controls/)

**NEXEN requirement:** A corrected plan, reopened task, cancelled pending action or disabled collection source must remain changed after restart and in both GUI/game views. Voice may propose a task, but its interpretation and effect must be inspectable and correctable. Keep the typed/manual path available when speech or a model fails.

**Acceptance:** Correct one inferred requirement and confirm the next context packet uses the approved correction while retaining its historical alternative. Pause a fixture worker and restart the app: it stays paused. Reopen a completed task: its prior completion remains in history and the active state changes everywhere. Repeated recognition of the same voice request does not silently create duplicate side-effect jobs.

**Current basis:** Task reopening and completion journals are tested. A unified cancellation/feedback contract across voice and every execution adapter remains future verification.

## 6. Keep the practical GUI fully usable with keyboard and readable status — P1

WCAG SC 2.4.7 requires a visible keyboard focus indicator; SC 4.1.3 covers programmatically identifiable status updates. The linked Understanding documents explain those requirements and are not themselves a full conformance test. [W3C: Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html), [W3C: Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

**NEXEN requirement:** The game is an optional interface to the same functions. Service checks, login steps, task completion, source review and recovery must work from ordinary pages without requiring driving, a mouse or audio. Maintain visible focus, meaningful labels and status regions; avoid stealing focus when a background operation reports progress.

**Acceptance:** A keyboard-only pass can unlock NEXEN, find an urgent action, open its requirements, inspect a source, mark/reopen a task and pause work. Every focused control remains visible. A screen-reader pass announces loading, failures and successful completion once at a useful level of detail. Reduced-motion preference is respected for decorative completion/game-adjacent animation. Contrast and screen-reader behavior still need a real browser audit.

## 7. Budget model and background work around creative use — P1

PAIR distinguishes work suited to automation from work where the user benefits from control, and recommends evaluating meaningful outcomes rather than only a narrow immediate metric. [PAIR: User Needs + Defining Success](https://pair.withgoogle.com/chapter/user-needs/)

**NEXEN requirement:** Preserve the KB's bounded-concurrency intent, with interactive tasks ahead of background ingestion and plan generation. Expose model readiness, token/output limits, timeout, context provenance and whether a request could incur charges. Retain the currently disabled paid fallback unless explicitly configured under the user's limits.

**Acceptance:** With background ingestion active, an interactive request still receives immediate accepted/busy status and an accurate owner/job ID. A cancelled or failed request releases its slot. A missing provider does not trigger a paid fallback. Benchmark the user's actual music/gaming workload before setting CPU/GPU concurrency; this review does not claim a measured latency or audio-dropout budget.

## 8. Ship improvements against repeatable user scenarios — P2

**NEXEN requirement:** Maintain a small regression set based on the actual knowledge base and user priorities. Track verified completed actions, correctly surfaced blockers, recovery outcomes and time to useful next step. Prepared prompt count and game exploration XP stay separate from work completion and money.

**Acceptance:** Before the next release, demonstrate five scenarios using fixture providers where needed: urgent-life action review; WDR source-to-production brief with a missing reference; music-project next step; interrupted local workflow recovery; and password-protected phone access. Record exact evidence, unresolved dependencies and changed files for each. A release passes only if existing completion history and source provenance survive the upgrade.

This is a proposed product acceptance set grounded in the user's practical goals and PAIR's outcome-oriented evaluation guidance. [PAIR: User Needs + Defining Success](https://pair.withgoogle.com/chapter/user-needs/)

## Reproduce this task's verification

From `F:\NEXEN_GAME\NEXEN_Autonomy_v0.1`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'D:\yum\NEXEN_Autonomy_v0.1\.venv\Scripts\python.exe' -B -m unittest test_plan_sources -v
& 'C:\Program Files\nodejs\node.exe' 'F:\NEXEN_GAME\quality-development\test-plan-requests.cjs'
```

The existing D: interpreter and installed Node binary are read-only dependencies in this verification. New code, fixtures and research artifacts are on F:. The redacted local context snapshot is `F:\NEXEN_GAME\quality-development\local-quality-context.json`. This subtask changed only `plan_compiler.py` in the running application and added its scoped regression/artifact files; it did not implement the other seven priorities or claim all NEXEN features complete.
