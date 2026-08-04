# 日本語版コード

このフォルダには、E-GEO日本語TOEIC縮小再現実験で使用するコードを置きます。

正式研究の位置付けは次のとおりです。

> 先行研究の中核アルゴリズムを維持した日本語・小規模再現 ＋ 短文クエリへの転移評価

## 正式実験の実行順

| 順番 | ファイル | 役割 | API |
|---:|---|---|---|
| 1 | `01_楽天TOEIC商品データをクレンジング.py` | 元商品データを整形する | なし |
| 2 | `02_実験用TOEIC商品プールを作成.py` | 最終270商品を固定する | なし |
| 3 | `03_TOEIC購入意図テンプレートを作成.py` | 購入意図80件を作る | なし |
| 4 | `04_TOEIC候補商品を割り当て.py` | Dense Retrievalで上位30商品を取得する | なし |
| 5 | `04b_TOEIC候補10商品を選ぶ.py` | GPT-5 miniで30件から10件を選び、対象商品を固定する | `--execute`時のみ |
| 6 | `04c_TOEIC候補検索入力を検証.py` | 確定クエリ・最終商品説明との一致を照合する | なし |
| 7 | `05a_TOEICメタ最適化実験を計画.py` | Train／ValidationスケジュールとAPI予定回数を作る | なし |
| 8 | `05b_TOEIC候補選定API直前チェック.py` | 候補選定APIの入力・モデル・キーを検査する | なし |
| 9 | `05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py` | 先行研究準拠の3社本体実験 | `--execute`時のみ |
| 10 | `06b_TOEIC先行研究準拠結果分析.py` | Test統計・埋め込み収束・人手特徴評価表を生成 | 埋め込みは指定時のみ |
| 11 | `07b_TOEIC先行研究準拠完了チェック.py` | 数値・条件・分析・人手評価状態を検査 | なし |

## 正式3社版のモデル役割

```text
Candidate selector     OpenAI GPT-5 mini
Rewriter               OpenAI GPT-4.1
Meta-optimizer          OpenAI GPT-4.1
Training Model A        OpenAI GPT-4.1
Training Model B        Google Gemini 3 Flash Preview
Held-out Model E        OpenAI GPT-5
Held-out Model F        Google Gemini 3.5 Flash
Held-out Model G        Anthropic Claude Sonnet 4.5
```

必要なキー：

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

## 先行研究準拠版で修正した点

### Validationは版選択専用

Meta-optimizerへ渡す履歴は、各版のプロンプト本文とTrainのエンジン別結果だけです。Validation平均やValidationの個別結果は渡しません。

### モデルファミリー別System Prompt

Re-rankerには原著コードのSystem Promptを使用します。

```text
src/multi_model_optimization/prompts.py
```

- GPT-4.1用
- GPT-5用
- Gemini用
- Claude用

短い共通System Promptで全モデルを評価する旧方式は正式結果に使用しません。

### Rewriter入力

Rewriterへ渡すのは対象商品の以下だけです。

- 商品名
- 商品説明

購入クエリは渡さず、query-blindを維持します。

### 分析

- 埋め込み：`text-embedding-3-large`
- 対象：15プロンプトの全評価版
- 指標：重心への平均コサイン距離、平均ペアワイズ・コサイン距離
- 10特徴：人間が0／1／2で評価

自動キーワード一致による特徴判定は正式な再現結果として使用しません。

## 旧ファイルの扱い

### `05c_TOEIC_OpenAI単一キー実験を自動実行.py`

OpenAIだけで構造を確認する比較用です。提供元横断の正式結果には使用しません。

### `05c_TOEICメタ最適化API実験を自動実行.py`

共通の実験ロジックを保持する内部基盤です。

### `05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py`

3社API接続、キャッシュ、費用管理を提供する内部基盤です。正式には`05e`から読み込みます。

### `06_TOEICメタ最適化実験結果を分析.py`

smokeの構造確認と旧方式比較用です。正式分析は`06b`を使用します。

### `07_TOEIC研究完了チェック.py`

smokeと旧方式の確認用です。正式完了判定は`07b`を使用します。

## 一括実行スクリプト

正式実験は次のPowerShellだけを入口にします。

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

APIを呼ばず、構文・入力・設定だけ検査：

```powershell
powershell -ExecutionPolicy Bypass -File `
".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" `
-Mode Validate
```

3社を少数データで確認：

```powershell
powershell -ExecutionPolicy Bypass -File `
".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" `
-Mode Smoke
```

正式実験：

```powershell
powershell -ExecutionPolicy Bypass -File `
".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" `
-Mode Full
```

## 正式設定

```text
日本語版設定/TOEIC_EGEO実験設定_v3_先行研究準拠.json
日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
```

固定条件：

```text
15初期プロンプト
Train 40 / Validation 10 / Test 30
2 epochs
4 batches per epoch
batch size 10
各プロンプト8評価版
各プロンプト6更新
学習Re-ranker 2モデル
Held-out Test 3モデル
```

## 出力フォルダ

```text
日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
```

人手特徴評価表：

```text
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
04_prompt_feature_manual_review.xlsx
```

`scores`シートへ0／1／2を入力し、分析と完了チェックを再実行すると特徴heatmapまで完成します。

## 再開と予算停止

入力・モデル・工程・System Prompt・User Promptから作成した`job_id`で成功結果をJSONLへ保存します。途中停止後に同じコマンドを実行すると、成功済みジョブはキャッシュから再利用します。

OpenAI・Google・Anthropicの推定費用を合算し、20ドル、50ドル、80ドルで警告し、既定100ドルで停止します。埋め込みも別JSONLへキャッシュします。

## APIキー管理

`.env.example`をコピーして、リポジトリ直下へ`.env`を作ります。実際のキーは`.env`だけへ保存し、GitHub、チャット、スクリーンショットへ載せません。
