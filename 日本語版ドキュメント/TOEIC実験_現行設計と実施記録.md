# TOEIC実験：現行設計と実施記録

最終更新：2026年8月5日  
対象ブランチ：`ja-toeic-prototype`  
現行設計：**E-GEO v2のメタ最適化を中核とする、日本語TOEIC教材でのscaled-down replication**

この文書を、研究設計・実装状況・運用判断の正本とする。

> 2026年8月2日以前の`Original／EN-Zero／JA-Zero／JA-Adapted`比較は廃止済み。  
> 商品・購入意図・Dense Retrieval・実験ランナー・分析・完了検査は実装済み。  
> 2026年8月5日時点では、正式な有料API実験は開始していない。ポスターは結果差し替え前提で先に完成させる。

---

## 1. 研究を一文でいうと

> 英語環境で提案された15種類のE-GEO戦略を日本語TOEIC教材へ適用し、複数LLMの順位評価履歴から自動改善したプロンプトが、初期プロンプトより推薦順位を上げるか、さらに未学習モデルと短文検索へ転移するかを検証する。

本研究は、先行研究の全規模・全モデルを完全再現するものではない。維持するのは、候補固定、query-blind Rewriter、複数Re-rankerによるTrain、Validation選択、Testロック、初期版対最適化版、プロンプト収束という中核構造である。

---

## 2. 研究問い

1. 日本語へ忠実に翻訳した15種類の初期プロンプトは、元の商品説明より推薦順位を改善するか。
2. Trainの順位履歴を使ったメタ最適化により、初期版より最適化版の順位改善量が高くなるか。
3. 異なる15種類の初期プロンプトは、共通するGEO戦略へ意味的・特徴的に収束するか。
4. 長文購入相談で固定した最適化プロンプトは、短文検索でも効果を保つか。
5. 最適化に使っていないGPT-5・Gemini・Claudeでも改善が確認できるか。

---

## 3. 固定済みデータ

### 商品

```text
初期収集：300件
利用不能として除外：29件
クレンジング後：271件
明確な同一商品として除外：1件
最終商品プール：270件
```

正式ファイル：

```text
日本語版データ/TOEIC/02_商品プール/toeic_product_pool_final.csv
```

### 購入意図

```text
Train：40件
Validation：10件
Test：30件
合計：80件
```

長文購入相談とGoogleサジェスト由来短文を1対1で保持する。購入意図は商品を見ずに作成し、対象商品を有利にする条件の後付けを避けた。

正式ファイル：

```text
日本語版データ/TOEIC/03_購入意図/toeic_query_intents_review.xlsx
```

### Dense Retrieval

- 埋め込みモデル：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- クエリ：承認済み`long_query_final`
- 商品文：`title + description_clean`
- 80購入意図×上位30商品＝2,400行
- 正本との完全一致検証：不一致0件

カテゴリ絞り込み、タイトル独自加重、目標得点加点は使用しない。

---

## 4. 正式実験フロー

```text
270商品
  ↓
長文購入相談80件でDense Retrieval
  ↓
各購入意図の上位30商品を固定
  ↓
GPT-5 miniで関連商品10件を選定
  ↓
seed 42で対象商品1件を固定
  ↓
15種類の初期プロンプトを別々に実行
  ↓
Train 40件を4グループ×2 epochで評価
  ↓
GPT-4.1とGeminiの順位履歴からプロンプトを更新
  ↓
各版をValidation 10件で評価
  ↓
Validation平均が最高の版を固定
  ↓
固定後にのみHeld-out Testを実行
  ↓
初期版対最適化版、長文対短文、モデル別、収束を分析
```

### 版数と更新回数

各初期プロンプトについて、4グループ×2周の**8版を評価**する。各epochの最後には次版を作らないため、Meta-optimizerによる実際の更新は**6回**である。

### Testロック

Test 30件は、プロンプトの作成・更新・選択には使用しない。Validationで最良版を固定した後にのみ評価する。

### Query-blind Rewriter

Rewriterへ渡すもの：

- 商品名
- 商品説明
- リライトプロンプト

評価クエリは渡さない。リライト後は対象listing全体を置き換え、固定した他9商品と再ランキングする。

---

## 5. 現在のモデル構成

### 候補選定

- OpenAI GPT-5 mini

### Train・Validation

- Rewriter：OpenAI GPT-4.1
- Meta-optimizer：OpenAI GPT-4.1
- Model A：OpenAI GPT-4.1
- Model B：Google Gemini 3.1 Flash-Lite

Model A／Bの名称はMeta-optimizerへ匿名化して渡す。Validation結果は版選択専用で、Meta-optimizerの履歴へ含めない。

### 固定後のHeld-out Test

- Model E：OpenAI GPT-5
  - 初期プロンプト・長文Test
  - 最適化プロンプト・長文Test
  - 最適化プロンプト・短文Test
- Model F：Google Gemini 3.5 Flash-Lite
  - 初期プロンプト・長文Test
  - 最適化プロンプト・長文Test
- Model G：Anthropic Claude Sonnet 5
  - 最適化プロンプト・長文Testのみ
  - OpenAI＋Gemini完了後に追加可能

3モデルで条件が完全には同じでないため、全条件を単一平均へ混ぜない。公平な提供元比較はGPT-5とGeminiの共有長文条件、短文転移はGPT-5を主結果、Claudeは追加転移確認として報告する。

---

## 6. 予算設計

| Provider | 本体上限 | 主な役割 |
|---|---:|---|
| OpenAI | 98 USD | Rewriter、Meta-optimizer、主学習評価、GPT-5 Test |
| Google Gemini | 15 USD | 第2学習評価、長文Held-out Test |
| Anthropic Claude | 8 USD | 最適化済み長文Testの追加評価 |
| 本体合計 | 121 USD | Claude追加時の最大構成 |

OpenAIアカウントの100 USDのうち、本体ランナーは98 USDで停止する。残り2 USDは候補10件選定、`text-embedding-3-large`による収束分析、最後の1リクエストの小さな超過に予約する。

### hard stop

- OpenAI＋Gemini先行段階：総額113 USD
- Claude追加後：総額121 USD
- Provider別hard stopを新規API呼び出し前に検査
- 成功済みジョブはJSONLキャッシュから再利用
- 上限到達後も、別Providerの不足分だけ後日追加可能

詳細：

```text
日本語版ドキュメント/TOEIC_API費用配分_2026-08-05.md
```

---

## 7. 正式実行経路

### 現在の第一段階：OpenAI＋Gemini

```text
tools/実行_TOEIC研究_OpenAI_Gemini.ps1
```

内部経路：

```text
05f_TOEIC先行研究準拠_OpenAI_Gemini実験.py
  ↓
05h_TOEIC費用配分安全実行.py
  ↓
05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py
  ↓
05e／05d／05cの共通実験処理
```

### 後日追加：Claude

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

同じ出力フォルダを再利用し、成功済みOpenAI・Geminiジョブ、リライト、固定プロンプトをキャッシュから読み、Claudeの不足ジョブだけを追加する。

### 実行モード

```powershell
# APIを呼ばない構文・入力・設定確認
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate

# 少数件の有料接続・形式・実測費用確認
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Smoke

# 正式実験
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Full
```

2026年8月5日時点では、Validateまでの構造確認は完了している。Smoke・Fullの有料リクエスト部分は未実行である。

---

## 8. 分析と日本語版Table 6

正式分析：

```text
日本語版コード/06b_TOEIC先行研究準拠結果分析.py
```

完了検査：

```text
日本語版コード/07b_TOEIC先行研究準拠完了チェック.py
```

### 最終的に出す主要結果

1. 元説明対初期15戦略
2. 初期版対最適化版
3. GPT-5・Gemini・Claude別結果
4. 長文Test対短文Test
5. 15プロンプトの意味的収束
6. 10特徴の0／1／2人手評価

### ポスター用の日本語版Table 6

結果確定後、少なくとも次の列を出す。

| 評価モデル | クエリ条件 | 初期版平均順位改善 | 最適化版平均順位改善 | 差 | Wilcoxon p値 | 上昇率 | 不変率 | 低下率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|

- GPT-5：長文と短文
- Gemini：共有長文条件
- Claude：最適化済み長文の追加転移結果として別枠

Claudeには初期版の同条件がないため、初期対最適化の公平比較表へ無理に混ぜない。

---

## 9. ポスター先行方針

API予算と実行時間が確定していないため、A0ポスターは先に以下まで完成させる。

- 背景・目的・研究問い
- データ作成とTrain／Validation／Test分割
- 候補30件→10件の固定手順
- 15初期プロンプトとメタ最適化フロー
- モデル構成とTestロック
- 分析方法・統計検定
- 日本語版Table 6の枠
- グラフの差し替え枠
- 結論・限界・今後の展望の仮文章

API結果が出た後に差し替えるものは、数値、表、グラフ、統計、有効だった特徴、最終結論だけとする。

---

## 10. 現在地

### 完了

- 商品クレンジングと270商品固定
- 購入意図80件、長文・短文クエリ
- Dense Retrieval 2,400行
- Dense入力の完全一致検証
- 初期プロンプト15種類
- 2 epochs・4 batches・8評価版・6更新の計画
- Validation漏洩を除去した先行研究準拠ランナー
- OpenAI・Gemini・Claudeの接続基盤
- Provider別費用集計、警告、hard stop、再開キャッシュ
- `text-embedding-3-large`収束分析
- 10特徴の人手評価表
- 完了チェック

### 未完了

- GPT-5 miniによる候補30件→10件の有料選定
- OpenAI＋Geminiの有料Smoke
- 実測トークンによる費用再推定
- 正式Train／Validation／Test
- Claude追加評価
- 10特徴の人手評価
- 日本語版Table 6・グラフ・結論の結果差し替え

**正式な有料API実験は未開始であり、現在はポスター先行・結果差し替え待ちの状態である。**

---

## 11. 再開時の最短手順

1. `git switch ja-toeic-prototype`と`git pull`で最新版へ更新する。
2. `.env`へ必要なAPIキーを設定する。
3. OpenAIの利用可能額100 USD、Gemini上限15 USDを確認する。
4. `-Mode Validate`を再実行する。
5. 候補10件選定を実行し、レビューExcelを確認する。
6. `-Mode Smoke`を実行し、モデル利用可否、JSON形式、実測費用を確認する。
7. 費用が上限内ならモデル構成を固定し、`-Mode Full`を実行する。
8. `06b`、`07b`を実行する。
9. 日本語版Table 6、グラフ、結論をポスターへ反映する。

Train開始後に結果を見てモデル・データ・候補集合を変更しない。変更が必要な場合はpilotと正式実験を分離し、別出力フォルダで最初から実行する。
