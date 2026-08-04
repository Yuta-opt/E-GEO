# E-GEO 日本語TOEIC縮小再現実験

E-GEO v2の中核である、**複数Re-rankerの順位結果を用いたプロンプトのメタ最適化**を、日本語のTOEIC教材領域で小規模に再現する研究です。

研究の位置付け：

> **E-GEO v2の中核アルゴリズムを維持したscaled-down replication ＋ 日本語・TOEIC・短文検索への拡張**

## 研究の中心

```text
15種類の初期リライトプロンプト
        ↓
TrainでGPT-4.1・Geminiの順位改善量を測定
        ↓
Trainのプロンプト本文・エンジン別結果だけを履歴へ追加
        ↓
Meta-optimizerが次のプロンプトを生成
        ↓
Validation平均が最も高い版を固定
        ↓
未使用TestをGPT-5・Gemini・Claudeで最終評価
        ↓
初期版対最適化版、長文対短文、プロンプト収束を分析
```

**Validationは版選択専用で、Meta-optimizerへ渡しません。**

## データ

- 楽天ブックスで収集：300商品
- クレンジング後：271商品
- 最終商品プール：270商品
- 購入意図：80件
- Train 40／Validation 10／Test 30
- 主実験：長文購入相談
- 追加実験：Googleサジェスト由来の短文検索

購入意図の正本は`toeic_query_intents_review.xlsx`です。Dense Retrievalの2,400行について、正本の`long_query_final`と最終商品プールの`title + description_clean`を使用したことを照合し、不一致0件を確認済みです。

## 候補商品の作成

```text
270商品
  ↓
多言語Sentence TransformerによるDense Retrieval
  ↓
コサイン類似度上位30件
  ↓
OpenAI GPT-5 miniによる関連商品10件の選定
  ↓
seed 42で対象商品1件を固定
```

埋め込みモデルは`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`です。カテゴリ絞り込み、タイトルへの独自重み付け、目標得点加点は使用しません。

## 正式実験のモデル構成

```text
Candidate selector     OpenAI GPT-5 mini
Rewriter               OpenAI GPT-4.1
Meta-optimizer          OpenAI GPT-4.1

学習Re-ranker
Model A                 OpenAI GPT-4.1
Model B                 Google Gemini 3 Flash Preview

固定後のHeld-out Test評価
Model E                 OpenAI GPT-5
Model F                 Google Gemini 3.5 Flash
Model G                 Anthropic Claude Sonnet 4.5
```

必要なAPIキー：

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

先行研究は4学習Re-rankerと2評価専用Re-rankerを使用しました。本研究は計算予算に合わせて学習Re-rankerをGPT-4.1とGeminiへ縮小し、Testでは最適化に未使用のGPT-5・Gemini・Claudeを同一条件で評価します。

## 先行研究との対応

### 維持する中核条件

- 候補10商品をGEO実験前に固定
- 対象商品を事前固定
- Rewriterはquery-blind
- 順位改善量：元順位 − リライト後順位
- 複数エンジンのTrain結果でプロンプトを改善
- エンジン名をModel A／Bとして匿名化
- Validationは最良版選択専用
- Testはプロンプト固定後まで未使用
- 初期版と最適化版を同じTestで比較

### 縮小条件

```text
初期プロンプト 15
Train / Validation / Test = 40 / 10 / 30
2 epochs
4 batches per epoch
batch size 10
各初期プロンプト8評価版
各初期プロンプト6更新
```

### モデルファミリー別Re-ranker System Prompt

正式ランナーは原著コードの各System Promptを直接使用します。

```text
src/multi_model_optimization/prompts.py
```

- GPT-4.1用
- GPT-5用
- Gemini用
- Claude用

全モデルへ短い共通System Promptを使う旧方式は、正式結果には使用しません。

### Rewriter入力

原著実装へ近づけるため、Rewriterへ対象商品の以下を渡します。

- 商品名
- 商品説明

購入クエリは渡しません。リライト後は対象listing全体を置き換え、固定した他9商品と再ランキングします。

## 正式実行経路

正式入口：

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

内部で使用する本体：

```text
日本語版コード/05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py
```

設定：

```text
日本語版設定/TOEIC_EGEO実験設定_v3_先行研究準拠.json
日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
```

APIを使わない構文・入力・設定確認：

```powershell
powershell -ExecutionPolicy Bypass -File `
".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" `
-Mode Validate
```

3社すべてを少数データで確認：

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

20・50・80ドルで警告し、既定100ドルで停止します。成功済みAPIジョブはJSONLキャッシュから再利用するため、途中停止後に同じコマンドで再開できます。

## 正式分析

分析コード：

```text
日本語版コード/06b_TOEIC先行研究準拠結果分析.py
```

### 順位結果

- 初期版 vs 最適化版
- Wilcoxon対応検定
- 上昇率・不変率・低下率
- 長文Test vs 短文Test
- GPT-5・Gemini・Claude別比較

### 埋め込み収束

先行研究と同じ`text-embedding-3-large`を使い、15プロンプトの全評価版について次を追跡します。

- 平均コサイン距離 to centroid
- 平均pairwise cosine distance

### 10特徴

E-GEO v2 Section 5.5.1と同様に、人間が次の三段階で評価します。

- 0：Absent
- 1：Implicit
- 2：Explicit

自動キーワード一致は正式な特徴分析として使用しません。

正式実験後に生成される評価表：

```text
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
04_prompt_feature_manual_review.xlsx
```

## 完了チェック

```text
日本語版コード/07b_TOEIC先行研究準拠完了チェック.py
```

次を区別して判定します。

1. 数値結果・統計・埋め込み分析が完成
2. 10特徴の人手評価だけが未入力
3. 人手評価を含む全分析が完成

## OpenAI単一キー版

```text
日本語版コード/05c_TOEIC_OpenAI単一キー実験を自動実行.py
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

構造確認・比較用として残しますが、提供元横断の正式結果には使用しません。

## 出力を混ぜない

### OpenAI単一版

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/
```

### 正式3社版

```text
日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
```

## 現在地

完了：

- 商品クレンジングと270商品固定
- 購入意図80件、長文・短文クエリ
- Dense Retrieval上位30件
- Dense入力の完全一致検証
- 初期プロンプト15種類
- 2 epochs・4 batches・8評価版のスケジュール
- Validation漏洩を除去した先行研究準拠ランナー
- モデルファミリー別System Prompt
- 商品名＋商品説明を用いるquery-blind Rewriter
- GPT・Gemini・Claudeの3モデルHeld-out Test設定
- `text-embedding-3-large`収束分析
- 10特徴の0／1／2人手評価表
- 先行研究準拠完了チェック

未完了：

- GPT-5 miniによる候補30件→10件の有料選定
- 3社APIのsmoke実行
- 実測トークンによる最終費用確定
- 正式Train／Validation／Test
- 10特徴の人手評価
- ポスターへの結果反映

**正式な有料API実験はまだ開始していません。**

## 正本ドキュメント

- `日本語版ドキュメント/TOEIC先行研究準拠_2026-08-05修正記録.md`
- `日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md`
- `日本語版ドキュメント/TOEIC_API費用と完了見込み.md`
- `日本語版ドキュメント/TOEIC購入意図クエリ作成記録.md`
- `日本語版ドキュメント/先行研究/`
