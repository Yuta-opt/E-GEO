# Claude Sonnet 4.5 Held-out評価

## 目的

成功済みのOpenAI・Gemini Full実験を変更せず、固定済みの日本語TOEIC TestをClaude Sonnet 4.5で追加評価する。

- Train・Validation・メタ最適化は再実行しない
- GPT・Gemini APIは再実行しない
- GPT-4.1で生成済みのリライト文章を再利用する
- Claude専用の別キャッシュへ保存する
- 初期長文と最適化長文を評価し、先行研究Table 6形式の「最適化後」と「最適化−初期」を計算する
- 短文Testは行わない

## 評価件数

| 種類 | API呼び出し数 |
|---|---:|
| 元の商品説明の順位 | 30 |
| 初期プロンプト15種 × Test 30件 | 450 |
| 最適化プロンプト15種 × Test 30件 | 450 |
| 合計 | 930 |

Smokeで実行した3件はFull時にキャッシュ再利用される。

## モデルと予算

- モデル：`claude-sonnet-4-5`
- 料金設定：入力 $3 / 1M tokens、出力 $15 / 1M tokens
- 想定：$10–16
- Full開始ゲート：安全余裕込み予測 $16.50以下
- Hard stop：$18
- 予備：$2

Smokeの実測単価からFull費用を推定する。予測がゲートを超えた場合、Fullは自動的に開始拒否される。

## 出力先

`日本語版データ/TOEIC/05_API実験/03_Claude_Heldout評価`

主な出力：

- `00_execution_plan.json`
- `01_claude_cache.jsonl`
- `02_smoke_results.jsonl`
- `02_claude_test_results.jsonl`
- `03_claude_cost_ledger.csv`
- `04_smoke_projection.json`
- `05_claude_test_summary.csv`
- `06_claude_initial_vs_optimized.csv`
- `07_claude_results_summary.json`
- `08_run_summary.json`

`.env`、APIキー、Claudeキャッシュ、生のTest結果はGitHubへ追加しない。

## 実行手順

### 1. Validate（API 0回）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File ".\tools\run_toeic_claude_heldout.ps1" `
  -Mode Validate
```

以下が出ればよい。

```text
Validate完了：APIは呼び出していません。
```

### 2. ANTHROPIC_API_KEY

`.env`へ次の環境変数を設定する。値をチャット、GitHub、スクリーンショットへ出さない。

```text
ANTHROPIC_API_KEY=...
```

### 3. Smoke（3件）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File ".\tools\run_toeic_claude_heldout.ps1" `
  -Mode Smoke
```

`04_smoke_projection.json`の主要項目：

- `status`
- `smoke_cost_usd`
- `full_raw_projection_usd`
- `full_projection_with_margin_usd`
- `full_projection_gate_usd`
- `hard_stop_usd`

`status: pass`のときだけFullへ進む。

### 4. Full（最大930件、Smoke分は再利用）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File ".\tools\run_toeic_claude_heldout.ps1" `
  -Mode Full
```

途中停止しても`01_claude_cache.jsonl`を削除せず、同じコマンドで再開する。

### 5. Analyze（API 0回）

通常はFullの最後に自動実行される。再集計だけを行う場合：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File ".\tools\run_toeic_claude_heldout.ps1" `
  -Mode Analyze
```

## 既存3社ランナーとの違い

既存の`TOEIC_OpenAI_Gemini_Claude実験設定_v1.json`は、Claude Sonnet 5で最適化済み長文だけを評価する旧費用制御案である。本ランナーは先行研究との比較を優先し、Claude Sonnet 4.5で初期長文と最適化長文の両方を評価する。
