# TOEIC実験：API実行経路の分離

最終更新：2026年8月2日

本研究では、API実験を次の2経路へ明確に分離する。異なる経路の設定、APIログ、分析結果を同じフォルダへ混ぜない。

## 1. OpenAI単一キー版

### 実行入口

```text
日本語版コード/05c_TOEIC_OpenAI単一キー実験を自動実行.py
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

### 設定

```text
日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json
```

### 必要なAPIキー

```env
OPENAI_API_KEY=
```

### モデル役割

```text
候補10件選定        OpenAI GPT-5 mini
Rewriter            OpenAI GPT-4.1
Meta-optimizer      OpenAI GPT-4.1
学習Model A         OpenAI GPT-4.1
学習Model B         OpenAI GPT-4.1 mini
評価専用Model E     OpenAI GPT-5
```

### 出力

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/
```

### 位置づけ

実装とAPIキー管理が簡単である。一方、学習モデルと評価モデルがすべてOpenAI提供であるため、提供元をまたいだ一般化検証はできない。この制約を発表時に明記する。

---

## 2. OpenAI・Gemini・Claude版

### 実行入口

```text
日本語版コード/05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

### 設定

```text
日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
```

### 必要なAPIキー

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

### モデル役割

```text
候補10件選定        OpenAI GPT-5 mini
Rewriter            OpenAI GPT-4.1
Meta-optimizer      OpenAI GPT-4.1
学習Model A         OpenAI GPT-4.1
学習Model B         Google Gemini 3 Flash Preview
評価専用Model E     Anthropic Claude Sonnet 4.5
```

### 出力

```text
日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
日本語版データ/TOEIC/07_本番前チェック/03_OpenAI_Gemini_Claude研究完了チェック.json
```

### 位置づけ

正式実験の第一候補である。先行研究の4学習Re-ranker・2評価専用Re-rankerから、2学習・1評価へ縮小しているが、OpenAI・Google・Anthropicを分離することで、OpenAI単一キー版よりも特定提供元への過適合を検査しやすい。

Gemini 3 FlashはPreviewモデルであるため、正式Train開始日に利用可能性を再確認する。Claude Sonnet 4.5は固定版`claude-sonnet-4-5-20250929`を使用する。

---

## 3. 実行モード

両経路とも3モードを持つ。

### Validate

- API呼び出し0回
- Python依存関係同期
- 構文チェック
- Dense入力検証
- 候補選定計画
- メタ最適化計画
- モデル設定確認

### Smoke

- 候補10件を80購入意図について確定
- 1初期プロンプト
- Train 2件
- Validation 1件
- Test 1件
- Rewriter、複数学習Re-ranker、Meta-optimizer、評価専用Re-rankerを実際に接続
- 分析と完了チェックまで実行

3社版のSmokeでは、OpenAI、Gemini、Claudeのすべてを実際に1回以上使用する。

### Full

- 15初期プロンプト
- 2 epochs × 4 batches
- Train 40件
- Validation 10件
- Test 30件
- 長文初期版、長文最適化版、短文最適化版
- 統計、収束分析、特徴分析、図表、完了チェック

---

## 4. 正式採用ルール

```text
1. Validateを通す
2. APIキーを.envへ保存する
3. Smokeを実行する
4. 3社の出力形式と実測費用を確認する
5. モデル構成を固定する
6. Fullを開始する
```

Train開始後に結果を見てモデル構成を変更しない。変更が必要な場合、先行実行をpilotとして分離し、正式実験は新しい出力フォルダで最初から実行する。

---

## 5. キャッシュと予算

- 成功済みAPIジョブはJSONLキャッシュから再利用する
- 同じ入力・モデル・工程の再実行による二重課金を避ける
- OpenAI、Google、Anthropicの費用を合算する
- 20ドル、50ドル、80ドルで警告する
- 既定100ドルで停止する
- Testはプロンプト固定後にのみ実行する

実際のAPIキーは`.env`だけへ保存し、GitHub、チャット、スクリーンショットへ載せない。
