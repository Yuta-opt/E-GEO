param(
    [ValidateSet("Validate", "Smoke", "Full", "Analyze")]
    [string]$Mode = "Validate",

    [double]$HardStopUsd = 18.0
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonMode = $Mode.ToLowerInvariant()

Write-Host "Claude held-out runner"
Write-Host "  Mode: $Mode"
Write-Host "  Hard stop: USD $HardStopUsd"
Write-Host "  Repo: $repoRoot"

uv run python ".\tools\toeic_claude_heldout.py" `
    --mode $pythonMode `
    --hard-stop-usd $HardStopUsd

if ($LASTEXITCODE -ne 0) {
    throw "Claude held-out step failed: $Mode (exit code $LASTEXITCODE)"
}
