[CmdletBinding()]
param(
    [ValidateSet("Validate", "Smoke", "Full")]
    [string]$Mode = "Validate",

    [double]$HardStopUsd = 133,

    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$target = Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter "*OpenAI_Gemini.ps1" |
    Where-Object { $_.Name -ne "run_toeic_openai_gemini_compat.ps1" } |
    Select-Object -First 1

if (-not $target) {
    throw "Target OpenAI_Gemini PowerShell script was not found."
}

$tempPath = Join-Path $PSScriptRoot ".run_toeic_openai_gemini_utf8bom.ps1"
$utf8Read = New-Object System.Text.UTF8Encoding($false)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$text = [System.IO.File]::ReadAllText($target.FullName, $utf8Read)
[System.IO.File]::WriteAllText($tempPath, $text, $utf8Bom)

$invokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $tempPath,
    "-Mode", $Mode,
    "-HardStopUsd", $HardStopUsd
)
if ($SkipSmoke) {
    $invokeArgs += "-SkipSmoke"
}

try {
    & powershell @invokeArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}

exit $exitCode
