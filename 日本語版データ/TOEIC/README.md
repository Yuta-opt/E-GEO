# TOEIC研究データ

ローカルの研究データは、現在のE-GEO縮小再現パイプラインに沿って管理します。CSV、Excel、JSONL、API結果はGitHubへアップロードしません。

| フォルダ | 内容 |
|---|---|
| `00_元データ/` | Octoparseで取得した楽天ブックス300商品の原本。直接編集しない |
| `01_クレンジング済み/` | 明らかに使えない商品を除外し、表記を整えたデータ |
| `02_商品プール/` | 価格欠損と明確な同一商品を除いた商品プール270件 |
| `03_購入意図/` | 商品から独立して作成した80購入意図、短文・長文クエリ、Googleサジェスト元データ |
| `04_候補商品/` | Dense Retrieval上位30件、候補10件選定ジョブ、選定結果、固定対象商品 |
| `05_API実験/` | メタ最適化計画、リライト、Re-ranking、Meta-optimizer履歴、Test結果 |
| `06_分析結果/` | 初期版対最適化版の集計、統計、収束分析、図表 |
| `07_本番前チェック/` | 現行設計に基づく整合性検査と予算確認 |

## 現在の04_候補商品

現行ファイル：

```text
01_dense_retrieval_top30.csv
02_candidate_selection_jobs.jsonl
03_dense_retrieval_summary.json
04_dense_retrieval_review.xlsx
05_candidate_selection_plan.json
```

API利用後に、次が追加されます。

```text
06_candidate_selection_results.jsonl
07_candidate_assignments.csv
08_toeic_experiment_instances.json
09_candidate_selection_summary.json
10_candidate_assignments_review.xlsx
```

旧TF-IDF候補割当で作成した`toeic_candidate_*`と`toeic_experiment_instances.json`は使用しません。

## 現在の05_API実験

```text
00_実行計画/
├─ 01_meta_optimization_schedule.csv
├─ 02_api_call_plan_by_stage.csv
├─ 03_api_call_plan_summary.csv
└─ 04_meta_optimization_plan.json
```

旧`Original／EN-Zero／JA-Zero`設計の`experiment_plan.json`、`rewrite_results.jsonl`、`ranking_results.jsonl`は使用しません。

## 削除した旧フォルダ

次は現行設計と重複・矛盾するため削除します。

```text
04_API実験/
05_分析結果/
99_旧版/
```

旧設計で作られた`06_分析結果/`と`07_本番前チェック/`の中身も一度削除し、今後はメタ最適化設計に対応したコードから再生成します。
