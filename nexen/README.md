# NEXEN

One app that tracks, learns and connects every NEXEN piece. V3 is frozen. V4 reads V3 and the F: legacy lines through read-only adapters and writes only under `Data\V4` and the vault's `00-Control/Handoffs/nexen/` folder.

## Start
- Double-click `NEXEN.exe`. It starts the Python engine, opens the app window (Edge app mode) and sits in the tray. It restarts the engine if it dies (max 5 per 10 minutes) and when an update writes `Data\V4\restart.flag`.
- Without the exe: `nexen.cmd serve`, then open http://127.0.0.1:8794/.
- CLI: `nexen.cmd status`, `nexen.cmd context "topic" --print`, `nexen.cmd learn recursive "question"`. Full list: `nexen.cmd --help`.
- MCP: `python run.py mcp` (ten tools). Registration commands are in `tools\register_mcp.ps1` and are not applied automatically.
- Tests: `nexen.cmd selftest` (38 tests).
- Rebuild the exe: `tools\build_exe.ps1` (uses the .NET compiler already on Windows). The exe is only a shell, so updates never need a rebuild.

## Pieces
| Piece | Where | What it does |
|---|---|---|
| Novel Learning | `engine/nexen/learning/novel.py` | Novelty gate with ADD, UPDATE, REINFORCE, NOOP, HOLD; validity windows; recall as of a past date; gap map; quality-diversity archive |
| Recursive Learning | `learning/recursive.py` | Question to evidence to gate to follow-up questions, depth 3 max; UCB1 strategy choice; lessons; skill recipes |
| Self-tuning | `learning/meta.py`, `golden.py` | Edits five gate parameters from labels, blocked by golden cases, logged, reversible |
| Connectors | `connectors/agents.py`, `nexen.py` | Codex, Antigravity, Hermes, Claude Code, ChatGPT exports, MARVIN, canonical tasks, vault |
| Gate | `gate.py` | Internal work unattended; external effects queued for the owner; STOP honoured |
| Registry and buttons | `registry.py`, `modules/*.json` | Every piece with a health probe and buttons, including Business Operations and MARVIN actions |
| Server, UI | `server.py`, `ui/index.html` | Local API on 127.0.0.1:8794 and the app window |
| Updater | `updater.py` | Verified, backed-up, tested, reversible live updates |

## Add something later (live)
1. Button or module: drop a `.json` file into `modules/`. It appears in the app within seconds, no restart. Format: `{"id","name","line","kind","probe":{"path"|"http"|"cli"},"buttons":[{"id","label","kind":"view|url|script|folder|file","target"}]}`. Launch targets must sit under `H:\NEXEN-ENTERPRISE`, `H:\NEXEN`, `H:\NEXEN-VideoStudio` or `H:\NEXEN_V3`.
2. Code: `python -c "from nexen import updater; updater.make_package('name','4.0.1',['engine/nexen/x.py'],'notes')"` (run from `engine`), then press Apply in the Update tab or POST `/api/update/apply`. Apply verifies sha256 for every file, allows only `engine/`, `ui/`, `modules/`, backs up the old files, runs the test suite, rolls back on any failure, and asks the exe to restart the engine when engine files changed.

## Intelligence layer (added 2026-10-06)
| Piece | Where | What it does |
|---|---|---|
| Intellect spine | `spine/problems.py`, `engine.py` | 72 predetermined problem classes with playbooks (OPS-001 to OPS-010 come from the NEXEN and MARVIN boot, bus and autonomy logs; `indicators.py` checks three of them live: boot stderr, missing bus handlers, log size); diagnosis, optimized variant choice, composed candidates for novel problems that promote after two clean successes, premortem, live indicators |
| Rules engine | `spine/rules.py` | Quotas, test accounts, experiments, graduation, mirroring and cap-evasion refusal, spend, clipping, STOP; lawful alternatives; 3,072-situation matrix |
| Swap registry | `spine/swap.py` | Models, LoRA/QLoRA adapters, methods, hustles, stores, sources, accounts as slots with health, cooldown, revert |
| Knowledge packs | `spine/packs.py`, `stores.py` | Nine agents, each with its own pack; every prompt fans out to every store and leaves a receipt |
| World model | `spine/world.py` | GDELT, Hacker News, Wikipedia, Mastodon, RSS, each labeled with what it measures |
| Routine | `spine/schedule.py` | Money and stability first; any block movable at any time |
| Research viewer | `spine/research.py`, UI Research tab | Learned items with source links, YouTube transcript research, rule-checked workflow drafts |
| MARVIN core | `marvin/` | Traces, complexity, skill discovery, learning orchestrator with eval gate, bounded agent loop, tested self-patching |
| Reliability | `reliability.py` | Guarded entry points, diagnosed structured failures, `nexen doctor --fix` |
| Identity | `identity.py` | JARVIS = MARVIN, hard-coded |
| n8n | `H:\NEXEN-ENTERPRISE\Workflows\V4` | MARVIN Gateway, Routine Tick, Research to Draft: inactive until imported and enabled |

Commands: `nexen decide`, `ask`, `prompt`, `spine ...`, `rules ...`, `swap ...`, `world ...`, `schedule ...`, `research ...`, `workflow ...`, `agent`, `selfcode`, `orchestrate`, `doctor`, `who`.
Training corpus: `tools\build_corpus_v4.py` (master dataset plus spine shard). Name recode: `tools\name_recode.py` writes the recoded source copy and manifest under `H:\NEXEN-ENTERPRISE\Source\NEXEN-core`. License decisions: `NOTICE.md`.

## Honest limits
- Novel Learning's old home was a stub: `H:\NEXEN\tools\continuous_learning_watcher.py` only logs file names to `Marvin_Brain_Index.json`. V4 reads that queue and does the actual judging. V3's `recursive_learning.py` stays untouched.
- Lexical similarity only unless an embedding function is supplied. It will miss paraphrases with no shared words.
- Chat-derived items are low trust (0.35) until a second independent source corroborates them.
- ChatGPT has no local API. Packets are written, never sent.
- F: is failing. Vault walks are time-boxed and prefer the recovered H: copy.
- Live autonomy is gated by the owner's global STOP. V4 does not remove it.
