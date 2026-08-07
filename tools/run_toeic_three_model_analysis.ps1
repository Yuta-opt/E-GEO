param(
    [ValidateSet("Validate", "Analyze")]
    [string]$Mode = "Validate"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "TOEIC E-GEO three-model analysis runner"
Write-Host "  Mode: $Mode"
Write-Host "  Repo: $repoRoot"
Write-Host "  API calls: 0"
Write-Host "  Poster update: none"

uv run python ".\tools\analyze_toeic_three_model.py" `
    --mode $Mode.ToLowerInvariant()

if ($LASTEXITCODE -ne 0) {
    throw "Three-model analysis failed: $Mode (exit code $LASTEXITCODE)"
}
