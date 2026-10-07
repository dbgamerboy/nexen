---
name: reel-to-asset
description: Turn an indexed YouTube reel/tutorial source into a paired NEXEN reel investment asset (Codex skill + n8n workflow, one shared asset ID). Use when a research reel has been imported through YouTube memory and should become a reusable skill+workflow bundle with a hover-preview card on the dashboard.
---

# reel-to-asset

Every useful research reel is an investment: it should leave behind both a **skill** (WHY/WHEN/HOW) and a
**workflow** (execution shape), sharing one canonical asset ID, discoverable from a preview card. This skill
wraps `reel_assets.py`, the NEXEN backend module that builds that bundle from an already-ingested
`youtube_memory` source. It never fabricates automation: a workflow is only marked executable when a
compiled, source-cited draft already exists.

## WHY
Reels get watched once and forgotten. Recording *why it was captured*, *when to reuse it*, and *what
concretely runs* turns a one-off video into a durable, cross-linked asset instead of a dead bookmark.

## WHEN
- A YouTube source is already `status: "ready"` in `/youtube-memory` (transcript imported and indexed).
- You want a shareable, hover-previewable card that answers: what is this, why did I save it, when do I use
  it, what happens if I run it.
- Optionally, after compiling a `workflow` draft on that source (richer bundle: an n8n-importable skeleton
  with cited steps instead of a reference-only stub).

## HOW
1. Confirm the source is ready:
   ```powershell
   node .Codex\skills\run-nexen\driver.mjs get /api/youtube-memory/sources/<source_id>
   ```
2. (Optional, recommended) Compile a workflow draft so the bundle becomes executable instead of
   reference-only:
   ```powershell
   node .Codex\skills\run-nexen\driver.mjs post /api/youtube-memory/sources/<source_id>/compile '{"kind":"workflow","model":"<installed-ollama-model>"}' --allow-write
   ```
3. Build (or rebuild — it is idempotent per source) the paired reel asset:
   ```powershell
   node .Codex\skills\run-nexen\driver.mjs post /api/reel-assets '{"source_id":"<source_id>"}' --allow-write
   ```
4. Review the bundle at `H:\NEXEN\v1\app\data\reel-assets\<asset_id>\`: `SKILL.md`, `workflow.json`,
   `diagram.mmd`, `metadata.json`, `preview.json`, `screenshots/`, `source/README.md` (pointer back to the
   original youtube_memory receipt — the transcript itself is never duplicated).
5. Open `/reel-assets` in the dashboard to see the hover-preview card (title, one-line purpose, why, when,
   mini Mermaid diagram, status/tags, Open Skill / Open Workflow / Expand Preview / View Source) and the
   expanded modal (full diagram, skill markdown, workflow JSON, metadata).

## Context / contract
- Canonical ID: `sha256("reel-asset-v1\n" + source_id)[:24]`, shared by `skill_id`, `workflow_id` and the
  bundle folder name. Regenerating from the same source overwrites the bundle in place (lifecycle can
  advance from `captured` to `converted` once a draft is compiled); it never duplicates the row.
- `executable: true` only when the source has a compiled `workflow` draft with cited steps. The generated
  `workflow.json` then uses `n8n-nodes-base.manualTrigger` + one `n8n-nodes-base.noOp` per cited step
  (importable into n8n, but each NoOp is a documented placeholder — replace it with a reviewed adapter node
  before treating it as a real automation). Otherwise the bundle is `reference_only`, `executable: false`,
  with the exact next action to unblock it.
- No cloud model call, no n8n execution, and no invented revenue/ROI/performance numbers happen in this
  module. `metadata.json` lifecycle/cost/effort/revenue/reusability fields default to honest
  `unknown`/`unverified` values until a human fills them in.
- See `diagram-template.mmd` in this folder for the standard source → skill → steps → workflow shape used by
  `build_diagram()` in `reel_assets.py`.
