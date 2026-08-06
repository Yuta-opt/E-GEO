# TOEIC実験：現行設計と実施記録

最終更新：2026年8月6日  
対象ブランチ：`ja-toeic-prototype`  
現行設計：**E-GEO v2の中核構造を日本語TOEIC教材へ移した、予算縮小型追試＋短文転移実験**

この文書を、研究設計・実装状況・運用判断の正本とする。

> 2026年8月2日以前の`Original／EN-Zero／JA-Zero／JA-Adapted`比較は廃止済み。  
> 2026年8月6日に、API実行前の安全監査で見つかった問題を修正した。  
> 正式な有料API実験はまだ開始していない。

---

## 1. 研究を一文でいうと

> 英語環境で提案された15種類のE-GEOリライト戦略を日本語TOEIC教材へ適用し、複数LLMの順位評価履歴から自動改善したプロンプトが、初期プロンプトより推薦順位を上げるか、さらに未学習モデルと短文検索へ転移するかを検証する。

本研究は先行研究の全規模・全モデル・全System Promptを完全再現するものではない。次の中核構造を維持した**scaled replication**として報告する。

- リライト前に候補商品と対象商品を固定する
- Rewriterへ評価クエリを渡さない
- 対象商品だけを書き換える
- 元順位－書換後順位を評価する
- 複数Re-rankerのTrain結果からプロンプトを更新する
- Validationは版選択だけに使用する
- Testはプロンプト固定後にのみ使用する
- 未学習モデルで転移を評価する

---

## 2. 研究問い

1. 日本語へ忠実に翻訳した15種類の初期プロンプトは、元の商品説明より推薦順位を改善するか。
2. Trainの順位履歴を使ったメタ最適化により、初期版より最適化版の順位改善量が高くなるか。
3. 異なる15種類の初期プロンプトは、共通するGEO戦略へ意味的・特徴的に収束するか。
4. 長文購入相談で固定した最適化プロンプトは、**同じリライト文章のまま**短文検索でも効果を保つか。
5. 最適化に使用していないGPT-5・Gemini、任意追加のClaudeでも改善が確認できるか。

英語原文、日本語翻訳、日本語適応の3条件比較は、現在の正式実験には含めない。

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

長文購入相談と短文検索クエリを1対1で保持する。購入意図は商品を見ずに作成し、対象商品を有利にする条件の後付けを避けた。

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
04d：GPT-5 miniで関連商品10件を選定
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
05i：固定後にのみHeld-out Testを実行
  ↓
06c：統計・収束・人手特徴分析
  ↓
07d：研究完了条件を自動検査
```

### 版数と更新回数

各初期プロンプトについて、4グループ×2周の**8版を評価**する。各epochの最後には次版を作らないため、Meta-optimizerによる更新は**6回**である。

### Testロック

Test 30件は、プロンプトの作成・更新・選択には使用しない。Validationで最良版を固定した後にのみ評価する。

### Query-blind Rewriter

Rewriterへ渡すもの：

- 商品名
- 商品説明
- リライトプロンプト

評価クエリは渡さない。リライト後は対象listing全体を置き換え、固定した他9商品と再ランキングする。

### 長文・短文の比較

最適化済みTestでは、同じ`prompt_id × Test intent`についてリライト文章を1回だけ生成する。その同じ文章を、長文クエリと短文クエリの両方で順位付けする。

したがって、長文と短文の差にRewriterの乱数差を混ぜない。完了時には`rewrite_job_id`と`rewritten_description`の完全一致を`07d`が検査する。

---

## 5. モデル構成

### 候補選定

- OpenAI GPT-5 mini
- `reasoning.effort = minimal`
- `max_output_tokens = 200`
- 正式80件の前に1件だけ接続Smokeを行う

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
  - `reasoning.effort = minimal`
  - `max_output_tokens = 1000`
- Model F：Google Gemini 3.5 Flash-Lite
  - 初期プロンプト・長文Test
  - 最適化プロンプト・長文Test
  - `temperature`は送信しない
- Model G：Anthropic Claude Sonnet 5
  - 最適化プロンプト・長文Testのみ
  - OpenAI＋Gemini完了後の任意追加評価

条件が完全には同じでないため、全モデル・全条件を一つの平均へ混ぜない。主結果はGPT-5、共有長文条件はGPT-5とGemini、Claudeは追加転移確認として報告する。

### Re-ranker System Promptの扱い

- OpenAI：先行研究コードのモデルファミリー別System Prompt
- Gemini：短いGemini専用Re-ranker Prompt
- Claude：短いClaude専用Re-ranker Prompt

Gemini・Claudeの短縮Promptは、費用制約による明示的な差分である。「全Providerで先行研究のSystem Promptを完全再現した」とは記載しない。

---

## 6. 2026年8月6日の安全修正

### 6.1 長文・短文で同一リライトを共有

旧コードは最適化長文と最適化短文でRewriterを別々に呼んでいた。`05i`では1回だけ生成し、両クエリ形式へ再利用する。

### 6.2 Parser失敗時も費用を記録

API応答取得後、JSON解析より先にusageと費用を確定する。応答に課金された後でParserが失敗しても、失敗試行の費用をJSONLへ記録する。

### 6.3 Gemini 3.5のsampling引数を停止

`temperature = null`、`supports_temperature = false`とし、Gemini 3.5 Flash-Liteへtemperatureを送らない。

### 6.4 GPT-5の推論設定を明示

GPT-5のRe-rankerには`reasoning.effort = minimal`を指定し、可視JSONが出力上限に圧迫されるリスクを下げる。

### 6.5 正式候補選定前の接続Smoke

`05j`は実データを使わず、Rewriter、Meta-optimizer、全Training Re-ranker、全Held-out Re-rankerの接続、Parser、usage、費用を確認する。候補選定も正式80件の前に1件だけ別フォルダで実行する。

### 6.6 統計の補強

`06c`で次を追加する。

- Test平均順位改善量の95%ブートストラップ信頼区間
- 初期版対最適化版の平均差の95%ブートストラップ信頼区間
- 対応ありWilcoxon符号付順位検定
- 全比較に対するHolm補正
- Re-ranker内の15比較に対するHolm補正

---

## 7. 予算設計

| Provider | 本体上限 | 主な役割 |
|---|---:|---|
| OpenAI | 98 USD | Rewriter、Meta-optimizer、主学習評価、GPT-5 Test |
| Google Gemini | 15 USD | 第2学習評価、長文Held-out Test |
| Anthropic Claude | 8 USD | 最適化済み長文Testの任意追加評価 |
| 本体合計 | 121 USD | Claude追加時の最大構成 |

OpenAIアカウント100 USDのうち本体ランナーは98 USDで停止する。残り2 USDは候補選定、`text-embedding-3-large`による収束分析、最後の1リクエストの小さな超過に予約する。

- 新規API呼び出しの直前に総額とProvider別hard stopを検査
- 成功済みジョブはJSONLキャッシュから再利用
- API応答後にParserが失敗した試行も費用へ加算
- 接続Smokeのhard stopは3 USD

---

## 8. 正式実行経路

Python本体を個別に実行せず、原則としてPowerShell入口を使用する。

### 第一段階：OpenAI＋Gemini

```powershell
# 0円。構文、設定、ローカルデータ、APIなしセルフチェック
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate

# 少額。候補1件、全モデル接続、正式工程Smoke
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Smoke

# 正式実験。Smoke合格後に実行
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Full -SkipSmoke
```

内部経路：

```text
04d 候補選定安全ラッパー
  ↓
07e APIなし安全セルフチェック
  ↓
05j 全モデル接続Smoke
  ↓
05i 最終安全実行
  ↓
06c 最終統計分析
  ↓
07d 最終完了チェック
```

### 任意追加：Claude

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Full -SkipSmoke
```

同じ出力フォルダを再利用し、成功済みOpenAI・Geminiジョブ、固定プロンプト、共有リライトをキャッシュから読み、Claudeの不足ジョブだけを追加する。

---

## 9. 実行を止める条件

次のいずれかがNGなら、正式Fullへ進まない。

- `uv sync`失敗
- Python構文チェック失敗
- `07e`セルフチェック失敗
- Dense Retrieval入力検証失敗
- APIキー不足
- GPT-5 mini候補1件Smoke失敗
- `05j`接続Smoke失敗
- 正式工程SmokeのParserまたは構造検査失敗
- Provider別費用が想定を大きく外れる
- モデルIDが利用不可

---

## 10. 分析出力

正式分析：

```text
日本語版コード/06c_TOEIC最終統計分析.py
```

主な出力：

```text
01_test_summary.csv
02_initial_vs_optimized_paired.csv
03_prompt_convergence_trajectory.csv
03b_prompt_trajectory.csv
04_prompt_feature_manual_review.xlsx
06_results_summary.json
07_initial_vs_optimized.png
08_long_vs_short.png
09_prompt_convergence.png
10_results_review.xlsx
11_embedding_cache.jsonl
12_statistical_inference.json
```

最終完了検査：

```text
日本語版コード/07d_TOEIC最終完了チェック.py
```

`07d`は、80件・40/10/30、15×8版、Test件数、Provider別条件、予算、分析ファイルに加え、次も検査する。

- 接続Smoke合格
- 最適化長文と短文のリライトID・文章一致
- Parser失敗費用記録パッチ
- GPT-5 minimal reasoning
- 95%信頼区間
- Holm補正

---

## 11. ポスター用主要表

少なくとも次の列を出す。

| 評価モデル | クエリ条件 | 初期版平均順位改善 | 最適化版平均順位改善 | 差 | 95% CI | Wilcoxon p値 | Holm補正p値 | 上昇率 | 不変率 | 低下率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|

- GPT-5：長文の初期対最適化、短文転移
- Gemini：共有長文条件
- Claude：最適化済み長文の追加転移結果として別枠

Claudeには初期版の同条件がないため、初期対最適化の公平比較表へ混ぜない。

---

## 12. 現在地

### 完了

- 商品クレンジングと270商品固定
- 購入意図80件、長文・短文クエリ
- Dense Retrieval 2,400行
- Dense入力の完全一致検証コード
- 初期プロンプト15種と共通Prompt
- 最終安全ランナー`05i`
- 接続Smoke`05j`
- 統計補強`06c`
- 最終完了検査`07d`
- APIなしセルフチェック`07e`
- PowerShell実行経路の更新

### 未実行

- 2026年8月6日版コードによるローカル`Validate`
- 有料の候補1件Smoke
- 有料の全モデル接続Smoke
- 候補80件の正式選定
- 正式工程Smoke
- Full実験
- 埋め込みAPI分析
- 10特徴の人手評価

**次の操作は、有料実験ではなくローカルの`-Mode Validate`である。Validateが全項目合格するまでSmokeへ進まない。**
