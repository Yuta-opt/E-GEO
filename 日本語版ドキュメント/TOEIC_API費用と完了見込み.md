# TOEIC実験：API費用と完了見込み

最終更新：2026年8月5日  
対象ブランチ：`ja-toeic-prototype`  
状態：**OpenAI＋Gemini先行実行とClaude後日追加のランナー実装済み。有料APIは未実行**

この文書は、APIキー設定後に研究の数値結果が完成するまでの時間、現行モデル構成、概算費用、停止条件を記録する。

> 実額と所要時間は、商品説明長、Meta-optimizerへ渡す履歴量、Geminiのthinking tokens、再試行、レート制限で変動する。  
> 正式Train前にSmokeを行い、実測トークン数と1件当たり時間から再推定する。

---

## 1. 現在の結論

### 先に実行する構成

```text
OpenAI＋Google Gemini
```

### 後日追加できる構成

```text
Anthropic Claudeの最適化済み長文Testだけを追加
```

### 予算上限

| Provider | 本体上限 | 備考 |
|---|---:|---|
| OpenAI | 98 USD | アカウント100 USDのうち2 USDを本体外へ予約 |
| Google Gemini | 15 USD | Flash-Lite系列を使用 |
| Anthropic Claude | 8 USD | 最適化済み長文だけ |
| OpenAI＋Gemini | 113 USD | 第一段階の総hard stop |
| 3社合計 | 121 USD | Claude追加後の総hard stop |

OpenAIの予約2 USDは、GPT-5 miniによる候補10件選定、`text-embedding-3-large`による収束分析、最後の1リクエストによる小さな超過に使用する。

---

## 2. 研究完了の定義

候補30件から10件を選ぶだけでは研究全体は完了しない。

```text
候補30件→10件選定
        ↓
対象商品をseed 42で固定
        ↓
15初期プロンプトをTrainで評価
        ↓
GPT-4.1・Geminiの履歴でMeta-optimization
        ↓
Validation最高版を固定
        ↓
GPT-5・GeminiでHeld-out Test
        ↓
必要ならClaudeを追加
        ↓
統計・収束・人手特徴評価
        ↓
日本語版Table 6とポスターへ反映
```

本資料では次を区別する。

- **数値結果完成**：Test結果、統計、埋め込み収束、図表、完了チェックがそろう
- **全分析完成**：10特徴の人手評価まで終わる
- **発表可能状態**：ポスターの表・グラフ・結論を実結果へ差し替える

---

## 3. APIキー設定後の所要時間

| 工程 | 目安 | API |
|---|---:|---|
| `.env`設定、Validate | 15〜30分 | なし |
| 候補30件→10件を80購入意図で選定 | 30分〜2時間 | OpenAI |
| OpenAI＋Gemini Smoke | 1〜4時間 | あり |
| 正式Train／Validation／GPT-5・Gemini Test | 6〜18時間 | あり |
| レート制限・再試行を含む安全幅 | 最大1〜2日 | あり |
| 自動分析・完了チェック | 1〜3時間 | 埋め込みのみ一部API |
| 10特徴の人手評価 | 2〜6時間 | なし |
| ポスター結果差し替え | 2〜4時間 | なし |
| Claude追加評価 | 1〜4時間 | Anthropic |

現時点の目安：

```text
OpenAI＋Geminiの数値結果：最短半日、通常1〜2日
人手評価を含む全分析：1〜3日
ポスター反映まで：2〜3日
```

これは処理時間の見積りであり、予算上限内で全ジョブが完了する保証ではない。Smoke後に総費用を再計算し、Full開始前にモデル構成を固定する。

---

## 4. 現行モデル構成

### 候補選定

```text
OpenAI GPT-5 mini
```

### Train・Validation

```text
Rewriter           OpenAI GPT-4.1
Meta-optimizer     OpenAI GPT-4.1
Training Model A   OpenAI GPT-4.1
Training Model B   Google Gemini 3.1 Flash-Lite
```

### Held-out Test

```text
Model E  OpenAI GPT-5
         初期長文・最適化長文・最適化短文

Model F  Google Gemini 3.5 Flash-Lite
         初期長文・最適化長文

Model G  Anthropic Claude Sonnet 5
         最適化長文のみ。後日追加
```

GeminiとClaudeは費用を抑えるため、Test条件をGPT-5より縮小している。3モデルの全結果を単一平均へ混ぜず、共有条件を分けて報告する。

---

## 5. API呼び出し規模

正式実験は約1万回規模のAPIジョブを含む。実際の新規呼び出し数は、次により変わる。

- Original順位のキャッシュ共有
- 同一リライトの再利用
- GPT-5・Gemini・Claudeで実行するTest条件の違い
- 再試行回数
- 途中停止後のJSONLキャッシュ再開

主要な処理：

| 処理 | 規模の考え方 |
|---|---|
| 候補10件選定 | 80購入意図 |
| Rewriter | 15プロンプト×8版×対象Train／Validation／Test条件 |
| Training Re-ranking | GPT-4.1とGeminiでTrain評価 |
| Validation | 各版をValidation 10件で選択 |
| Held-out Test | GPT-5全条件、Gemini長文、Claude最適化長文 |
| Meta-optimizer | 15プロンプト×6更新 |

正確な予定件数は、実行前に`05a_TOEICメタ最適化実験を計画.py`とValidate出力で確認する。

---

## 6. 費用管理ルール

### OpenAI

- アカウント利用可能額：100 USD
- 本体ランナー警告：50、75、90、96 USD
- 本体ランナーhard stop：98 USD
- 本体外予約：2 USD

### Google

- 警告：5、10、13 USD
- hard stop：15 USD

### Anthropic

- 警告：3、5、7 USD
- hard stop：8 USD

### 共通

- 新しいAPI呼び出しの直前にhard stopを検査する
- 1回のリクエスト分だけ上限をわずかに超える可能性がある
- 成功応答は保存直後からキャッシュとして再利用する
- 再試行は最大3回
- Provider別費用を分離して集計する
- Smoke結果を正式結果へ混ぜない
- TestはValidationでプロンプトを固定した後にのみ実行する

費用記録：

```text
01_llm_cache.jsonl
05_cost_ledger.csv
05b_provider_cost_summary.json
```

---

## 7. 実行経路

### APIを呼ばない確認

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate
```

### 少数件の有料確認

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Smoke
```

Smokeで確認するもの：

1. APIキーとモデル利用可否
2. 3種類の出力JSON形式
3. 1件当たり入力・出力トークン
4. 1件当たり時間
5. Provider別費用
6. キャッシュ再開
7. Testロック

### 正式実験

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Full
```

### Claude追加

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Full
```

Claude追加時は同じ出力フォルダを使う。OpenAI・Geminiの成功済みジョブと固定済みプロンプトを再利用し、Claudeの不足ジョブだけを新規実行する。

---

## 8. Full開始の判断基準

Smoke後、次を満たす場合だけFullを開始する。

- 候補10件と対象商品が固定済み
- GPT-4.1・GPT-5・GeminiのモデルIDが利用可能
- JSON形式エラーが再試行内で収まる
- OpenAI本体98 USD、Gemini15 USD以内へ収まる見込み
- TestロックとValidation分離が確認できる
- 予定件数と出力先が正しい
- ポスターの分析表と必要な出力列が確定している

Train開始後、結果を見てモデル、データ分割、候補集合、対象商品を変更しない。変更する場合はpilotとして分離し、正式実験を別出力フォルダで最初から行う。

---

## 9. ポスター先行運用

正式APIをすぐ実行しない場合でも、次は先に完成できる。

- 背景、目的、研究問い
- データ作成
- Train／Validation／Test分割
- 候補固定
- 15プロンプトとメタ最適化
- モデル構成
- 評価指標とWilcoxon検定
- 日本語版Table 6の枠
- 収束グラフの枠
- 限界と今後の展望

API結果後に差し替えるもの：

- 初期版・最適化版の平均順位改善
- p値
- 上昇率・不変率・低下率
- モデル別結果
- 長文・短文差
- 収束指標
- 10特徴評価
- 最終結論

---

## 10. 現在地

```text
商品・クエリ・Dense Retrieval          完了
Dense入力完全一致検証                  完了
候補30件→10件のコード・計画            完了
OpenAI＋Gemini先行ランナー              実装済み・未実行
Claude後日追加ランナー                  実装済み・未実行
Provider別予算停止・キャッシュ          実装済み
分析・完了チェック                      実装済み・未実行
APIを呼ばないValidate                   確認済み
正式な有料API呼び出し                   0回
ポスター                                結果差し替え前提で先行作成
```

詳細な費用配分は次を正本とする。

```text
日本語版ドキュメント/TOEIC_API費用配分_2026-08-05.md
```
