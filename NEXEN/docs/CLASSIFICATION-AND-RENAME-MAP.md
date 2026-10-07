# Classification and rename map

Date: 2026-10-06. Classification is by role from the name and the scan. Nothing here is marked working until tested.

## Tier A: wire into the core (MARVIN and money)
Runtime and routing: MARVIN_RUNTIME_ENGINE, NEXEN_UNIFIED_ORCHESTRATOR, NEXEN_24_7_AUTONOMY_LOOP, NEXEN_FINAL_MASTER_HUB, NEXEN_FINAL_ROUTER_INTEGRATION, NEXEN_FINAL_IMMORTAL_ROUTER, NEXEN_FINAL_RAY_ROUTER, NEXEN_FINAL_MARVIN_API_BINDER, context_agent, agent_team_orchestrator.
Reliability: MARVIN_RESOURCE_GOVERNOR, MARVIN_THERMAL_GOVERNOR, MARVIN_CIRCUIT_BREAKER, DBSOPAID_HEARTBEAT_MONITOR, NEXEN_ESCALATION_PAGER, HIGGSFIELD_WATCHDOG.
Learning and memory: MARVIN_SELF_EVOLUTION_LOOP, MARVIN_GOLDEN_CODE_INJECTOR, NEXEN_HYBRID_MEMORY, NEXEN_KNOWLEDGE_EXTRACTOR, NEXEN_DISTILLATION_ENGINE, qdrant_ingest_pipeline, plus the V4 recursive learning and novel learning modules.
Quality: NEXEN_QUALITY_CONTROL_AGENT, NEXEN_FINAL_QA_CRUCIBLE, NEXEN_METRICS_PROVER, MARVIN_WORKFLOW_ROI_CALCULATOR.
Money: LOCAL_LEAD_GENERATOR, NEXEN_APEX_REVENUE_ENGINE, NEXEN_FINAL_B2B_EXECUTION, NEXEN_DROPSHIP_FACTORY, NEXEN_OMNI_MONEY_MATRIX, NEXEN_THE_MILLION_DOLLAR_PIPELINE, NEXEN_COMMS_DISPATCH (approval gated), NEXEN_MASTER_DISCORD_REPORTER, discord_ping.
Recovered set: clippers (paid or research only), Clipping Service Clip Generator and QA gate, Context Slappa, Knowledge sync, OpenJev router, Hermes rotator, PC2 packet bridge, Business Operations engines, Archive OCR and embedding ingestion, Reel asset workspace, Autonomy and watchdog modules.

## Tier B: keep as optional modules
NEXEN_MUSIC_PROMO, Music Factory, NEXEN_VOICEBOX_MODULE, NEXEN_MULTIMODAL_RIPPER, NEXEN_3HR_VIDEO_BRIEFING, NEXEN_PROBABILITY_ENGINE, NEXEN_NEXT_UNIFIED_DASHBOARD, NEXEN_FINAL_EMPIRE_DASHBOARD, HARDWARE_AWARE_DISTRIBUTED_FORGE, NEXEN_FINAL_DISTRIBUTED_FORGE, NEXEN_FINAL_LOCAL_FORGE_PC1, NEXEN_FINAL_LAN_BRIDGE_SETUP, NEXEN_SUPER_MODEL_FORGE, train_nexen_super, NEXEN_FINAL_AI_MODEL_SYNDICATE.

## Tier C: archive, unrelated to MARVIN or money
Personal and life: NEXEN_BIOMETRIC_LOGGER, NEXEN_ETERNAL_LEGACY, NEXEN_SURVIVAL_BENEFITS_AUTOMATOR, Benefit Applier, WDR City, WDR lookbook, Dorion camera bridge, Drive cleanup recommender, Final Boss and Relay installers, G0DM0D3 source tree, Gaming AutoClipper duplicate, Older Whop campaign clipper, Older fine-tune packagers.
Redundant: NEXEN_100_COMMANDMENTS, NEXEN_FINAL_PURGE_AND_OPTIMIZE, NEXEN_FINAL_OFFLINE_BRIDGE_UPDATE, NEXEN_FINAL_CORE_SYNTHESIS, deploy_FINAL_swarm, patch_grammar, AGENT_HR_DIRECTOR, AGENTIC_OS_BRIDGE.
Review before any use: generate_1000_links, generate_3000_links, swarm_scraper, NEXEN_FINANCIAL_AUTONOMY (moves money, so approval only), NEXEN_NEXT_ACCOUNT_MANAGER.

## Tier X: refused, archived, never wired
MARVIN_OPSEC_ANTI_BAN, MARVIN_ONLYSCAMS_OPSEC, MARVIN_FINGERPRINT_VAULT, NEXEN_GHOST_PROTOCOL, NEXEN_ANTI_SABOTAGE_LOCK, UNCENSORED_AGENT_LOOP, MARVIN_ALGORITHM_SNIPER, MARVIN_CIRCADIAN_CYCLE (ban or detection evasion by name; confirm by reading before final placement).

## Rename map (one name: NEXEN)
| Old | New | When |
|---|---|---|
| Desktop `NEXEN Programs - Recovered` | Desktop `NEXEN Programs\Recovered` | now (shortcuts only) |
| Desktop `NEXEN_ALL_PROGRAMS` | Desktop `NEXEN Programs\Scripts` | now (shortcuts only) |
| `H:\NEXEN-ENTERPRISE\Apps\NEXEN` | `H:\NEXEN-FINAL\Apps\NEXEN` | at cutover |
| `NEXEN.exe`, `nexen.cmd` | `NEXEN.exe`, `nexen.cmd` | at cutover |
| `H:\NEXEN\v1\app` | `H:\NEXEN-FINAL\Core` | at cutover |
| `H:\NEXEN\apps` | `H:\NEXEN-FINAL\Modules` | at cutover |
| `F:\NEXEN_GAME\NEXEN_Autonomy_v0.1` | Archive, read only | at cutover |

Live folders are renamed at cutover, not now. Other sessions have about 30 Python processes running from these paths, and an early rename would break them.

## Module bridge results (2026-10-06, real run through the approval gate)
- Ran ok: MARVIN_CIRCUIT_BREAKER, MARVIN_WORKFLOW_ROI_CALCULATOR, NEXEN_OMNI_MONEY_MATRIX, NEXEN_UNIFIED_ORCHESTRATOR. The first two print fixed success or kill text without computing it, so "ran ok" is not proof of real work.
- Queued for owner approval (outbound code), not executed: agent_team_orchestrator, NEXEN_24_7_AUTONOMY_LOOP, NEXEN_APEX_REVENUE_ENGINE, NEXEN_FINAL_QA_CRUCIBLE, NEXEN_MASTER_DISCORD_REPORTER, NEXEN_THE_MILLION_DOLLAR_PIPELINE.
- Fail: context_agent, NEXEN_DROPSHIP_FACTORY, NEXEN_FINAL_IMMORTAL_ROUTER (timeout at 8 s), qdrant_ingest_pipeline (needs `qdrant_client`).
- Syntax errors (Windows paths in plain strings): MARVIN_RUNTIME_ENGINE, NEXEN_COMMS_DISPATCH.
