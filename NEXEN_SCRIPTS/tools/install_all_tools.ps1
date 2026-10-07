# Install all recommended "computer‑use" tools for Windows 10/11
# This script uses winget (built‑in on recent Windows) and pip.
# Run it from an elevated PowerShell prompt (Run as Administrator).
# It will attempt each installation; failures are logged but the script continues.

function Log-Info { param([string]$msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Log-Error { param([string]$msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# 1. Core dev utilities
$packages = @(
    "Microsoft.PowerShell",        # PowerShell 7+
    "Docker.DockerDesktop",       # Docker Desktop
    "Git.Git",                    # Git CLI
    "Microsoft.VisualStudioCode", # VS Code editor
    "OpenJS.NodeJS",              # Node.js (includes npm)
    "Python.Python.3.12",         # Python 3.12 (latest)
    "Microsoft.WindowsTerminal"   # Windows Terminal
)

foreach ($pkg in $packages) {
    Log-Info "Installing $pkg..."
    winget install --id $pkg -e --silent
    if ($LASTEXITCODE -ne 0) { Log-Error "Failed to install $pkg" }
    else { Log-Info "$pkg installed successfully" }
}

# 2. Python packages (global – you can later use virtualenv if you prefer)
$pyPkgs = @(
    "playwright",
    "google-genai",
    "pandas",
    "openpyxl",
    "xlite",
    "ffmpeg-python",
    "obs-cli"
)

# Ensure pip is up‑to‑date
python -m pip install --upgrade pip

foreach ($p in $pyPkgs) {
    Log-Info "Installing Python package $p..."
    python -m pip install $p
    if ($LASTEXITCODE -ne 0) { Log-Error "Failed to install $p" }
    else { Log-Info "$p installed" }
}

# 3. Playwright browsers (chromium, firefox, webkit)
Log-Info "Installing Playwright browsers..."
python -m playwright install chromium
python -m playwright install firefox
python -m playwright install webkit

# 4. Verify installations (basic version checks)
Log-Info "Verification:"
Write-Host "PowerShell version: $(pwsh -Command \"$PSVersionTable.PSVersion\")"
Write-Host "Docker version: $(docker --version)"
Write-Host "Git version: $(git --version)"
Write-Host "Node version: $(node --version)"
Write-Host "Python version: $(python --version)"
Write-Host "Playwright version: $(python -c \"import playwright; print(playwright.__version__)\")"
Write-Host "xlite version: $(python -c \"import xlite, importlib.metadata; print(importlib.metadata.version('xlite'))\")"

Log-Info "All installations attempted. Review the output for any errors."
