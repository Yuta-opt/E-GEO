param(
    [ValidateSet("Validate", "Publish")]
    [string]$Mode = "Validate",
    [switch]$Commit,
    [switch]$Push
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$analysisDir = Join-Path $repoRoot "日本語版データ\TOEIC\06_分析結果\03_3モデル統合"
$legacyDir = Join-Path $repoRoot "日本語版ドキュメント\実験ログ\2026-08-07_OpenAI_Gemini_Full結果"
$publishDir = Join-Path $repoRoot "日本語版ドキュメント\実験ログ\2026-08-08_3モデル統合_最終結果"
$posterDir = Join-Path $publishDir "ポスター用図表"

Write-Host "TOEIC E-GEO three-model result publisher"
Write-Host "  Mode: $Mode"
Write-Host "  Repo: $repoRoot"
Write-Host "  API calls: 0"
Write-Host "  Source: $analysisDir"
Write-Host "  Destination: $publishDir"

# Always validate the raw GPT/Gemini + Claude inputs first.
& powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\run_toeic_three_model_analysis.ps1" -Mode Validate
if ($LASTEXITCODE -ne 0) {
    throw "Three-model input validation failed. Nothing was published."
}

if ($Mode -eq "Validate") {
    Write-Host "Validation complete. No files copied."
    exit 0
}

# Rebuild all final tables/statistics/figures from the validated raw results.
& powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\run_toeic_three_model_analysis.ps1" -Mode Analyze
if ($LASTEXITCODE -ne 0) {
    throw "Three-model analysis failed. Nothing was published."
}

$required = @(
    "00_validation_report.json",
    "01_three_model_integrated_table.csv",
    "02_model_level_statistical_tests.csv",
    "03_prompt_level_statistical_tests.csv",
    "04_prompt_by_model_recovery.csv",
    "05_three_model_paired_rows.csv",
    "06_three_model_results_summary.json",
    "07_three_model_initial_vs_optimized.png",
    "08_three_model_recovery.png",
    "09_prompt_recovery_heatmap.png",
    "10_three_model_results.xlsx",
    "11_three_model_report.md"
)

foreach ($name in $required) {
    $path = Join-Path $analysisDir $name
    if (-not (Test-Path $path)) {
        throw "Required three-model artifact is missing: $path"
    }
}

$validation = Get-Content (Join-Path $analysisDir "00_validation_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$summary = Get-Content (Join-Path $analysisDir "06_three_model_results_summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json

if ($validation.status -ne "pass") {
    throw "Validation report status is not pass."
}
if ([int]$validation.integrated_long_rows -ne 2700) {
    throw "Expected 2700 integrated long rows, got $($validation.integrated_long_rows)."
}
if ([int]$summary.model_count -ne 3) {
    throw "Expected 3 models, got $($summary.model_count)."
}
if ([int]$summary.prompt_count -ne 15) {
    throw "Expected 15 prompts, got $($summary.prompt_count)."
}
if ([int]$summary.intent_count -ne 30) {
    throw "Expected 30 Test intents, got $($summary.intent_count)."
}
if ([int]$summary.paired_rows -ne 1350) {
    throw "Expected 1350 paired rows, got $($summary.paired_rows)."
}

New-Item -ItemType Directory -Force -Path $publishDir | Out-Null
New-Item -ItemType Directory -Force -Path $posterDir | Out-Null

# Canonical three-model artifacts.
foreach ($name in $required) {
    Copy-Item -Force (Join-Path $analysisDir $name) (Join-Path $publishDir $name)
}

# Supplemental artifacts that remain valid after adding Claude.
$supplemental = @{
    "03_final_prompts.json" = "12_final_prompts.json"
    "03_prompt_convergence_trajectory.csv" = "13_prompt_convergence_trajectory.csv"
    "03b_prompt_trajectory.csv" = "14_prompt_trajectory.csv"
}
foreach ($sourceName in $supplemental.Keys) {
    $sourcePath = Join-Path $legacyDir $sourceName
    if (Test-Path $sourcePath) {
        Copy-Item -Force $sourcePath (Join-Path $publishDir $supplemental[$sourceName])
    } else {
        Write-Warning "Supplemental artifact not found: $sourcePath"
    }
}

# Poster-ready figures. The first three supersede the old two-model comparison figures.
$posterCopies = @(
    @{ Source = (Join-Path $analysisDir "07_three_model_initial_vs_optimized.png"); Name = "01_3モデル_初期vs最適化.png" },
    @{ Source = (Join-Path $analysisDir "08_three_model_recovery.png"); Name = "02_3モデル_回復量.png" },
    @{ Source = (Join-Path $analysisDir "09_prompt_recovery_heatmap.png"); Name = "03_3モデル_プロンプト別回復ヒートマップ.png" },
    @{ Source = (Join-Path $legacyDir "08_long_vs_short.png"); Name = "04_GPT5_長文vs短文.png" },
    @{ Source = (Join-Path $legacyDir "09_prompt_convergence.png"); Name = "05_プロンプト収束.png" }
)

foreach ($item in $posterCopies) {
    if (Test-Path $item.Source) {
        Copy-Item -Force $item.Source (Join-Path $posterDir $item.Name)
    } else {
        Write-Warning "Poster figure not found: $($item.Source)"
    }
}

# Write a reproducibility manifest with hashes of the published artifacts.
$manifestFiles = Get-ChildItem -Path $publishDir -File -Recurse | Where-Object { $_.Name -ne "PUBLISH_MANIFEST.json" }
$manifestEntries = foreach ($file in $manifestFiles) {
    $relative = $file.FullName.Substring($publishDir.Length + 1).Replace("\", "/")
    $hash = (Get-FileHash -Algorithm SHA256 -Path $file.FullName).Hash.ToLowerInvariant()
    [ordered]@{
        path = $relative
        bytes = $file.Length
        sha256 = $hash
    }
}
$manifest = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    source_analysis_dir = "日本語版データ/TOEIC/06_分析結果/03_3モデル統合"
    canonical_result_dir = "日本語版ドキュメント/実験ログ/2026-08-08_3モデル統合_最終結果"
    validation_status = $validation.status
    integrated_long_rows = [int]$validation.integrated_long_rows
    model_count = [int]$summary.model_count
    prompt_count = [int]$summary.prompt_count
    intent_count = [int]$summary.intent_count
    paired_rows = [int]$summary.paired_rows
    primary_inference_unit = $summary.primary_inference_unit
    files = @($manifestEntries)
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $publishDir "PUBLISH_MANIFEST.json")

Write-Host "Published canonical three-model artifacts."
Write-Host "  Model count: $($summary.model_count)"
Write-Host "  Integrated rows: $($validation.integrated_long_rows)"
Write-Host "  Paired rows: $($summary.paired_rows)"
Write-Host "  Overall initial mean: $($summary.overall_initial_mean)"
Write-Host "  Overall optimized mean: $($summary.overall_optimized_mean)"
Write-Host "  Overall recovery mean: $($summary.overall_recovery_mean)"
Write-Host "  Poster figures: $posterDir"

if ($Commit -or $Push) {
    $branch = (git branch --show-current).Trim()
    if ($branch -ne "ja-toeic-prototype") {
        throw "Refusing to commit from branch '$branch'. Switch to ja-toeic-prototype first."
    }

    git add -- "日本語版ドキュメント/実験ログ/2026-08-08_3モデル統合_最終結果"
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "No new published-result changes to commit."
    } else {
        git commit -m "Publish final three-model TOEIC E-GEO results"
        if ($LASTEXITCODE -ne 0) {
            throw "git commit failed."
        }
    }
}

if ($Push) {
    git push origin ja-toeic-prototype
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed."
    }
}

Write-Host "Done."
