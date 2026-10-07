# Registers the NEXEN MCP server with the agents on this PC.
# NOT run automatically: it edits each tool's persistent configuration. Run it once, or run one line at a time.
$py  = 'H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe'
$app = 'H:\NEXEN-ENTERPRISE\Apps\NEXEN\run.py'

# Claude Code (user scope, every project)
claude mcp add --scope user nexen -- $py -X utf8 $app mcp

# Codex: add this block to $env:USERPROFILE\.codex\config.toml
@"

[mcp_servers.nexen]
command = "$($py -replace '\\','\\')"
args = ["-X", "utf8", "$($app -replace '\\','\\')", "mcp"]
"@ | Add-Content "$env:USERPROFILE\.codex\config.toml"

# Antigravity: add this to its MCP config (see $env:USERPROFILE\.gemini\antigravity\mcp):
#   "nexen": { "command": "H:\\NEXEN_RUNTIME\\python-recovery\\Scripts\\python.exe", "args": ["-X","utf8","H:\\NEXEN-ENTERPRISE\\Apps\\NEXEN\\run.py","mcp"] }
