param(
    [ValidateSet("Validate", "Publish")]
    [string]$Mode = "Validate",
    [switch]$Commit,
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$argsList = @(
    "run",
    "python",
    ".\tools\publish_toeic_three_model_results.py",
    "--mode",
    $Mode.ToLowerInvariant()
)

if ($Commit) {
    $argsList += "--commit"
}
if ($Push) {
    $argsList += "--push"
}

& uv @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Three-model result publisher failed with exit code $LASTEXITCODE"
}
