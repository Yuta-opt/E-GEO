# E-GEO 日本語TOEIC縮小再現実験

このブランチは、E-GEO v2のメタ最適化を日本語TOEIC教材へ適用する研究用ブランチです。

- 対象ブランチ：`ja-toeic-prototype`
- 最終更新：2026年8月5日
- 詳細な日本語README：[`README_日本語.md`](README_日本語.md)
- 現行設計の正本：[`日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md`](日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md)

> 元の公開E-GEO実装は`main`ブランチを参照してください。このブランチでは、日本語TOEIC研究用のコード・設定・ドキュメントを追加しています。

## 現在地

```text
商品270件・購入意図80件・Dense Retrieval   完了
先行研究準拠ランナー                        実装済み
OpenAI・Gemini・Claude接続基盤               実装済み
Provider別予算停止・キャッシュ再開          実装済み
分析・完了チェック                          実装済み
APIを呼ばないValidate                       確認済み
正式な有料API実験                           未開始
A0ポスター                                  結果差し替え前提で先行作成
```

## 実験の概要

```text
15種類の初期プロンプト
  ↓
GPT-4.1とGeminiでTrain順位を評価
  ↓
Train履歴だけでプロンプトを更新
  ↓
Validationで最良版を固定
  ↓
GPT-5・Gemini・ClaudeでHeld-out Test
  ↓
初期版対最適化版、長文対短文、収束を分析
```

- Train／Validation／Test：40／10／30
- 各初期プロンプト：8版評価、6回更新
- RewriterとMeta-optimizer：GPT-4.1
- Training Re-ranker：GPT-4.1、Gemini 3.1 Flash-Lite
- Held-out Test：GPT-5、Gemini 3.5 Flash-Lite、Claude Sonnet 5

## Pull後の最短確認

```powershell
git switch ja-toeic-prototype
git pull origin ja-toeic-prototype
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini.ps1" -Mode Validate
```

`Validate`はAPIを呼びません。有料の`Smoke`と`Full`は、予算とAPIキーを確認してから実行します。

## 正式実行入口

### OpenAI＋Gemini

```text
tools/実行_TOEIC研究_OpenAI_Gemini.ps1
```

### Claudeを後日追加

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

## 予算

| Provider | 本体上限 |
|---|---:|
| OpenAI | 98 USD |
| Gemini | 15 USD |
| Claude | 8 USD |
| 最大合計 | 121 USD |

OpenAIアカウント100 USDのうち2 USDは、候補選定、埋め込み収束分析、最後の1リクエストに予約します。

## 最初に読む順番

1. [`README_日本語.md`](README_日本語.md)
2. [`00_最初に読む_日本語版研究の全ファイル案内.md`](00_最初に読む_日本語版研究の全ファイル案内.md)
3. [`日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md`](日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md)
4. [`日本語版ドキュメント/TOEIC_API費用と完了見込み.md`](日本語版ドキュメント/TOEIC_API費用と完了見込み.md)
5. [`日本語版コード/00_最初に読む_全コードの役割.md`](日本語版コード/00_最初に読む_全コードの役割.md)
