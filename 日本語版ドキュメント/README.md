# 日本語版ドキュメント

E-GEO日本語TOEIC縮小再現実験の、現在採用している設計・費用・実行手順・根拠を保存します。

最終更新：2026年8月5日  
対象ブランチ：`ja-toeic-prototype`

## 最初に読む順番

1. [`../README_日本語.md`](../README_日本語.md)
2. [`TOEIC実験_現行設計と実施記録.md`](TOEIC実験_現行設計と実施記録.md)
3. [`TOEIC_API費用と完了見込み.md`](TOEIC_API費用と完了見込み.md)
4. [`TOEIC_API費用配分_2026-08-05.md`](TOEIC_API費用配分_2026-08-05.md)
5. [`TOEIC_API実行経路_OpenAI単一と3社版.md`](TOEIC_API実行経路_OpenAI単一と3社版.md)
6. [`先行研究/E-GEO論文要約_研究対応.md`](先行研究/E-GEO論文要約_研究対応.md)

## 正本

### [`TOEIC実験_現行設計と実施記録.md`](TOEIC実験_現行設計と実施記録.md)

現行設計・実装状況・運用判断の最重要正本です。

- 15種類の初期プロンプト
- Train 40／Validation 10／Test 30
- query-blind Rewriter
- GPT-4.1とGeminiによるTrain
- Validation選択とTestロック
- GPT-5・Gemini・Claudeの役割
- 日本語版Table 6
- ポスター先行方針
- 再開手順

### [`TOEIC_API費用と完了見込み.md`](TOEIC_API費用と完了見込み.md)

APIキー投入後の所要時間、SmokeからFull開始までの判断、数値結果完成・全分析完成・ポスター反映の違いを記録します。

### [`TOEIC_API費用配分_2026-08-05.md`](TOEIC_API費用配分_2026-08-05.md)

Provider別予算とモデルごとのTest条件の正本です。

```text
OpenAI本体        98 USD
Gemini            15 USD
Claude             8 USD
最大本体合計     121 USD
```

### [`TOEIC_API実行経路_OpenAI単一と3社版.md`](TOEIC_API実行経路_OpenAI単一と3社版.md)

PowerShell入口、内部Python経路、必要なAPIキー、Validate／Smoke／Fullの違いを説明します。

最新の正式入口：

```text
tools/実行_TOEIC研究_OpenAI_Gemini.ps1
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

### [`TOEIC_OpenAI単一キー自動実行設計.md`](TOEIC_OpenAI単一キー自動実行設計.md)

OpenAI単一キー版の補助設計です。比較・障害切り分け用であり、正式な提供元横断結果には使用しません。

### [`TOEIC購入意図クエリ作成記録.md`](TOEIC購入意図クエリ作成記録.md)

Googleサジェスト由来の短文と、商品から独立して作成した長文購入相談の作成過程を記録します。

### [`TOEIC先行研究準拠_2026-08-05修正記録.md`](TOEIC先行研究準拠_2026-08-05修正記録.md)

先行研究との照合で修正したValidation漏洩、モデル別System Prompt、Rewriter入力、収束分析、10特徴評価を記録します。

### [`先行研究/`](先行研究/)

E-GEO v2の原論文、要約、実験条件との対応資料を保存します。

## 文書間で矛盾した場合

次の順で優先します。

1. `TOEIC実験_現行設計と実施記録.md`
2. `TOEIC_API費用配分_2026-08-05.md`
3. `TOEIC_API費用と完了見込み.md`
4. `../README_日本語.md`
5. その他の補助文書

モデルID・単価・停止額など実行値については、実際に指定するJSON設定を機械可読正本とします。

## 現在の状態

```text
データ・Dense Retrieval                完了
実験ランナー                           実装済み
予算停止・キャッシュ                   実装済み
分析・完了チェック                     実装済み
Validate                               確認済み
正式な有料API実験                      未開始
ポスター                               結果差し替え前提で先行作成
```

## 現在採用していない旧設計

- 単一の最良プロンプトを英語版・日本語版で比較する設計
- `Original／EN-Zero／JA-Zero／JA-Adapted`比較
- TF-IDF・カテゴリ固定・得点帯加点で候補10件を直接選ぶ方式
- 商品を先に固定してから購入意図を作る方式
- Validation結果をMeta-optimizerへ渡す方式
- 全モデルへ同じ短いSystem Promptを使う方式

Git履歴には変更前の内容が残りますが、現行作業では使用しません。
