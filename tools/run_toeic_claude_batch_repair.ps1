param(
    [ValidateSet("Validate", "Submit", "Status", "Collect")]
    [string]$Mode = "Validate"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Claude Batch repair runner"
Write-Host "  Mode: $Mode"
Write-Host "  Repo: $repoRoot"

uv run python ".\tools\toeic_claude_batch_repair.py" `
    --mode $Mode.ToLowerInvariant()

if ($LASTEXITCODE -ne 0) {
    throw "Claude Batch repair failed: $Mode (exit code $LASTEXITCODE)"
}
