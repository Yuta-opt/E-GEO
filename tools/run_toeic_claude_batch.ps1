param(
    [ValidateSet("Validate", "Submit", "Status", "Collect")]
    [string]$Mode = "Validate"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$pythonMode = $Mode.ToLowerInvariant()

Write-Host "Claude Sonnet 4.5 Batch runner"
Write-Host "  Mode: $Mode"
Write-Host "  Repo: $repoRoot"

uv run python ".\tools\toeic_claude_batch.py" `
    --mode $pythonMode

if ($LASTEXITCODE -ne 0) {
    throw "Claude Batch step failed: $Mode (exit code $LASTEXITCODE)"
}
