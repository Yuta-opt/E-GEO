# TOEIC実験：API費用と完了見込み

最終更新：2026年8月2日  
状態：**OpenAI単一キー版とOpenAI・Gemini・Claude版の自動ランナー実装済み。有料APIは未実行**

この文書は、APIキー設定後に研究の数値結果が完成するまでの時間、モデル構成別の概算費用、予算停止ルールを記録する。

> 実額は、商品説明の長さ、Geminiのthinking tokens、Meta-optimizerへ渡す履歴量、再試行、レート制限で変動する。  
> 正式Train前にSmokeを実行し、実測トークン数から再計算する。

---

## 1. 研究完了の定義

候補30件から10件を選ぶだけでは研究全体は完了しない。

```text
候補30件→10件選定
        ↓
対象商品をseed 42で固定
        ↓
15初期プロンプトをTrainで評価
        ↓
複数Re-rankerの履歴からMeta-optimizerで更新
        ↓
Validation最高版を固定
        ↓
評価専用Re-rankerでTest長文を評価
        ↓
固定済みプロンプトをTest短文で追加評価
        ↓
統計・収束分析・図表
```

本資料では次を区別する。

- **数値結果完成**：Test結果、統計、収束分析、図表、完了チェックがそろう
- **発表可能状態**：数値結果を確認し、解釈とポスター本文へ反映する

---

## 2. APIキー設定後の所要時間

以前の見積りにはランナー実装1〜2日を含めていたが、現在は実装済みである。

| 工程 | 目安 |
|---|---:|
| `.env`設定、Validate | 15〜30分 |
| 候補30件→10件を80購入意図で選定 | 30分〜2時間 |
| 3社Smoke、形式・実測費用の確認 | 1〜4時間 |
| 15プロンプトの正式Train／Validation／Test | 6〜18時間。レート制限次第で1〜2日 |
| 自動分析・完了チェック | 1〜3時間 |
| 人間による解釈確認・ポスター反映 | 半日〜1日 |

現時点の目安：

```text
数値結果完成：1〜3日
発表可能状態：2〜4日
最短ケース：1日程度
```

API障害、利用上限、出力形式エラーが続いた場合は延びる。

---

## 3. API呼び出し規模

`05a_TOEICメタ最適化実験を計画.py`の設計値：

| 構成 | 学習Re-ranker | 評価専用Re-ranker | API予定回数 |
|---|---:|---:|---:|
| Smoke | 3社接続を少数件で確認 | 1 | 数十回 |
| 正式な最小研究構成 | 2 | 1 | 約9,780回 |
| 先行研究に近い役割構成 | 4 | 2 | 約16,090回 |

現在実装した正式候補は、2学習Re-ranker＋1評価専用Re-rankerの約9,780回である。

---

## 4. 概算に使用するトークン仮定

| 処理 | 入力 | 出力 |
|---|---:|---:|
| 商品説明リライト | 約1,000 | 約700 |
| 候補10商品のRe-ranking | 約4,500 | 約120 |
| Meta-optimizer | 約2,500 | 約800 |
| 候補30件→10件選定 | 約1,000 | 約50 |

```text
費用 = 入力トークン ÷ 1,000,000 × 入力単価
     + 出力トークン ÷ 1,000,000 × 出力単価
```

日本語説明文とthinking tokensのばらつきを考慮し、最終見積りには広めの幅を持たせる。

---

## 5. 使用モデルと標準単価

単位は100万トークン当たりの米ドル。2026年8月2日時点の標準料金を設定ファイルへ記録する。

| 提供元 | モデル | 入力 | 出力 |
|---|---|---:|---:|
| OpenAI | GPT-4.1 | $2.00 | $8.00 |
| OpenAI | GPT-4.1 mini | $0.40 | $1.60 |
| OpenAI | GPT-5 | $1.25 | $10.00 |
| OpenAI | GPT-5 mini | $0.25 | $2.00 |
| Google | Gemini 3 Flash Preview | $0.50 | $3.00（thinkingを含む） |
| Anthropic | Claude Sonnet 4.5 | $3.00 | $15.00 |
| Anthropic | Claude Haiku 4.5 | $1.00 | $5.00 |

公式資料：

- OpenAIモデル・スナップショット：<https://platform.openai.com/docs/models>
- Geminiモデル：<https://ai.google.dev/gemini-api/docs/models>
- Gemini料金：<https://ai.google.dev/gemini-api/docs/pricing>
- Claude Sonnet 4.5：<https://www.anthropic.com/claude/sonnet>

---

## 6. 実装した2つの経路

### 6.1 OpenAI単一キー版

```text
候補選定            GPT-5 mini
Rewriter            GPT-4.1
Meta-optimizer      GPT-4.1
学習Model A         GPT-4.1
学習Model B         GPT-4.1 mini
評価専用Model E     GPT-5
```

概算：

```text
中心値：約$65
想定範囲：約$45〜$95
```

長所：キー管理と障害対応が簡単。  
短所：全モデルがOpenAI提供であり、提供元をまたぐ一般化検証が弱い。

設定：

```text
日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json
```

---

### 6.2 OpenAI・Gemini・Claude版

```text
候補選定            OpenAI GPT-5 mini
Rewriter            OpenAI GPT-4.1
Meta-optimizer      OpenAI GPT-4.1
学習Model A         OpenAI GPT-4.1
学習Model B         Google Gemini 3 Flash Preview
評価専用Model E     Anthropic Claude Sonnet 4.5
```

概算：

```text
中心値：約$80
想定範囲：約$55〜$120
運用hard stop：$100
```

中心値の概算内訳：

| 工程 | 中心値 |
|---|---:|
| GPT-4.1によるリライト | 約$25 |
| GPT-4.1 Meta-optimizer | 約$1 |
| GPT-4.1 学習Re-ranking | 約$24 |
| Gemini学習Re-ranking | 約$6 |
| Claude Test評価 | 約$22 |
| 候補10件選定 | $1未満 |

この3社版を正式実験の第一候補とする。OpenAI単一版より高いが、学習時にGoogle、評価時にAnthropicを使い、特定提供元への過適合を検査できる。

ただし、上振れすると$100を超える可能性があるため、Smoke実測値から総額を再計算する。

設定：

```text
日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
```

---

### 6.3 予算優先の代替案

3社Smoke後に$100超過が見込まれる場合：

```text
Rewriter            GPT-4.1 mini
Meta-optimizer      GPT-4.1 mini
学習Model A         GPT-5 mini
学習Model B         Gemini Flash系の低価格モデル
評価専用Model E     Claude Haiku 4.5
```

概算：

```text
約$15〜$35
```

アルゴリズム上の中核は維持できるが、先行研究のGPT-4.1 Rewriter／Meta-optimizerから離れる。その場合は、計算予算による小型モデル構成であることを発表資料へ明記する。

---

## 7. 正式採用手順

```text
1. Validate：API呼び出し0回
2. 候補選定80件
3. OpenAI・Gemini・Claudeを含むSmoke
4. 各社の実測入力・出力トークンを確認
5. 約9,780回分へ外挿
6. $100以内なら3社版を固定
7. 超過見込みなら予算優先版へ変更
8. モデル固定後に正式Trainを開始
```

Train開始後、結果を見てモデルを変更しない。変更が必要な場合はpilotとして分離し、正式実験を新しい出力フォルダで最初から行う。

---

## 8. 予算管理ルール

- APIキーは`.env`だけへ保存する
- 3社の費用を合算する
- 成功済みジョブはJSONLキャッシュから再利用する
- 失敗時の再試行は最大3回
- 20ドル、50ドル、80ドルで警告する
- 既定100ドルで自動停止する
- TestはValidationでプロンプトを固定した後にのみ実行する
- Smoke結果を正式結果へ混ぜない

候補30件→10件の80回だけは通常$1未満を想定するが、実測値を必ず記録する。

---

## 9. 現在地

```text
商品・クエリ・Dense Retrieval       完了
Dense入力完全一致検証               完了
候補30件→10件のコード・計画         完了
OpenAI単一キー版ランナー            実装済み・未実行
OpenAI・Gemini・Claude版ランナー     実装済み・未実行
分析・完了チェック                   実装済み・未実行
有料API呼び出し                      0回
```
