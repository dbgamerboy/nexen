---
name: run-nexen
description: Run, start, check, log into, screenshot, API-call and test the live NEXEN V1 app (FastAPI hub on 127.0.0.1:8788). Use when asked to run NEXEN, start NEXEN, check if NEXEN is up, screenshot a NEXEN page, call a NEXEN API route, or run NEXEN's tests.
---

# run-nexen

NEXEN is a FastAPI app (`nexen.py` â†’ uvicorn `nexen:app`) serving about 30 HTML pages and a JSON API on **127.0.0.1:8788**. You drive it with **`driver.mjs`**, a Node 24 script with no dependencies: `fetch` for the API, headless Chrome over CDP for screenshots, and the recovery Python for tests. Paths below are relative to the app root `F:\NEXEN_GAME\NEXEN_Autonomy_v0.1`.

## Prerequisites (already on this machine)
- Node 24 on PATH (`node --version` â†’ v24.19.0)
- `H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe` (Python 3.12 with fastapi). This is the only interpreter that runs NEXEN.
- Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe`

## Run (agent path)
```powershell
node .Codex\skills\run-nexen\driver.mjs health
node .Codex\skills\run-nexen\driver.mjs start
node .Codex\skills\run-nexen\driver.mjs get /api/auth/session
node .Codex\skills\run-nexen\driver.mjs shot /login H:\NEXEN\temp\run-nexen\login.png
node .Codex\skills\run-nexen\driver.mjs test test_app_auth_navigation test_hub_startup test_task_tracking test_private_access
node .Codex\skills\run-nexen\driver.mjs test
```
- `health` prints `UP {"status":"ok"}`.
- `start` skips if 8788 is already up ("already runningâ€¦"). Otherwise it launches `nexen.py serve` hidden and waits up to 180 s for `/healthz`.
- `get` prints the HTTP status and the body, truncated to 3,000 chars. Without login, `/api/*` returns `401 {"detail":"Unlock NEXEN first."}`.
- `shot` saves a PNG and prints the page title and path. Screenshots go to `H:\NEXEN\temp\run-nexen\`.
- `test` with no modules runs the full suite: **424 tests, OK (skipped=1), ~75 s** (verified 2026-09-26). The 4-module subset: 21 tests in ~1 s.

### Authenticated pages and API
The owner password is not stored anywhere readable. Set it **for this shell only**, then log in:
```powershell
$env:NEXEN_PASSWORD = "<owner password>"
node .Codex\skills\run-nexen\driver.mjs login
node .Codex\skills\run-nexen\driver.mjs get /api/tasks
node .Codex\skills\run-nexen\driver.mjs shot /next H:\NEXEN\temp\run-nexen\next.png
```
The session cookie is saved to `H:\NEXEN\temp\run-nexen\session.cookie` (about 12 h) and reused by `get`, `post` and `shot`. Writes need `post <route> <json> --allow-write`, which adds `Origin` and `X-Nexen-Action: launch`.

## Run (human path)
Open http://127.0.0.1:8788 in a browser and unlock with the owner password. NEXEN is normally already running (started by `H:\NEXEN\launcher\Start-NEXEN-Focus.ps1`).

## Gotchas
- **The port is hard-wired.** Host must be `127.0.0.1:8788`, `localhost:8788` or `[::1]:8788` (pc_control.py / private_access.py), so a second copy on another port gets 403 on every page. `start` never launches a second copy.
- **Only the recovery Python works.** The app `.venv` has no fastapi. Every launcher that names `F:\yum\...\.venv` (START_NEXEN.ps1, RUN_N8N.ps1, RUN_FIRST_SCAN.ps1, nexen_v2_supervisor.pyw) is dead, because that folder no longer exists.
- **Login lockout:** 5 failed logins in 15 min returns 429. The driver never retries a login.
- **`/` redirects to `/login` when logged out.** The page title is "Unlock NEXEN V2", even though the folder is V1.
- **Writes need three headers:** exactly one `Origin: http://127.0.0.1:8788`, the session cookie and `X-Nexen-Action: launch`, or the call is rejected.
- **`nexen.py` CLI subcommands** (`scan`, `compile`, `marvin`, â€¦) load the whole app and write to the live `data/nexen.db`. Don't use them just to test.
- **The background autonomy loop** scans and queues Ollama jobs every 30 s unless `data/PAUSE_AUTONOMY` exists.
- **The running server is two processes:** the venv shim plus its base-Python child, which holds 8788. `stop` only kills what this driver started (PID file), never the owner's running hub.

## Troubleshooting
- `DOWN` from `health`: run `start`, then read `H:\NEXEN\temp\run-nexen\server.err.log`.
- `401 Unlock NEXEN first.` on `/api/*`: not logged in. Set `NEXEN_PASSWORD` and run `login`.
- `NEXEN_PASSWORD not set`: set it in the current shell only. Never write it to a file.

