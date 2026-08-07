param(
    [ValidateSet("Validate", "Execute")]
    [string]$Mode = "Validate"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Claude final missing-item runner"
Write-Host "  Mode: $Mode"
Write-Host "  Repo: $repoRoot"

uv run python ".\tools\toeic_claude_finalize_missing.py" `
    --mode $Mode.ToLowerInvariant()

if ($LASTEXITCODE -ne 0) {
    throw "Claude final missing-item step failed: $Mode (exit code $LASTEXITCODE)"
}
