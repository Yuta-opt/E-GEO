[CmdletBinding()]
param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Remove-LegacyPath {
    param([string]$RelativePath)

    $native = Join-Path $RepoRoot ($RelativePath -replace "/", [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $native)) {
        Write-Host "[なし] $RelativePath"
        return
    }

    if ($Preview) {
        Write-Host "[Preview: 削除予定] $RelativePath" -ForegroundColor Yellow
        return
    }

    Remove-Item -LiteralPath $native -Recurse -Force
    Write-Host "[削除] $RelativePath" -ForegroundColor Green
}

Write-Host "旧TOEIC設計のローカル生成物を整理します。" -ForegroundColor Cyan
Write-Host "現行の01〜05a、新Dense Retrieval結果、購入意図、商品プールは削除しません。"

$legacyDirectories = @(
    "日本語版データ/TOEIC/04_API実験",
    "日本語版データ/TOEIC/05_分析結果",
    "日本語版データ/TOEIC/06_分析結果",
    "日本語版データ/TOEIC/07_本番前チェック",
    "日本語版データ/TOEIC/99_旧版"
)

$legacyFiles = @(
    "日本語版データ/TOEIC/04_候補商品/toeic_candidate_assignments.csv",
    "日本語版データ/TOEIC/04_候補商品/toeic_candidate_intent_summary.csv",
    "日本語版データ/TOEIC/04_候補商品/toeic_experiment_instances.json",
    "日本語版データ/TOEIC/04_候補商品/toeic_candidate_assignment_summary.json",
    "日本語版データ/TOEIC/04_候補商品/toeic_candidate_assignments_review.xlsx",
    "日本語版データ/TOEIC/05_API実験/rewrite_results.jsonl",
    "日本語版データ/TOEIC/05_API実験/ranking_results.jsonl",
    "日本語版データ/TOEIC/05_API実験/experiment_plan.json"
)

foreach ($path in $legacyDirectories) {
    Remove-LegacyPath $path
}
foreach ($path in $legacyFiles) {
    Remove-LegacyPath $path
}

Write-Host ""
if ($Preview) {
    Write-Host "Previewのみです。実際には削除していません。" -ForegroundColor Yellow
}
else {
    Write-Host "旧設計のローカル生成物を削除しました。" -ForegroundColor Green
    Write-Host "残す主な現行フォルダ："
    Write-Host "  日本語版データ/TOEIC/00_元データ"
    Write-Host "  日本語版データ/TOEIC/01_クレンジング済み"
    Write-Host "  日本語版データ/TOEIC/02_商品プール"
    Write-Host "  日本語版データ/TOEIC/03_購入意図"
    Write-Host "  日本語版データ/TOEIC/04_候補商品"
    Write-Host "  日本語版データ/TOEIC/05_API実験"
}
