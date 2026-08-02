# TOEIC実験：OpenAI単一キー自動実行設計

最終更新：2026年8月2日  
状態：**実装済み・API未実行・ローカルValidate待ち**

## 1. 目的

従来は、候補10件選定までは実行できても、その後のメタ最適化、Validation選択、Test評価、分析を個別に実装・実行する必要があった。

現在は、リポジトリ直下の`.env`へ`OPENAI_API_KEY`を1つ設定し、PowerShellスクリプトを1本実行すると、次の工程を順に実行できる。

```text
入力・コード検証
        ↓
候補30件→10件を80購入意図で選定
        ↓
seed 42で対象商品を固定
        ↓
15初期プロンプトを別々にメタ最適化
        ↓
各版をValidationで評価
        ↓
各初期プロンプトの最高版を固定
        ↓
Held-out Re-rankerでTest長文を評価
        ↓
固定済み最適化プロンプトをTest短文で追加評価
        ↓
統計・収束・特徴・図表を自動生成
        ↓
件数、重複、費用、出力の完了検査
```

## 2. 実行ファイル

```text
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

### APIを使わない検証

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Validate
```

### 小規模全工程

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Smoke
```

### 正式実験

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI単一キー.ps1" -Mode Full
```

## 3. モデル構成

設定ファイル：

```text
日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json
```

| 役割 | モデル |
|---|---|
| 候補30件→10件 | `gpt-5-mini-2025-08-07` |
| Rewriter | `gpt-4.1-2025-04-14` |
| Meta-optimizer | `gpt-4.1-2025-04-14` |
| Training Model A | `gpt-4.1-2025-04-14` |
| Training Model B | `gpt-4.1-mini-2025-04-14` |
| Held-out Model E | `gpt-5-2025-08-07` |

Re-ranker名はMeta-optimizerへ`Model A`、`Model B`として渡す。Held-out Model Eは、最適化履歴へ渡さず、プロンプト固定後のTestだけで使う。

## 4. 先行研究との対応

維持するもの：

- 15種類の初期プロンプト
- Query-blind Rewriter
- 複数Re-rankerの順位結果
- エンジン名の匿名化
- Trainのバッチごとのプロンプト更新
- 各版のValidation評価
- Validation最高版の固定
- Held-out Re-rankerによるTest
- `元順位 - リライト後順位`
- 初期プロンプトと最適化プロンプトの比較
- 意味的収束の分析

変更するもの：

- 先行研究は複数企業を含む4学習Re-ranker・2評価専用Re-ranker
- 単一キー構成はOpenAI内の2学習Re-ranker・1評価専用Re-ranker

したがって、手順の中核は維持するが、提供元をまたぐ一般化の検証は弱い。発表では次を明記する。

> 計算・実装制約のため、単一提供元の異なるモデルを学習Re-rankerおよび評価専用Re-rankerとして用いた縮小再現実験である。

## 5. APIランナー

```text
日本語版コード/05c_TOEICメタ最適化API実験を自動実行.py
```

主な機能：

- `smoke`と`full`を分離
- 40 Trainをseed 42で各epochごとに決定的に再シャッフル
- 2 epochs × 4 batches × 10件
- 15プロンプトごとに独立した軌跡
- 各版をValidation 10件で評価
- 各初期プロンプト6回のMeta-optimizer更新
- Validation平均最大版を固定
- Testは固定完了後にだけ実行
- 成功済みAPI応答の再利用
- API失敗時の最大3回再試行
- 入出力トークンと概算費用の記録
- 20、50、80ドルで警告
- 既定100ドルでhard stop

## 6. キャッシュと再開

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/01_llm_cache.jsonl
```

APIジョブは、工程、モデル、入力、プロンプト、バージョンから安定した`job_id`を作る。同じコマンドを再実行した場合、成功済みの同一ジョブはAPIを再呼び出しせず、保存結果を利用する。

途中でPCやターミナルを閉じた場合も、同じFullコマンドから再開できる。

## 7. 自動分析

```text
日本語版コード/06_TOEICメタ最適化実験結果を分析.py
```

自動生成するもの：

- 条件・プロンプト・Re-ranker別の平均順位改善量
- 上昇、不変、低下率
- 標準偏差と標準誤差
- 初期版対最適化版の対応比較
- Wilcoxon符号付順位検定
- 最適化長文対短文の比較
- 15プロンプトの平均ペアワイズ・コサイン距離
- 重心からの距離
- 10種類の戦略特徴
- CSV、JSON、Excel、PNG図表

## 8. 完了判定

```text
日本語版コード/07_TOEIC研究完了チェック.py
```

正式実験では次を検査する。

```text
候補instance：80件
Train／Validation／Test：40／10／30
最終プロンプト：15件
最適化版：15 × 8 = 120件
Test初期長文：450行
Test最適化長文：450行
Test最適化短文：450行
Test合計：1,350行
重複結果：0
分析ファイル：全件存在
API概算費用：hard stop未満
```

全検査に合格すると、次の状態になる。

```text
research_numeric_results_complete
```

これは、数値結果、統計、収束分析、図表がそろった状態を示す。研究の主観的な解釈確認とポスターの最終レイアウトは別作業である。

## 9. APIキー

`.env.example`を参考に、リポジトリ直下へ`.env`を作成する。

```env
OPENAI_API_KEY=発行したキー
```

`.env`はGit管理対象外である。APIキーをGitHub、チャット、スクリーンショットへ載せない。
