# NEXEN notices and license decisions

## JARVIS = MARVIN
The assistant is MARVIN. JARVIS is only its earlier name (owner decision 20260926-jarvis-is-marvin, hard-coded in `engine/nexen/identity.py`). Prose, comments and prompts are rewritten to MARVIN. File names, routes and keys that other code depends on are kept and mapped. Third-party project names are proper nouns and are never rewritten.

## Third-party JARVIS projects found in the arsenal, and what V4 may take from each
| Project | License | Code use in a money-making NEXEN | What V4 did |
|---|---|---|---|
| open-jarvis/OpenJarvis (Stanford) | Apache-2.0 | Allowed with attribution | Concepts only, code written fresh: trace store, complexity scoring, skill discovery from traces, trace -> learn -> eval-gate orchestrator |
| Edw590/VISOR | Apache-2.0 | Allowed with attribution | Not used yet |
| rajkishorbgp/JARVIS-AI-Assistant | MIT | Allowed with notice | Not used yet |
| isair/jarvis | Custom non-commercial | Not allowed: commercial use needs a separate license | No code used; ideas only (voice-first, local memory) |
| ethanplusai/jarvis | Custom non-commercial, no revenue use | Not allowed | No code used |
| Arnav3241/Jarvis-v13 | AGPL-3.0 | Copyleft: would force publishing derived code | No code used |

The owner's priority is money, so only Apache and MIT sources may supply code. Concept-level inspiration is not copyrightable, and V4 wrote its own implementations.

## Research the learning design follows
SAGE novelty gate (arXiv 2605.30711), Mem0 ADD/UPDATE/NOOP, Zep temporal validity, Voyager skill library, Reflexion and ReasoningBank lessons, Darwin Godel Machine archive and empirical self-modification gate, MAP-Elites quality-diversity, OpenJarvis learning loop.

## Public data used by the world model (free, keyless, read-only)
GDELT DOC 2.0 (news tone), Hacker News Algolia API (attention), Wikimedia pageviews (what people looked up), Mastodon trending tags, BBC and NPR RSS headlines. Each reading is labeled with what it measures. None of it is public opinion on its own.
