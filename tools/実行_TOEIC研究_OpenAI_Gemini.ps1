[CmdletBinding()]
param(
    [ValidateSet("Validate", "Smoke", "Full")]
    [string]$Mode = "Validate",

    [double]$HardStopUsd = 113,

    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$CandidateModel = "gpt-5-mini-2025-08-07"
$CandidateRunner = ".\日本語版コード\04d_TOEIC候補10商品を安全に選ぶ.py"
$Runner = ".\日本語版コード\05i_TOEIC最終安全実行.py"
$ConnectivitySmoke = ".\日本語版コード\05j_TOEIC_API接続Smoke.py"
$PlanRunner = ".\日本語版コード\05b_TOEIC最終実行計画.py"
$BudgetProjection = ".\日本語版コード\05k_TOEIC_Smoke実測からFull予算を判定.py"
$SelfCheck = ".\日本語版コード\07e_TOEIC最終安全実装を自己検査.py"
$AnalysisRunner = ".\日本語版コード\06c_TOEIC最終統計分析.py"
$CompletionChecker = ".\日本語版コード\07d_TOEIC最終完了チェック.py"
$ExperimentConfig = ".\日本語版設定\TOEIC_EGEO実験設定_v3_先行研究準拠.json"
$ModelProfile = ".\日本語版設定\TOEIC_OpenAI_Gemini実験設定_v1.json"
$CandidateSmokeDir = ".\日本語版データ\TOEIC\05_API実験\00_候補選定接続Smoke"
$ConnectivityDir = ".\日本語版データ\TOEIC\05_API実験\00_API接続Smoke"
$RunDir = ".\日本語版データ\TOEIC\05_API実験\02_OpenAI_Gemini_Claude実行"
$AnalysisDir = ".\日本語版データ\TOEIC\06_分析結果\02_OpenAI_Gemini_Claude"
$SmokeCompletionReport = ".\日本語版データ\TOEIC\07_本番前チェック\03_OpenAI_Gemini_smokeチェック.json"
$CompletionReport = ".\日本語版データ\TOEIC\07_本番前チェック\05_OpenAI_Gemini費用配分完了チェック.json"
$ExpectedHeldoutCount = 2

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

Write-Host "E-GEO 日本語TOEIC研究：OpenAI主予算＋低予算Gemini" -ForegroundColor Green
Write-Host "Mode: $Mode"
Write-Host "総hard stop: USD $HardStopUsd"
Write-Host "OpenAIアカウント予算: 100 USD（本体98＋予備2）"
Write-Host "Provider上限: OpenAI本体 98 USD / Google 15 USD"
Write-Host "候補選定上限: 出力フォルダごとに1 USD"
Write-Host "学習Re-ranker: GPT-4.1 / Gemini 3.1 Flash-Lite"
Write-Host "Held-out Test: GPT-5（全条件）/ Gemini 3.5 Flash-Lite（長文のみ）"
Write-Host "最適化長文と最適化短文は同一リライトを共有します。"
Write-Host "OpenAI cached inputは実測cached_tokensを割引単価で計上します。"
Write-Host "Full前にSmoke実測費用からProvider別予算を自動判定します。"
Write-Host "必要キー: OPENAI_API_KEY / GEMINI_API_KEY"
Write-Host "ANTHROPIC_API_KEYは今回不要です。"
Write-Host "Validationは版選択専用で、Meta-optimizerへ渡しません。"

Invoke-Step "1. Python環境を同期" {
    uv sync
}

Invoke-Step "2. 実行コードの構文チェック" {
    uv run python -m py_compile `
        ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        $CandidateRunner `
        ".\日本語版コード\04c_TOEIC候補検索入力を検証.py" `
        ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py" `
        $PlanRunner `
        ".\日本語版コード\05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py" `
        ".\日本語版コード\05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py" `
        ".\日本語版コード\05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py" `
        ".\日本語版コード\05h_TOEIC費用配分安全実行.py" `
        $Runner `
        $ConnectivitySmoke `
        $BudgetProjection `
        ".\日本語版コード\06b_TOEIC先行研究準拠結果分析.py" `
        $AnalysisRunner `
        ".\日本語版コード\07c_TOEIC費用配分完了チェック.py" `
        $CompletionChecker `
        $SelfCheck
}

Invoke-Step "3. 最終安全実装をAPIなしで自己検査" {
    uv run python $SelfCheck
}

Invoke-Step "4. Dense Retrieval入力の再検証" {
    uv run python ".\日本語版コード\04c_TOEIC候補検索入力を検証.py"
}

Invoke-Step "5. 候補30件→10件の計画を安全設定で再作成" {
    uv run python $CandidateRunner `
        --model $CandidateModel
}

Invoke-Step "6. 先行研究準拠メタ最適化スケジュールを再確認" {
    uv run python $PlanRunner `
        --config $ExperimentConfig `
        --overwrite
}

if ($Mode -eq "Validate") {
    Invoke-Step "7. API接続Smokeの設定検査（API呼び出し0回）" {
        uv run python $ConnectivitySmoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --output-dir $ConnectivityDir
    }
    Invoke-Step "8. 最終ランナー設定を検査（API呼び出し0回）" {
        uv run python $Runner `
            --mode smoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --hard-stop-usd $HardStopUsd
    }
    Write-Host ""
    Write-Host "Validate完了：APIは呼び出していません。" -ForegroundColor Green
    Write-Host ".envへOPENAI_API_KEYとGEMINI_API_KEYを設定後、-Mode Smokeへ進みます。"
    exit 0
}

Invoke-Step "7. OpenAI・Gemini APIキー存在確認（API呼び出し0回）" {
    uv run python $ConnectivitySmoke `
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --output-dir $ConnectivityDir `
        --require-keys
}

Invoke-Step "8. GPT-5 mini候補選定を1購入意図だけ接続Smoke" {
    uv run python $CandidateRunner `
        --model $CandidateModel `
        --limit 1 `
        --output-dir $CandidateSmokeDir `
        --execute
}

Invoke-Step "9. Rewriter・Meta・全Re-rankerの少額API接続Smoke" {
    uv run python $ConnectivitySmoke `
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --output-dir $ConnectivityDir `
        --require-keys `
        --execute `
        --hard-stop-usd 3
}

Invoke-Step "10. GPT-5 miniで候補10件を全80購入意図について選定" {
    uv run python $CandidateRunner `
        --model $CandidateModel `
        --execute
}

if ($Mode -eq "Smoke") {
    Invoke-Step "11. OpenAI＋Geminiの正式工程Smoke" {
        uv run python $Runner `
            --mode smoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
    Invoke-Step "12. Smoke結果を構造確認用に分析" {
        uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py" `
            --run-dir $RunDir `
            --output-dir $AnalysisDir
    }
    Invoke-Step "13. Smoke完了チェック" {
        uv run python ".\日本語版コード\07_TOEIC研究完了チェック.py" `
            --run-dir $RunDir `
            --analysis-dir $AnalysisDir `
            --report $SmokeCompletionReport `
            --expected-heldout-count $ExpectedHeldoutCount `
            --allow-smoke `
            --hard-stop-usd $HardStopUsd
    }
    Invoke-Step "14. Smoke実測費用からFull予算を保守的に判定" {
        uv run python $BudgetProjection `
            --run-dir $RunDir `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --budget-fraction 0.90
    }
    Write-Host ""
    Write-Host "OpenAI＋Gemini SmokeとFull予算判定が完了しました。" -ForegroundColor Green
    Write-Host "正式実験は -Mode Full -SkipSmoke です。"
    exit 0
}

if (-not $SkipSmoke) {
    Invoke-Step "11. 正式実験前のOpenAI＋Gemini工程Smoke" {
        uv run python $Runner `
            --mode smoke `
            --experiment-config $ExperimentConfig `
            --model-profile $ModelProfile `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
}

Invoke-Step "12. Smoke実測費用からFull予算を再判定" {
    uv run python $BudgetProjection `
        --run-dir $RunDir `
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --budget-fraction 0.90
}

Invoke-Step "13. 15プロンプトの正式メタ最適化・費用配分Test評価" {
    uv run python $Runner `
        --mode full `
        --experiment-config $ExperimentConfig `
        --model-profile $ModelProfile `
        --execute `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "14. Test統計・95%CI・Holm補正・埋め込み収束・人手評価表を生成" {
    uv run python $AnalysisRunner `
        --run-dir $RunDir `
        --output-dir $AnalysisDir `
        --execute-embeddings
}

Invoke-Step "15. GPT＋Gemini段階の最終安全完了チェック" {
    uv run python $CompletionChecker `
        --run-dir $RunDir `
        --analysis-dir $AnalysisDir `
        --report $CompletionReport `
        --connectivity-dir $ConnectivityDir `
        --expected-heldout-count $ExpectedHeldoutCount
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "OpenAI＋Gemini段階の実行・統計・埋め込み分析が終了しました。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "API接続Smoke：$ConnectivityDir"
Write-Host "Full予算判定：$RunDir\00b_full_budget_projection.json"
Write-Host "APIログ：$RunDir"
Write-Host "Provider別費用：$RunDir\05b_provider_cost_summary.json"
Write-Host "分析結果：$AnalysisDir"
Write-Host "段階完了判定：$CompletionReport"
Write-Host "人手特徴評価表：$AnalysisDir\04_prompt_feature_manual_review.xlsx"
Write-Host "Claude追加時は3社版PowerShellを同じフォルダで実行し、成功済みGPT/Geminiジョブと共有リライトを再利用します。"
