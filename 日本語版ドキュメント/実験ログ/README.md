# TOEIC E-GEO 実験ログ索引

このディレクトリは、YANS 2026向け日本語TOEIC E-GEO実験の**公開用・再現確認用成果物**を保存します。APIキー、生レスポンス、大容量キャッシュ、元商品データは保存しません。

## 正式版 / Canonical

### `2026-08-08_3モデル統合_最終結果/`

GPT-5・Gemini 3.5 Flash・Claude Sonnet 4.5 の3評価モデルを統合した**最終結果フォルダ**です。

最終ポスター、考察、Table 6相当、統計検定、モデル比較グラフではこのフォルダを参照します。

主な成果物:

- `00_validation_report.json` — 3モデル・2700行の整合性確認
- `01_three_model_integrated_table.csv` — 3モデル統合表
- `02_model_level_statistical_tests.csv` — モデル単位の主要統計検定
- `03_prompt_level_statistical_tests.csv` — 45比較の補助統計検定
- `04_prompt_by_model_recovery.csv` — 15プロンプト×3モデルの回復量
- `05_three_model_paired_rows.csv` — 対応比較用1350行
- `06_three_model_results_summary.json` — 最終集計値
- `07_three_model_initial_vs_optimized.png` — 初期 vs 最適化後（3モデル）
- `08_three_model_recovery.png` — モデル別回復量
- `09_prompt_recovery_heatmap.png` — プロンプト別×モデル別回復量
- `10_three_model_results.xlsx` — 統合Excel
- `11_three_model_report.md` — 日本語分析レポート
- `ポスター用図表/` — ポスターに直接使う最新版PNGを集約

生成元はローカルの `日本語版データ/TOEIC/06_分析結果/03_3モデル統合/` です。このローカル分析ディレクトリは `.gitignore` 対象のため、公開用成果物だけをここへコピーします。

## 旧版 / Legacy

### `2026-08-07_OpenAI_Gemini_Full結果/`

GPT-5 + Gemini の2モデル時点の中間成果です。再現記録として残しますが、**3モデル最終結果が揃った後は最終ポスターのモデル比較グラフに使用しません**。

ただし、以下のモデル非依存または補助分析は引き続き利用できます。

- 最終プロンプト
- プロンプト最適化trajectory
- プロンプト意味収束
- GPT-5短文クエリ転移

### `2026-08-06_OpenAI_Gemini_Smoke/`

本実験前のSmoke Testです。最終結果には使用しません。

## 最終結果の公開手順

ローカルでClaude回収と3モデル分析が完了した後、以下を実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\publish_toeic_three_model_results.ps1" -Mode Publish
```

このコマンドはAPIを呼ばず、入力・件数を再検証した上で3モデル分析を再生成し、公開用成果物と最新版グラフを `2026-08-08_3モデル統合_最終結果/` に集約します。

## 解釈上の注意

`rank_improvement = original rank - rewritten rank` です。

- 正: 原文より順位上昇
- 0: 原文と同等
- 負: 原文より順位低下

したがって、最適化後平均が0未満の場合は「順位が全体として上昇した」ではなく、**「初期プロンプトによる順位悪化がメタ最適化で大幅に緩和された」**と記述します。
