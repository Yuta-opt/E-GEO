[CmdletBinding()]
param(
    [ValidateSet("Validate", "Smoke", "Full")]
    [string]$Mode = "Validate",

    [double]$HardStopUsd = 121,

    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$CandidateModel = "gpt-5-mini-2025-08-07"
$Runner = ".\日本語版コード\05h_TOEIC費用配分安全実行.py"
$ExperimentConfig = ".\日本語版設定\TOEIC_EGEO実験設定_v3_先行研究準拠.json"
$ModelProfile = ".\日本語版設定\TOEIC_OpenAI_Gemini_Claude実験設定_v1.json"
$RunDir = ".\日本語版データ\TOEIC\05_API実験\02_OpenAI_Gemini_Claude実行"
$AnalysisDir = ".\日本語版データ\TOEIC\06_分析結果\02_OpenAI_Gemini_Claude"
$SmokeCompletionReport = ".\日本語版データ\TOEIC\07_本番前チェック\03_OpenAI_Gemini_Claude_smokeチェック.json"
$CompletionReport = ".\日本語版データ\TOEIC\07_本番前チェック\05_3社費用配分完了チェック.json"
$ExpectedHeldoutCount = 3

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Command
    )
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "ステップ失敗: $Title（終了コード $LASTEXITCODE）"
    }
}

Write-Host "E-GEO 日本語TOEIC研究：OpenAI主予算＋低予算Gemini/Claude" -ForegroundColor Green
Write-Host "Mode: $Mode"
Write-Host "総hard stop: USD $HardStopUsd"
Write-Host "OpenAIアカウント予算: 100 USD（本体98＋予備2）"
Write-Host "Provider上限: OpenAI本体 98 / Google 15 / Anthropic 8 USD"
Write-Host "学習Re-ranker: GPT-4.1 / Gemini 3.1 Flash-Lite"
Write-Host "GPT-5 Test: 初期長文・最適化長文・最適化短文"
Write-Host "Gemini Test: 初期長文・最適化長文"
Write-Host "Claude Sonnet 5 Test: 最適化長文のみ"
Write-Host "必要キー: OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY"
Write-Host "APIキーの値は画面に表示しません。"
Write-Host "Validationは版選択専用で、Meta-optimizerへ渡しません。"

Invoke-Step "1. Python環境を同期" {
    uv sync
}

Invoke-Step "2. 実行コードの構文チェック" {
    uv run python -m py_compile `
        ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        ".\日本語版コード\04c_TOEIC候補検索入力を検証.py" `
        ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py" `
        ".\日本語版コード\05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py" `
        ".\日本語版コード\05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py" `
        ".\日本語版コード\05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py" `
        $Runner `
        ".\日本語版コード\06b_TOEIC先行研究準拠結果分析.py" `
        ".\日本語版コード\07c_TOEIC費用配分完了チェック.py"
}

Invoke-Step "3. Dense Retrieval入力の再検証" {
    uv run python ".\日本語版コード\04c_TOEIC候補検索入力を検証.py"
}

Invoke-Step "4. 候補30件→10件の計画を固定モデルで再作成" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel
}

Invoke-Step "5. 先行研究準拠メタ最適化スケジュールを再確認" {
    uv run python ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py" `
        --config $ExperimentConfig `
        --overwrite
}

if ($Mode -eq "Validate") {
    Invoke-Step "6. 3社費用配分設定を検査（API呼び出し0回）" {
        uv run python $Runner `
            --mode smoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
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
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --require-keys `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "7. OpenAIで候補10件を全80購入意図について選定" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel `
        --execute
}

if ($Mode -eq "Smoke") {
    Invoke-Step "8. 費用配分版の3社smoke実験" {
        uv run python $Runner `
            --mode smoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
    Invoke-Step "9. smoke結果を構造確認用に分析" {
        uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py" `
            --run-dir $RunDir `
            --output-dir $AnalysisDir
    }
    Invoke-Step "10. smoke完了チェック" {
        uv run python ".\日本語版コード\07_TOEIC研究完了チェック.py" `
            --run-dir $RunDir `
            --analysis-dir $AnalysisDir `
            --report $SmokeCompletionReport `
            --expected-heldout-count $ExpectedHeldoutCount `
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
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
}

Invoke-Step "9. 15プロンプトの正式メタ最適化・費用配分Test評価" {
    uv run python $Runner `
        --mode full `
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --execute `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "10. Test統計・text-embedding-3-large収束・人手評価表を生成" {
    uv run python ".\日本語版コード\06b_TOEIC先行研究準拠結果分析.py" `
        --run-dir $RunDir `
        --output-dir $AnalysisDir `
        --execute-embeddings
}

Invoke-Step "11. 3社費用配分版の研究完了チェック" {
    uv run python ".\日本語版コード\07c_TOEIC費用配分完了チェック.py" `
        --run-dir $RunDir `
        --analysis-dir $AnalysisDir `
        --report $CompletionReport `
        --expected-heldout-count $ExpectedHeldoutCount
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "3社費用配分版の実行・統計・埋め込み分析が終了しました。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "APIログ：$RunDir"
Write-Host "Provider別費用：$RunDir\05b_provider_cost_summary.json"
Write-Host "分析結果：$AnalysisDir"
Write-Host "完了判定：$CompletionReport"
Write-Host "人手特徴評価表：$AnalysisDir\04_prompt_feature_manual_review.xlsx"
Write-Host "再実行時は成功済みAPIジョブと埋め込みをキャッシュから再利用します。"
