param([Parameter(Mandatory=$true)][string]$ApiKey)
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $ApiKey, "User")
Write-Host "OPENAI_API_KEY saved for the current Windows user. Close/reopen NEXEN afterward."
