# E-GEO 日本語TOEIC縮小再現実験

E-GEO v2の中核である、**複数Re-rankerの順位結果を用いたプロンプトのメタ最適化**を、日本語のTOEIC教材領域で小規模に再現する研究です。

対象ブランチ：`ja-toeic-prototype`  
最終更新：2026年8月5日

> **E-GEO v2のscaled-down replication＋日本語・TOEIC教材・短文検索への拡張**

## 現在の状態

```text
商品・購入意図・Dense Retrieval          完了
先行研究準拠ランナー                     実装済み
OpenAI・Gemini・Claude接続基盤            実装済み
Provider別予算停止・キャッシュ再開       実装済み
分析・完了チェック                       実装済み
APIを呼ばないValidate                    確認済み
正式な有料API実験                        未開始
A0ポスター                               結果差し替え前提で先行作成
```

正式な有料API実験はまだ開始していません。現在は、ポスターの背景・方法・分析枠を先に完成させ、結果取得後に日本語版Table 6、グラフ、統計、結論だけを差し替える方針です。

## 研究の中心

```text
15種類の初期リライトプロンプト
        ↓
TrainでGPT-4.1・Geminiの順位改善量を測定
        ↓
Train履歴だけを匿名化してMeta-optimizerへ追加
        ↓
GPT-4.1が次のプロンプトを生成
        ↓
Validation平均が最高の版を固定
        ↓
固定後にGPT-5・Gemini・ClaudeでHeld-out Test
        ↓
初期対最適化、長文対短文、モデル別、収束を分析
```

**Validationは版選択専用で、Meta-optimizerへ渡しません。Testはプロンプト固定後まで使用しません。**

## データ

- 楽天ブックスで収集：300商品
- クレンジング後：271商品
- 最終商品プール：270商品
- 購入意図：80件
- Train 40／Validation 10／Test 30
- 主実験：長文購入相談
- 追加実験：Googleサジェスト由来の短文検索
- Dense Retrieval：80×30＝2,400行
- Dense入力と正本データの不一致：0件

購入意図の正本：

```text
日本語版データ/TOEIC/03_購入意図/toeic_query_intents_review.xlsx
```

CSV・Excel・JSONL・API結果は原則GitHubへ置かず、ローカルで管理します。

## 候補商品の作成

```text
270商品
  ↓
多言語Sentence TransformerによるDense Retrieval
  ↓
コサイン類似度上位30件
  ↓
GPT-5 miniによる関連商品10件の選定
  ↓
seed 42で対象商品1件を固定
```

埋め込みモデル：

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

カテゴリ絞り込み、タイトル独自加重、目標得点加点は使用しません。

## 正式モデル構成

### 候補選定

```text
OpenAI GPT-5 mini
```

### Train・Validation

```text
Rewriter           OpenAI GPT-4.1
Meta-optimizer     OpenAI GPT-4.1
Model A            OpenAI GPT-4.1
Model B            Google Gemini 3.1 Flash-Lite
```

### 固定後のHeld-out Test

```text
Model E  OpenAI GPT-5
         初期長文・最適化長文・最適化短文

Model F  Google Gemini 3.5 Flash-Lite
         初期長文・最適化長文

Model G  Anthropic Claude Sonnet 5
         最適化長文のみ。後日追加可能
```

GPT-5とGeminiの共有長文条件で公平比較し、短文転移はGPT-5を主結果、Claudeは追加のクロスモデル転移確認として報告します。

## 先行研究との対応

### 維持する中核条件

- 候補10商品をGEO実験前に固定
- 対象商品をseed 42で固定
- Rewriterはquery-blind
- 順位改善量：元順位 − リライト後順位
- 複数エンジンのTrain結果でプロンプトを改善
- エンジン名をModel A／Bとして匿名化
- Validationは最良版選択専用
- Testはプロンプト固定後まで未使用
- 初期版と最適化版を同じTestで比較
- 全評価版の意味的収束を分析

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

各epochの最後には次版を作らないため、8版を評価しても実際の更新は6回です。

## 予算

| Provider | 本体上限 | 役割 |
|---|---:|---|
| OpenAI | 98 USD | Rewriter、Meta-optimizer、主学習評価、GPT-5 Test |
| Gemini | 15 USD | 第2学習評価、長文Held-out Test |
| Claude | 8 USD | 最適化済み長文の追加評価 |
| 最大合計 | 121 USD | Claude追加時 |

OpenAIアカウントの100 USDのうち、本体ランナーを98 USDで止め、2 USDを候補選定、埋め込み収束分析、最後の1リクエストに予約します。

- OpenAI＋Gemini段階の総hard stop：113 USD
- Claude追加後の総hard stop：121 USD
- Provider別hard stopあり
- 成功済みAPIジョブはJSONLキャッシュから再利用

詳細：

```text
日本語版ドキュメント/TOEIC_API費用配分_2026-08-05.md
```

## 正式実行経路

### 第一段階：OpenAI＋Gemini

```text
tools/実行_TOEIC研究_OpenAI_Gemini.ps1
```

```powershell
# API呼び出しなし
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate

# 少数件の有料接続・形式・費用確認
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Smoke

# 正式実験
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Full
```

### 後日：Claude追加

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

同じ出力フォルダを使用し、OpenAI・Geminiの成功済みジョブと固定済みプロンプトを再利用してClaudeの不足分だけを実行します。

必要なAPIキー：

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

OpenAI＋Gemini先行実行では、最初の2キーだけを使用します。

## 主要コード

```text
日本語版コード/
├─ 01_楽天TOEIC商品データをクレンジング.py
├─ 02_実験用TOEIC商品プールを作成.py
├─ 03_TOEIC購入意図テンプレートを作成.py
├─ 04_TOEIC候補商品を割り当て.py
├─ 04b_TOEIC候補10商品を選ぶ.py
├─ 04c_TOEIC候補検索入力を検証.py
├─ 05a_TOEICメタ最適化実験を計画.py
├─ 05f_TOEIC先行研究準拠_OpenAI_Gemini実験.py
├─ 05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py
├─ 05h_TOEIC費用配分安全実行.py
├─ 06b_TOEIC先行研究準拠結果分析.py
└─ 07b_TOEIC先行研究準拠完了チェック.py
```

正式入口から内部の`05e／05d／05c`共通処理を呼びます。内部本体は通常、直接実行しません。

## 正式分析

分析コード：

```text
日本語版コード/06b_TOEIC先行研究準拠結果分析.py
```

- 初期版 vs 最適化版
- Wilcoxon対応検定
- 上昇率・不変率・低下率
- 長文Test vs 短文Test
- モデル別比較
- `text-embedding-3-large`による収束分析
- 10特徴の0／1／2人手評価

完了検査：

```text
日本語版コード/07b_TOEIC先行研究準拠完了チェック.py
```

数値・統計・埋め込みが完成した状態と、10特徴の人手評価まで完成した状態を分けて判定します。

## ポスター用日本語版Table 6

結果確定後、次の形式で出力します。

| 評価モデル | クエリ条件 | 初期版平均順位改善 | 最適化版平均順位改善 | 差 | Wilcoxon p値 | 上昇率 | 不変率 | 低下率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|

Claudeは最適化済み長文だけの追加評価なので、初期対最適化の公平比較表とは分けます。

## 次に読むファイル

1. `00_最初に読む_日本語版研究の全ファイル案内.md`
2. `日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md`
3. `日本語版コード/00_最初に読む_全コードの役割.md`
4. `日本語版ドキュメント/TOEIC_API費用と完了見込み.md`
5. `日本語版ドキュメント/TOEIC_API費用配分_2026-08-05.md`

## Pull後の最短確認

```powershell
git switch ja-toeic-prototype
git pull origin ja-toeic-prototype
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate
```
