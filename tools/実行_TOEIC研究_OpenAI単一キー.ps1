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
$Python = "uv run python"

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

Write-Host "E-GEO 日本語TOEIC研究：OpenAI単一キー自動実行" -ForegroundColor Green
Write-Host "Mode: $Mode"
Write-Host "Hard stop: USD $HardStopUsd"
Write-Host "APIキーは.envから読み込み、画面には表示しません。"

Invoke-Step "1. Python環境を同期" {
    uv sync
}

Invoke-Step "2. 実行コードの構文チェック" {
    uv run python -m py_compile `
        ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        ".\日本語版コード\04c_TOEIC候補検索入力を検証.py" `
        ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py" `
        ".\日本語版コード\05b_TOEIC候補選定API直前チェック.py" `
        ".\日本語版コード\05c_TOEICメタ最適化API実験を自動実行.py" `
        ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py"
}

Invoke-Step "3. Dense Retrieval入力の再検証" {
    uv run python ".\日本語版コード\04c_TOEIC候補検索入力を検証.py"
}

Invoke-Step "4. 候補30件→10件の計画を固定モデルで再作成" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel
}

Invoke-Step "5. メタ最適化スケジュールを作成" {
    uv run python ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py"
}

if ($Mode -eq "Validate") {
    Invoke-Step "6. API直前チェック（API呼び出し0回）" {
        uv run python ".\日本語版コード\05b_TOEIC候補選定API直前チェック.py"
    }
    Invoke-Step "7. 研究本体ランナーのdry-run（API呼び出し0回）" {
        uv run python ".\日本語版コード\05c_TOEICメタ最適化API実験を自動実行.py" `
            --mode smoke `
            --hard-stop-usd $HardStopUsd
    }
    Write-Host ""
    Write-Host "Validate完了：APIは呼び出していません。" -ForegroundColor Green
    Write-Host "次は .env にOPENAI_API_KEYを設定し、-Mode Smoke または -Mode Fullを実行します。"
    exit 0
}

Invoke-Step "6. APIキーを含む候補選定直前チェック" {
    uv run python ".\日本語版コード\05b_TOEIC候補選定API直前チェック.py" `
        --require-key
}

Invoke-Step "7. 候補10件を全80購入意図で選定し、対象商品を固定" {
    uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" `
        --model $CandidateModel `
        --execute
}

if ($Mode -eq "Smoke") {
    Invoke-Step "8. 研究本体のsmoke実験" {
        uv run python ".\日本語版コード\05c_TOEICメタ最適化API実験を自動実行.py" `
            --mode smoke `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
    Invoke-Step "9. smoke結果を自動分析" {
        uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py"
    }
    Write-Host ""
    Write-Host "Smoke完了：候補80件と小規模な全工程を確認しました。" -ForegroundColor Green
    Write-Host "正式実験は -Mode Full で開始します。"
    exit 0
}

if (-not $SkipSmoke) {
    Invoke-Step "8. 正式実験前のsmoke実験" {
        uv run python ".\日本語版コード\05c_TOEICメタ最適化API実験を自動実行.py" `
            --mode smoke `
            --execute `
            --hard-stop-usd $HardStopUsd
    }
}

Invoke-Step "9. 15プロンプトの正式メタ最適化・Test評価" {
    uv run python ".\日本語版コード\05c_TOEICメタ最適化API実験を自動実行.py" `
        --mode full `
        --execute `
        --hard-stop-usd $HardStopUsd
}

Invoke-Step "10. 正式結果の統計・収束・図表を自動生成" {
    uv run python ".\日本語版コード\06_TOEICメタ最適化実験結果を分析.py"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "OpenAI単一キー構成の研究実行と分析が完了しました。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "APIログ：日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行"
Write-Host "分析結果：日本語版データ/TOEIC/06_分析結果"
Write-Host "同じコマンドを再実行しても、成功済みAPIジョブはキャッシュから再利用します。"
