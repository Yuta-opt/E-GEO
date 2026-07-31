[CmdletBinding()]
param(
    [switch]$Preview
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Write-Step {
    param([string]$Message)
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function To-NativePath {
    param([string]$RelativePath)
    return Join-Path $RepoRoot ($RelativePath -replace "/", [IO.Path]::DirectorySeparatorChar)
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        if ($Preview) {
            Write-Host "[Preview] mkdir: $Path"
        }
        else {
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
        }
    }
}

function Move-CodeFile {
    param(
        [string]$SourceRelative,
        [string]$DestinationRelative
    )

    $source = To-NativePath $SourceRelative
    $destination = To-NativePath $DestinationRelative

    if (-not (Test-Path -LiteralPath $source)) {
        if (Test-Path -LiteralPath $destination) {
            Write-Host "[OK] 既に整理済み: $DestinationRelative"
        }
        else {
            Write-Warning "見つからないためスキップ: $SourceRelative"
        }
        return
    }

    if (Test-Path -LiteralPath $destination) {
        Write-Warning "移動先が既に存在するため上書きしません: $DestinationRelative"
        return
    }

    Ensure-Directory (Split-Path $destination -Parent)

    if ($Preview) {
        Write-Host "[Preview] git mv: $SourceRelative -> $DestinationRelative"
        return
    }

    & git -C $RepoRoot ls-files --error-unmatch -- $SourceRelative *> $null
    $isTracked = ($LASTEXITCODE -eq 0)

    if ($isTracked) {
        & git -C $RepoRoot mv -- $SourceRelative $DestinationRelative
        if ($LASTEXITCODE -ne 0) {
            throw "git mv に失敗しました: $SourceRelative"
        }
    }
    else {
        Move-Item -LiteralPath $source -Destination $destination
    }
}

function Move-LocalItemSafely {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }

    if (Test-Path -LiteralPath $Destination) {
        Write-Warning "同名の移動先があるため、元ファイルを残します: $Destination"
        return
    }

    Ensure-Directory (Split-Path $Destination -Parent)

    if ($Preview) {
        Write-Host "[Preview] move: $Source -> $Destination"
    }
    else {
        Move-Item -LiteralPath $Source -Destination $Destination
    }
}

function Merge-DirectorySafely {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }

    Ensure-Directory $Destination

    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $target = Join-Path $Destination $item.Name

        if ($item.PSIsContainer) {
            Merge-DirectorySafely -Source $item.FullName -Destination $target
        }
        else {
            Move-LocalItemSafely -Source $item.FullName -Destination $target
        }
    }

    if (-not $Preview -and (Test-Path -LiteralPath $Source)) {
        $remaining = @(Get-ChildItem -LiteralPath $Source -Force)
        if ($remaining.Count -eq 0) {
            Remove-Item -LiteralPath $Source -Force
        }
    }
}

function Replace-LiteralText {
    param(
        [string]$Path,
        [string]$OldText,
        [string]$NewText
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $text = [IO.File]::ReadAllText($Path)
    if (-not $text.Contains($OldText)) {
        return
    }

    if ($Preview) {
        Write-Host "[Preview] replace in: $Path"
        return
    }

    $updated = $text.Replace($OldText, $NewText)
    [IO.File]::WriteAllText(
        $Path,
        $updated,
        [Text.UTF8Encoding]::new($false)
    )
}

function Prepend-ArchiveNotice {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $notice = "# 旧方式の保存用コードです。現在の実験では実行しません。`r`n`r`n"
    $text = [IO.File]::ReadAllText($Path)
    if ($text.StartsWith("# 旧方式の保存用コードです。")) {
        return
    }

    if ($Preview) {
        Write-Host "[Preview] archive notice: $Path"
        return
    }

    [IO.File]::WriteAllText(
        $Path,
        $notice + $text,
        [Text.UTF8Encoding]::new($false)
    )
}

function Write-Utf8File {
    param(
        [string]$Path,
        [string]$Content
    )

    Ensure-Directory (Split-Path $Path -Parent)
    if ($Preview) {
        Write-Host "[Preview] write: $Path"
        return
    }

    [IO.File]::WriteAllText(
        $Path,
        $Content,
        [Text.UTF8Encoding]::new($false)
    )
}

Write-Step "1. Pythonコードを実行順に整理"

$codeMoves = @(
    @(
        "日本語版コード/07_TOEIC商品データクレンジング.py",
        "日本語版コード/01_楽天TOEIC商品データをクレンジング.py"
    ),
    @(
        "日本語版コード/08_TOEIC商品プール再構成.py",
        "日本語版コード/02_実験用TOEIC商品プールを作成.py"
    ),
    @(
        "日本語版コード/10_TOEIC購入意図テンプレート作成.py",
        "日本語版コード/03_TOEIC購入意図テンプレートを作成.py"
    ),
    @(
        "日本語版コード/08_TOEIC商品プール作成.py",
        "日本語版コード/99_旧版/旧_商品プール200件を作成.py"
    ),
    @(
        "日本語版コード/09_TOEIC商品プール最終化.py",
        "日本語版コード/99_旧版/旧_商品プールを最終化.py"
    )
)

foreach ($move in $codeMoves) {
    Move-CodeFile -SourceRelative $move[0] -DestinationRelative $move[1]
}

$active01 = To-NativePath "日本語版コード/01_楽天TOEIC商品データをクレンジング.py"
$active02 = To-NativePath "日本語版コード/02_実験用TOEIC商品プールを作成.py"
$active03 = To-NativePath "日本語版コード/03_TOEIC購入意図テンプレートを作成.py"
$archive01 = To-NativePath "日本語版コード/99_旧版/旧_商品プール200件を作成.py"
$archive02 = To-NativePath "日本語版コード/99_旧版/旧_商品プールを最終化.py"

Prepend-ArchiveNotice $archive01
Prepend-ArchiveNotice $archive02

Write-Step "2. TOEICデータを工程別フォルダへ整理"

$dataRoot = To-NativePath "日本語版データ/TOEIC"
Ensure-Directory $dataRoot

$rawOld = Join-Path $dataRoot "元データ"
$rawNew = Join-Path $dataRoot "00_元データ"
Merge-DirectorySafely -Source $rawOld -Destination $rawNew

$cleanOld = Join-Path $dataRoot "加工済み"
$cleanNew = Join-Path $dataRoot "01_クレンジング済み"
Merge-DirectorySafely -Source $cleanOld -Destination $cleanNew

$poolDir = Join-Path $dataRoot "02_商品プール"
$intentDir = Join-Path $dataRoot "03_購入意図"
$apiDir = Join-Path $dataRoot "04_API実験"
$analysisDir = Join-Path $dataRoot "05_分析結果"
$archiveDir = Join-Path $dataRoot "99_旧版"
$oldExperimentArchive = Join-Path $archiveDir "旧実験データ"

foreach ($dir in @($poolDir, $intentDir, $apiDir, $analysisDir, $archiveDir)) {
    Ensure-Directory $dir
}

$oldExperimentDir = Join-Path $dataRoot "実験データ"
if (Test-Path -LiteralPath $oldExperimentDir) {
    foreach ($item in Get-ChildItem -LiteralPath $oldExperimentDir -Force) {
        if ($item.PSIsContainer) {
            Move-LocalItemSafely `
                -Source $item.FullName `
                -Destination (Join-Path $oldExperimentArchive $item.Name)
            continue
        }

        $name = $item.Name
        if ($name -match '^toeic_purchase_intents_') {
            $destination = Join-Path $intentDir $name
        }
        elseif (
            $name -in @(
                "toeic_product_pool_final.csv",
                "toeic_product_pool_removed.csv",
                "toeic_product_pool_final_summary.json",
                "toeic_product_pool_final_review.xlsx"
            ) -or
            $name -match '^toeic_product_pool_revised_'
        ) {
            $destination = Join-Path $poolDir $name
        }
        else {
            $destination = Join-Path $oldExperimentArchive $name
        }

        Move-LocalItemSafely -Source $item.FullName -Destination $destination
    }

    if (-not $Preview -and (Test-Path -LiteralPath $oldExperimentDir)) {
        $remaining = @(Get-ChildItem -LiteralPath $oldExperimentDir -Force)
        if ($remaining.Count -eq 0) {
            Remove-Item -LiteralPath $oldExperimentDir -Force
        }
    }
}

$oldResultsDir = To-NativePath "日本語版データ/実験結果"
Merge-DirectorySafely -Source $oldResultsDir -Destination $analysisDir

foreach ($keepDir in @($apiDir, $analysisDir, $archiveDir)) {
    $keepFile = Join-Path $keepDir ".gitkeep"
    if (-not (Test-Path -LiteralPath $keepFile)) {
        if ($Preview) {
            Write-Host "[Preview] create: $keepFile"
        }
        else {
            New-Item -ItemType File -Path $keepFile -Force | Out-Null
        }
    }
}

Write-Step "3. 現役コードの入出力パスを新構成へ変更"

$pathReplacements = @(
    @(
        "日本語版データ/TOEIC/元データ/rakuten_toeic_raw_20260727.xlsx",
        "日本語版データ/TOEIC/00_元データ/rakuten_toeic_raw_20260727.xlsx"
    ),
    @(
        "日本語版データ/TOEIC/加工済み",
        "日本語版データ/TOEIC/01_クレンジング済み"
    )
)

foreach ($replacement in $pathReplacements) {
    Replace-LiteralText -Path $active01 -OldText $replacement[0] -NewText $replacement[1]
    Replace-LiteralText -Path $active02 -OldText $replacement[0] -NewText $replacement[1]
}

Replace-LiteralText `
    -Path $active02 `
    -OldText "日本語版データ/TOEIC/実験データ" `
    -NewText "日本語版データ/TOEIC/02_商品プール"

Replace-LiteralText `
    -Path $active03 `
    -OldText "日本語版データ/TOEIC/実験データ/toeic_product_pool_final.csv" `
    -NewText "日本語版データ/TOEIC/02_商品プール/toeic_product_pool_final.csv"

Replace-LiteralText `
    -Path $active03 `
    -OldText "日本語版データ/TOEIC/実験データ" `
    -NewText "日本語版データ/TOEIC/03_購入意図"

Replace-LiteralText `
    -Path $active02 `
    -OldText "07_TOEIC商品データクレンジング.py" `
    -NewText "01_楽天TOEIC商品データをクレンジング.py"

Write-Step "4. Markdown内のファイル名と主要パスを更新"

$textTargets = @()
$docsDir = To-NativePath "日本語版ドキュメント"
if (Test-Path -LiteralPath $docsDir) {
    $textTargets += Get-ChildItem -LiteralPath $docsDir -Recurse -File -Filter "*.md"
}

$rootReadmeJa = To-NativePath "README_日本語.md"
if (Test-Path -LiteralPath $rootReadmeJa) {
    $textTargets += Get-Item -LiteralPath $rootReadmeJa
}

$docReplacements = @(
    @(
        "07_TOEIC商品データクレンジング.py",
        "01_楽天TOEIC商品データをクレンジング.py"
    ),
    @(
        "08_TOEIC商品プール再構成.py",
        "02_実験用TOEIC商品プールを作成.py"
    ),
    @(
        "10_TOEIC購入意図テンプレート作成.py",
        "03_TOEIC購入意図テンプレートを作成.py"
    ),
    @(
        "日本語版データ/TOEIC/元データ",
        "日本語版データ/TOEIC/00_元データ"
    ),
    @(
        "日本語版データ/TOEIC/加工済み",
        "日本語版データ/TOEIC/01_クレンジング済み"
    ),
    @(
        "日本語版データ/TOEIC/実験データ/toeic_product_pool",
        "日本語版データ/TOEIC/02_商品プール/toeic_product_pool"
    ),
    @(
        "日本語版データ/TOEIC/実験データ/toeic_purchase_intents",
        "日本語版データ/TOEIC/03_購入意図/toeic_purchase_intents"
    )
)

foreach ($target in $textTargets) {
    foreach ($replacement in $docReplacements) {
        Replace-LiteralText `
            -Path $target.FullName `
            -OldText $replacement[0] `
            -NewText $replacement[1]
    }
}

Write-Step "5. .gitignoreを新しいデータ構成に対応"

$gitignorePath = To-NativePath ".gitignore"
if (Test-Path -LiteralPath $gitignorePath) {
    $gitignore = [IO.File]::ReadAllText($gitignorePath)
    $oldBlock = @'
# Rakuten Books TOEIC local datasets and experiment outputs
日本語版データ/TOEIC/元データ/*
日本語版データ/TOEIC/加工済み/*
日本語版データ/TOEIC/実験データ/*
日本語版データ/実験結果/*
!日本語版データ/実験結果/.gitkeep
'@

    $newBlock = @'
# Rakuten Books TOEIC local datasets and experiment outputs
日本語版データ/TOEIC/00_元データ/*
日本語版データ/TOEIC/01_クレンジング済み/*
日本語版データ/TOEIC/02_商品プール/*
日本語版データ/TOEIC/03_購入意図/*
日本語版データ/TOEIC/04_API実験/*
日本語版データ/TOEIC/05_分析結果/*
日本語版データ/TOEIC/99_旧版/*
!日本語版データ/TOEIC/04_API実験/.gitkeep
!日本語版データ/TOEIC/05_分析結果/.gitkeep
!日本語版データ/TOEIC/99_旧版/.gitkeep
'@

    if ($gitignore.Contains($oldBlock)) {
        if ($Preview) {
            Write-Host "[Preview] update: .gitignore"
        }
        else {
            $gitignore = $gitignore.Replace($oldBlock, $newBlock)
            [IO.File]::WriteAllText(
                $gitignorePath,
                $gitignore,
                [Text.UTF8Encoding]::new($false)
            )
        }
    }
    elseif (-not $gitignore.Contains("日本語版データ/TOEIC/00_元データ/*")) {
        if ($Preview) {
            Write-Host "[Preview] append new TOEIC ignore rules"
        }
        else {
            [IO.File]::AppendAllText(
                $gitignorePath,
                "`r`n" + $newBlock + "`r`n",
                [Text.UTF8Encoding]::new($false)
            )
        }
    }
}

Write-Step "6. フォルダ説明READMEを作成"

$codeReadme = @'
# 日本語版コード

現在使うPythonファイルは、上から順番に実行します。

| 順番 | ファイル | 何をするか | 主な出力先 |
|---:|---|---|---|
| 1 | `01_楽天TOEIC商品データをクレンジング.py` | 楽天ブックスの元Excelを整形し、明らかに使えない商品を除外する | `01_クレンジング済み/` |
| 2 | `02_実験用TOEIC商品プールを作成.py` | 価格欠損と明確な同一商品だけを除き、実験用の商品一覧を作る | `02_商品プール/` |
| 3 | `03_TOEIC購入意図テンプレートを作成.py` | 対象商品をTrain・Validation・Testへ分け、購入意図を記入するテンプレートを作る | `03_購入意図/` |

## 実行コマンド

```powershell
uv run python ".\日本語版コード\01_楽天TOEIC商品データをクレンジング.py"
uv run python ".\日本語版コード\02_実験用TOEIC商品プールを作成.py"
uv run python ".\日本語版コード\03_TOEIC購入意図テンプレートを作成.py"
```

## `99_旧版`

以前の「200件へ絞る方式」と「古い教材・版違いを除外する方式」を再現する保存用コードです。現在の研究では実行しません。
'@

$dataReadme = @'
# TOEIC研究データ

データは処理順にフォルダを分けています。数字の小さい順に見れば、研究の流れが分かります。

| フォルダ | 内容 | 代表ファイル |
|---|---|---|
| `00_元データ/` | Octoparseで取得した未加工データ。直接編集しない | `rakuten_toeic_raw_20260727.xlsx` |
| `01_クレンジング済み/` | 明らかに使えない商品を除外・整形したデータ | `toeic_products_clean.csv` |
| `02_商品プール/` | 実験対象候補と除外記録 | `toeic_product_pool_final.csv` |
| `03_購入意図/` | 短文・長文クエリを作成するテンプレート | `toeic_purchase_intents_review.xlsx` |
| `04_API実験/` | 元順位、リライト結果、再順位、APIログ | 今後作成 |
| `05_分析結果/` | 集計表、統計検定、グラフ、ポスター用出力 | 今後作成 |
| `99_旧版/` | 現在は使わない途中生成物・旧方式の出力 | 保存のみ |

## 重要

- `00_元データ`は原本なので上書きしません。
- CSV・Excel・API結果はGitHubへアップロードしない設定です。
- GitHubにはコード、README、実験条件、再現手順だけを保存します。
- 旧方式のファイルは削除せず、`99_旧版`へ移動します。
'@

Write-Utf8File `
    -Path (To-NativePath "日本語版コード/README.md") `
    -Content $codeReadme

Write-Utf8File `
    -Path (To-NativePath "日本語版データ/TOEIC/README.md") `
    -Content $dataReadme

Write-Step "整理結果"

Write-Host "現役コード:"
Write-Host "  01_楽天TOEIC商品データをクレンジング.py"
Write-Host "  02_実験用TOEIC商品プールを作成.py"
Write-Host "  03_TOEIC購入意図テンプレートを作成.py"
Write-Host ""
Write-Host "データフォルダ:"
Write-Host "  00_元データ"
Write-Host "  01_クレンジング済み"
Write-Host "  02_商品プール"
Write-Host "  03_購入意図"
Write-Host "  04_API実験"
Write-Host "  05_分析結果"
Write-Host "  99_旧版"

if ($Preview) {
    Write-Host "`nPreviewのため、実際の変更はしていません。"
}
else {
    Write-Host "`n完了しました。次のコマンドで変更を確認してください。" -ForegroundColor Green
    Write-Host "git status"
    Write-Host "git diff --stat"
}
