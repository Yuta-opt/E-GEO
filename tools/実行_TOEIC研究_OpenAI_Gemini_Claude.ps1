[CmdletBinding()]
param(
    [ValidateSet("Validate", "Smoke", "Full")]
    [string]$Mode = "Validate",

    [double]$HardStopUsd = 100,

    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$CandidateModel = "gpt-5-mini-2025-08-07"
$Runner = ".\日本語版コード\05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py"
$RunDir = ".\日本語版データ\TOEIC\05_API実験\02_OpenAI_Gemini_Claude実行"
$AnalysisDir = ".\日本語版データ\TOEIC\06_分析結果\02_OpenAI_Gemini_Claude"
$CompletionReport = ".\日本語版データ\TOEIC\07_本番前チェック\03_OpenAI_Gemini_Claude研究完了チェック.json"

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    & $Command
}

Write-Host "E-GEO 日本語TOEIC研究：OpenAI + Gemini + Claude" -ForegroundColor Green
Write-Host "Mode: $Mode"
Write-Host "Hard stop: USD $HardStopUsd"
Write-Host "必要キー: OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY"
Write-Host "APIキーの値は画面に表示しません。"

Invoke-Step "1. Python環境を同期" {
    uv sync
}

Invoke-Step "2. 実行コードの構文チェック" {
    uv run python -m py_compile `
        ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        ".\日本語版コード\04c_TOEIC候補検索入力を検証.py" `
        ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py" `
        ".\日本語版コード\05b_TOEIC候補選定API直前チェック.py" `
        ".\日本語版コード\05c_TOEIC_OpenAI単一キー実験を自動実行.py" `
        $Runner `
        ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py" `
        ".\日本語版コード\07_TOEIC研究完了チェック.py"
}

Invoke-Step "3. Dense Retrieval入力の再検証" {
    uv run python ".\日本語版コード\04c_TOEIC候補検索入力を検証.py"
}

Invoke-Step "4. 候補30件→10件の計画を固定モデルで再作成" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel
}

Invoke-Step "5. メタ最適化スケジュールを再確認" {
    uv run python ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py"
}

if ($Mode -eq "Validate") {
    Invoke-Step "6. 3社モデル設定の検査（API呼び出し0回）" {
        uv run python $Runner `
            --mode smoke `
            --hard-stop-usd $HardStopUsd
    }
    Write-Host ""
    Write-Host "Validate完了：APIは呼び出していません。" -ForegroundColor Green
    Write-Host ".envへ3種類のAPIキーを設定後、-Mode Smokeへ進みます。"
    exit 0
}

Invoke-Step "6. 3種類のAPIキー存在確認（API呼び出し0回）" {
    uv run python $Runner `
        --mode smoke `
        --require-keys `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "7. OpenAIで候補10件を全80購入意図について選定" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel `
        --execute
}

if ($Mode -eq "Smoke") {
    Invoke-Step "8. OpenAI・Gemini・Claudeをすべて使うsmoke実験" {
        uv run python $Runner `
            --mode smoke `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
    Invoke-Step "9. smoke結果を専用フォルダへ分析" {
        uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py" `
            --run-dir $RunDir `
            --output-dir $AnalysisDir
    }
    Invoke-Step "10. smoke完了チェック" {
        uv run python ".\日本語版コード\07_TOEIC研究完了チェック.py" `
            --run-dir $RunDir `
            --analysis-dir $AnalysisDir `
            --report $CompletionReport `
            --allow-smoke `
            --hard-stop-usd $HardStopUsd
    }
    Write-Host ""
    Write-Host "3社smoke完了。正式実験は -Mode Full です。" -ForegroundColor Green
    exit 0
}

if (-not $SkipSmoke) {
    Invoke-Step "8. 正式実験前の3社smoke実験" {
        uv run python $Runner `
            --mode smoke `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
}

Invoke-Step "9. 15プロンプトの3社正式メタ最適化・Test評価" {
    uv run python $Runner `
        --mode full `
        --execute `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "10. 3社正式結果の統計・収束・図表を専用フォルダへ生成" {
    uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py" `
        --run-dir $RunDir `
        --output-dir $AnalysisDir
}

Invoke-Step "11. 3社構成の研究完了チェック" {
    uv run python ".\日本語版コード\07_TOEIC研究完了チェック.py" `
        --run-dir $RunDir `
        --analysis-dir $AnalysisDir `
        --report $CompletionReport `
        --hard-stop-usd $HardStopUsd
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "OpenAI・Gemini・Claude構成の実行・分析・完了検査が終了しました。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "APIログ：$RunDir"
Write-Host "分析結果：$AnalysisDir"
Write-Host "完了判定：$CompletionReport"
Write-Host "再実行時は成功済みAPIジョブをキャッシュから再利用します。"
