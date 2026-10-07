# NEXEN SOT (source of truth)

Date: 2026-10-06. When two sources disagree, the higher row wins.

| Topic | Source of truth | Not the source |
|---|---|---|
| Decisions | `F:\NEXEN_MEMORY\NEXEN Shared Memory\Current Decisions.md` | old chats, archived plans |
| Live state | `00-Control\MASTER-PACKET.md` and `SESSION-LOG.md` tail | summaries in chat |
| Tasks | `H:\NEXEN\v1\app\data\nexen.db` (canonical task 142 and the 318-row snapshot) | the frozen F: app copy |
| Product name | NEXEN, one exe `NEXEN.exe`, hub `H:\NEXEN-FINAL` | NEXEN, V3, Business Operations as names |
| Code | `H:\NEXEN-ENTERPRISE` tree (this build) | `F:\NEXEN_GAME`, desktop shortcut folders |
| Program list | `Evidence\FinalBuild\program-inventory.csv` | shortcut names |
| F: dependencies | `Evidence\FinalBuild\preflight.json` | memory |
| Ingest source | `F:\05_AI` (read only) | the old ingest output |
| Spending | exact MARVIN approval per amount, purpose, provider, scope | blanket permission |
| Higgsfield | owner message 2026-10-06 grants use; account state unverified | the 2026-10-04 skip note (superseded) |

Status words: queued, prepared, tested, connected, running, published, paid. A prepared item is never reported as running.
