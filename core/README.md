# NEXEN Autonomy v0.1

This is a runnable control-plane starter for the architecture you asked for.

## What it already does

- Indexes configured PC folders, including the whole `F:\` by default.
- Preserves source provenance, file hashes, and full-text searchable chunks.
- Extracts goals, constraints, tasks, tools, ideas, and workflow candidates.
- Uses **Ollama first**, then optional OpenAI, then optional Anthropic.
- Keeps a persistent SQLite job queue, retries, events, approvals, tools, and workflows.
- Discovers installed CLI tools from a manifest.
- Compiles workflow candidates into normalized JSON execution specs.
- Automatically sends money/destructive/external-write workflows to an approval queue.
- Runs a 24/7 supervisor loop.
- Generates a factual MARVIN daily brief from real NEXEN telemetry.
- Serves a local dashboard at `http://127.0.0.1:8788`.

## What it intentionally does NOT do yet

- Delete, rename, or reorganize your files automatically.
- Blindly execute install commands found online.
- Log into ChatGPT by stealing browser cookies.
- Move real money or trade a brokerage account.
- Pretend an unresolved handwritten tool name is a verified package.

Those are separate adapters / permission classes.

## Install — one shot

Extract the folder, open PowerShell inside it, then:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\INSTALL_NEXEN_AUTONOMY.ps1 -InstallScheduledTask
```

Default target: `F:\NEXEN_AUTONOMY`.

If `F:` is unavailable it uses `H:\NEXEN_AUTONOMY`. If neither allowed drive is available, installation stops. Explicit targets outside H: or F: are rejected before creating files.

The installer preserves existing data and configuration and stops on conflicting program files. Its compatibility switch `-InstallScheduledTask` registers the H/F watchdog launcher through Windows-managed HKCU logon metadata; it does not create a C: Startup-folder shortcut. NEXEN caches, profiles and output files use guarded H/F locations.

## Start

```powershell
F:\NEXEN_AUTONOMY\START_NEXEN.ps1
```

Then open:

```text
http://127.0.0.1:8788
```

## First full scan

```powershell
F:\NEXEN_AUTONOMY\RUN_FIRST_SCAN.ps1
```

The first whole-drive scan can take a while. Later passes skip unchanged files.

## OpenAI inside NEXEN

Your ChatGPT subscription and API access are separate. NEXEN uses `OPENAI_API_KEY` if you provide one; otherwise it continues with Ollama/local processing.

```powershell
.\SET_OPENAI_KEY_CURRENT_USER.ps1 -ApiKey "YOUR_API_KEY"
```

Then restart NEXEN.

The configured OpenAI routing is:

- routine cloud fallback: `gpt-5.6-luna`
- hard cloud work: `gpt-5.6-sol`

## Tool Fabric

Edit `config\tools.yaml` to add more tools. NEXEN checks candidate executable names and records:

- installed / unresolved
- executable path
- version probe
- interfaces such as CLI, MCP, API, browser, SQL, etc.

The next layer should add verified adapters for OpenClaw, n8n, Amboras, Playwright, MCP servers, and PC2 workers.

## Safety model

`config\nexen.yaml` ships with safe-mode controls enabled. Raw source files remain untouched.

Real-money trading should remain a distinct subsystem behind a fixed risk engine and should not inherit ordinary automation permissions.
