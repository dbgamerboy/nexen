# NEXEN

AI infrastructure around the MARVIN assistant: recursive and novel learning, memory, routing, approvals and money lanes.

- `nexen/`: the application (164 passing tests; run `python -m unittest discover -s tests -t .` inside it)
- `modules/`: standalone modules with real logic, compile-checked only
- `docs/`: PRD, TRD, source of truth, classification

External effects (posting, sending, spending) go through an approval queue. No credentials are stored in this repo.
