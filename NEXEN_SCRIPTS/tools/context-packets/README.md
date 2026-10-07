# Local-model skill and context router

Codex and Claude skills are instruction packages, not capabilities that a local model automatically inherits. This packet builder explicitly selects the relevant `SKILL.md` files and NEXEN knowledge notes, hashes them, bounds the context size, redacts credential-shaped assignments, and writes one JSON task packet for Ollama or another approved local harness.

## Example

```powershell
& .\Build-NexenContextPacket.ps1 `
  -Objective 'Draft three original LumiPaw hooks and cite the supplied research' `
  -SkillPaths '%USERPROFILE%\.codex\skills\workflowgenerator\SKILL.md' `
  -KnowledgePaths 'H:\NEXEN\knowledge\NEXEN FULL RUN and Virality Operating Plan.md' `
  -OutputPath 'H:\NEXEN\queue\packets\lumipaw-hook-task.json'
```

The worker must return a result packet with the input packet hash, model identity, start/end time, outputs, tests or checks, and unresolved risks. A local model result remains a draft until its acceptance checks pass.

## Routing rule

- Small local model: classification, extraction, summaries, hook scoring, metadata, ticket drafting.
- Frontier model: architecture, ambiguous strategy, difficult code, complex review.
- PC2: bounded context packets, research, audio analysis, transcription, lightweight local inference.
- PC1: integration, final QA, and one heavy GPU job at a time.

