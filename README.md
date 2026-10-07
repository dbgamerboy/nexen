# NEXEN

AI infrastructure around the MARVIN assistant: learning, memory, routing, approvals and money lanes.

- `NEXEN/`: the application (src/nexen, hub, tests, workflows, config). Run: `python NEXEN/run.py serve --port 8794`. Tests: `cd NEXEN; python -m unittest discover -s tests -t .`.
- `NEXEN_MODULES/_curated`: 15 vetted standalone modules the app may run; outbound ones need owner approval.
- `NEXEN_SCRIPTS/`: start files and helper tools.
- `NEXEN_MEMORY/docs`: PRD, TRD, source of truth, code ranking.
- `NEXEN_DATA/`: placeholder, data stays local.

No credentials are stored here. External effects (posting, sending, spending) go through an approval queue.
See USE-THIS.txt.
