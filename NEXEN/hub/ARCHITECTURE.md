# NEXEN architecture implemented here

```text
F:\ + configured roots
        |
        v
Universal Ingestion Engine
        |
        v
SQLite provenance + FTS index
        |
        +--> knowledge_items
        +--> goals
        +--> workflow candidates
        |
        v
Workflow Factory
        |
        v
Tool / Capability Fabric
        |
        +--> MCP
        +--> API
        +--> CLI
        +--> browser
        +--> local executable
        |
        v
Persistent job queue
        |
        +--> Ollama
        +--> OpenAI
        +--> Anthropic
        +--> future OpenClaw / n8n / Amboras adapters
        |
        v
24/7 Supervisor
        |
        v
MARVIN + local dashboard
```

## Next adapters

### OpenClaw
- discover approved capabilities
- call known tasks
- collect logs/results
- return structured outputs to NEXEN

### n8n
- create/import workflow templates
- invoke webhooks
- query execution status
- keep credentials out of source code

### Amboras
- prefer official API if available
- otherwise use a browser adapter
- treat store/product modifications as external writes
- place ad-spend/refund/money actions behind stronger approvals

### PC2 worker
- PC1 remains source of truth
- PC2 leases jobs
- heartbeat + lease timeout
- return structured results

### Contradiction reviewer
- group conflicting statements
- show old vs current plan
- KEEP / SWITCH / MERGE controls
- never erase original source

### Money ledger
Track per workflow:
- revenue
- COGS
- ad spend
- API/software costs
- refunds
- contribution profit
- ROI

## Novel Learning and recursive learning

The existing memory path stays the source of truth: bounded `SharedMemory`
retrieval supplies citations, and the normal ingestion path preserves source
provenance. Recursive learning is a separate companion gate for candidate
claims and their follow-ups. It does not replace or rewrite Novel Learning.

```text
Novel Learning output + explicit current scope/references
                         |
                         v
Recursive candidate preview (/api/memory/recursive-learning/preview)
   | duplicate / declared overlap / missing evidence / unclear match
   +------------------------------------------------------> hold/exclude
   |
   v
Proposal ready -> owner review -> existing authorized memory-ingestion path
                 |
                 +-> feedback ledger (candidate hash + decision; no raw text)
```

The preview accepts a bounded parent-linked candidate list, source IDs,
current Novel Learning scope terms or reference items, and citations retrieved
from the existing memory bridge. It checks exact duplicates, declared scope
matches, and lexical near-matches. Ambiguous matches, missing provenance, and
an absent Novel Learning scope stay in review. Recursion is capped at three
follow-up levels and 50 candidates. The feedback endpoint retains the latest
owner decision by content hash, so repeated inclusions/exclusions are
consistent without copying candidate text into a second knowledge store.

`proposal_ready` means eligible for human review only. The preview never writes
the knowledge index, downloads sources, calls a model, or runs text as an
instruction. After owner approval, callers must use the existing
provenance-preserving ingestion path. The current checkout exposes the
evidence-based memory flow but no explicit Novel Learning adapter contract; the
companion therefore requires callers to supply current Novel Learning scope or
references and fails closed if they are missing. This is a boundary gap in the
checkout, not a claim that Novel Learning itself does not exist elsewhere.
