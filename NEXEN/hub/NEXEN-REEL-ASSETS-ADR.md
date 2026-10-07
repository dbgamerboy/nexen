# ADR: Reel investment assets (skill + workflow pairing)

Status: implemented; real-source bundle built and inspected. Updated 2026-09-30.

## Decision

Use the existing H: V1 application, `youtube_memory` source authority, `nexen_hub.register()` route pattern and `/reel-assets` page. Keep the bundle file based at `H:\NEXEN\v1\app\data\reel-assets\<asset_id>\`; do not create a second app or database registry. Ingestion accepts an indexed YouTube source ID or an original supported HTTPS URL plus supplied transcript for Instagram, TikTok or YouTube. Optional creator/date and up to three real images are preserved only when supplied; image files are limited to `H:\NEXEN\intake` and copied into the bundle.

## Canonical identity and bundle

`asset_id = sha256("reel-asset-v1\n" + source_id)[:24]`. The same ID appears in the skill frontmatter, workflow, metadata, preview and folder. Source transcript digest/segments, source pointer, extracted lesson, source references, assumptions/verification, and evaluation/lifecycle metadata travel together. Bundle rebuilds are deterministic and idempotent for the same source.

Files: `SKILL.md`, `workflow.json`, `metadata.json`, `preview.json`, `diagram.mmd`, cached stdlib-generated `diagram.svg`, `screenshots/`, and `source/README.md`, `source/transcript.md`, `source/verification.md`.

## Workflow and lifecycle

- `captured`: source and transcript are present; workflow is a reference-only shell.
- `converted`: a source-cited workflow draft exists and proposed steps appear as NoOp nodes. It is still `executable: false`; there is no generic Run action.
- `tested`, `active`, and `retired` remain false until their own evidence-backed transition is implemented and recorded.
- A future Run action requires a reviewed typed adapter, explicit inputs/outputs, bad-case tests, a real-input check, and checked result evidence. The current `/workflows` architecture exposes only limited approved execution adapters; this module does not bypass those gates.

Unknown access/cost, effort, revenue relevance, reuse and ROI stay explicitly unknown/unverified. The app must not turn a transcript or generated proposal into a financial claim.

## UI and diagrams

The existing dashboard page serves a rich hover/focus preview with purpose, rationale, when-to-use, what happens if opened/run, shared IDs, Mermaid source, cached SVG diagram, up to three real evidence images, status/tags and Open Skill / Open Workflow / Expand Preview / View Source. Expanded detail shows full transcript, explanation, workflow shape and evaluation/verification metadata. The SVG uses the standard library; Mermaid source remains available for editing and external rendering.

## Real proof

Primary short-form proof: Instagram reel `https://www.instagram.com/reel/DWmX1QKCE0O/`, source asset ID `4bb838b7649012b8d68beab9`, bundle under `data/reel-assets/4bb838b7649012b8d68beab9/`. It was built from the existing transcript, analysis card, media receipt and three actual frames at `H:\NEXEN\intake\workflow-reel-20260913\`. Transcript SHA-256 is `64e85335864b78b4536666ecd000253511e86ce9be4407cc2b04cb581c3d7a7a`. The source date and creator were not established; the media receipt capture date is kept separately. Existing analysis explicitly labels this music-royalties reel a non-match for the requested n8n demo. The asset therefore stays `captured`, `reference_only`, `executable: false`, not tested, with claims and proper-name transcription caveats retained.

Additional indexed-source proof: YouTube source `6ad9c24266b5a0f23198383d`, “Creating Your Own Agentic OS is Easy (Insanely Powerful),” URL `https://www.youtube.com/watch?v=w0S-khYCaB4`, bundle `89271fb329e7a3bae69abd7a`. Its source ID and transcript digest remain linked; creator/publication date remain unknown. It is also a captured reference until reviewed deterministic adapters and tests exist.

## Remaining work

An approved local workflow draft may be added after the pause is lifted. Mapping its steps to reviewed n8n adapters and lifecycle advancement to tested/active remain future work. Do not claim execution-ready automation until those gates pass.
