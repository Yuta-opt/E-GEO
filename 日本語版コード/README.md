# 日本語版コード

このフォルダには、E-GEO日本語TOEIC縮小再現実験で現在使用するコードだけを置きます。

## 実行順

| 順番 | ファイル | 役割 | API |
|---:|---|---|---|
| 1 | `01_楽天TOEIC商品データをクレンジング.py` | 元商品データを整形し、明らかに使えない商品を除外する | なし |
| 2 | `02_実験用TOEIC商品プールを作成.py` | 価格欠損と明確な同一商品を除き、270件の商品プールを作る | なし |
| 3 | `03_TOEIC購入意図テンプレートを作成.py` | 商品を見ずに80件の購入意図を作る | なし |
| 4 | `04_TOEIC候補商品を割り当て.py` | 長文クエリと270商品を埋め込み、上位30件を取得する | なし |
| 5 | `04b_TOEIC候補10商品を選ぶ.py` | 上位30件からLLMで関連商品10件を選び、seed 42で対象商品を固定する | `--execute`時のみ |
| 6 | `04c_TOEIC候補検索入力を検証.py` | Dense結果が確定クエリと最終商品説明から作られたか照合する | なし |
| 7 | `05a_TOEICメタ最適化実験を計画.py` | Train／ValidationスケジュールとAPI予定回数を作る | なし |
| 8 | `05b_TOEIC候補選定API直前チェック.py` | 候補選定の入力、モデル、APIキーを検査する | なし |
| 9 | `05c_TOEICメタ最適化API実験を自動実行.py` | 15プロンプトの最適化、Validation選択、Test長文・短文評価を実行する | `--execute`時のみ |
| 10 | `06_TOEICメタ最適化実験結果を分析.py` | 統計、初期対最適化、長文対短文、収束、特徴、図表を生成する | なし |

## OpenAI APIキー1つでの自動実行

単一の`OPENAI_API_KEY`で、異なるOpenAIモデルを次の役割に割り当てます。

```text
Rewriter              GPT-4.1
Meta-optimizer         GPT-4.1
Training Model A       GPT-4.1
Training Model B       GPT-4.1 mini
Held-out Model E       GPT-5
Candidate selector     GPT-5 mini
```

モデルID、単価、予算停止条件は次の設定に分離しています。

```text
日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json
```

この構成は複数モデルを使いますが、全モデルがOpenAI提供です。複数企業のモデルを使う構成より、提供元をまたいだ一般化検証は弱くなります。この制約は研究発表で明記します。

## 一括実行スクリプト

```text
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

### APIを使わない最終確認

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Validate
```

次を行います。

- `uv sync`
- 全コードの構文チェック
- Dense入力照合
- 候補選定dry-run
- メタ最適化計画作成
- APIキー・モデル直前チェック
- 05cのdry-run

API呼び出しは0回です。

### 小規模な全工程確認

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Smoke
```

候補10件を80購入意図で確定した後、1初期プロンプト、Train 2件、Validation 1件、Test 1件で、リライト、Re-ranking、Meta-optimizer、Test、分析まで動かします。

### 正式実験

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Full
```

既定では、正式実験前にsmokeを実行します。既にsmoke確認済みなら、次で省略できます。

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Full -SkipSmoke
```

予算hard stopは既定100ドルです。変更例：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Full -HardStopUsd 80
```

## APIキー

`.env.example`を参考に、リポジトリ直下の`.env`へ次の1行だけ設定します。

```env
OPENAI_API_KEY=発行したキー
```

`.env`は`.gitignore`対象です。キーをチャット、スクリーンショット、GitHubへ載せません。

## 再開と二重課金防止

05cはAPI応答を、入力・モデル・工程から作った安定した`job_id`でJSONLキャッシュします。

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/01_llm_cache.jsonl
```

途中で停止しても同じコマンドを再実行できます。成功済みの同一ジョブはAPIを再度呼ばず、キャッシュを再利用します。20、50、80ドル到達時に警告し、hard stopへ到達すると停止します。

## 主な出力

### 04 候補商品

```text
日本語版データ/TOEIC/04_候補商品/
├─ 07_candidate_assignments.csv
├─ 08_toeic_experiment_instances.json
├─ 09_candidate_selection_summary.json
└─ 10_candidate_assignments_review.xlsx
```

### 05 API実験

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/
├─ 00_execution_plan.json
├─ 01_llm_cache.jsonl
├─ 02_optimization_versions.jsonl
├─ 03_final_prompts.json
├─ 04_test_results.jsonl
├─ 05_cost_ledger.csv
└─ 06_run_summary.json
```

### 06 分析

```text
日本語版データ/TOEIC/06_分析結果/
├─ 01_test_summary.csv
├─ 02_initial_vs_optimized_paired.csv
├─ 03_prompt_convergence.csv
├─ 04_prompt_feature_matrix.csv
├─ 05_prompt_feature_summary.csv
├─ 06_results_summary.json
├─ 07_initial_vs_optimized.png
├─ 08_long_vs_short.png
├─ 09_prompt_convergence.png
└─ 10_results_review.xlsx
```

## 旧設計

単一の完成プロンプトを比較する旧05〜07、`Original／EN-Zero／JA-Zero／JA-Adapted`設計、旧候補割当、旧分析結果は削除済みです。現在の05c・06は、15種類の初期プロンプトを別々にメタ最適化する設計です。
