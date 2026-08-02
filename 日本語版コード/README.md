# 日本語版コード

このフォルダには、E-GEO日本語TOEIC縮小再現実験で現在使用するコードだけを置きます。

## 実行順

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
| 9A | `05c_TOEIC_OpenAI単一キー実験を自動実行.py` | OpenAIモデルだけで本体実験を実行する | `--execute`時のみ |
| 9B | `05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py` | OpenAI・Gemini・Claudeで本体実験を実行する | `--execute`時のみ |
| 10 | `06_TOEICメタ最適化実験結果を分析.py` | 統計・収束・特徴・図表を生成する | なし |
| 11 | `07_TOEIC研究完了チェック.py` | 件数・Test・分析・費用を検査する | なし |

## 重要：05cと05dの違い

### 05c：OpenAIだけ

```text
05c_TOEIC_OpenAI単一キー実験を自動実行.py
```

必要なキーは`OPENAI_API_KEY`だけです。

```text
Rewriter              GPT-4.1
Meta-optimizer         GPT-4.1
Training Model A       GPT-4.1
Training Model B       GPT-4.1 mini
Held-out Model E       GPT-5
```

簡単に実行できますが、全モデルが同じ提供元であるため、提供元をまたぐ一般化検証は弱くなります。

### 05d：OpenAI・Gemini・Claude

```text
05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py
```

必要なキーは次の3つです。

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

役割は次のとおりです。

```text
Candidate selector     OpenAI GPT-5 mini
Rewriter               OpenAI GPT-4.1
Meta-optimizer          OpenAI GPT-4.1
Training Model A        OpenAI GPT-4.1
Training Model B        Google Gemini 3 Flash Preview
Held-out Model E        Anthropic Claude Sonnet 4.5
```

こちらを正式実験の第一候補とします。先行研究の4学習・2評価モデルよりは縮小していますが、OpenAI・Google・Anthropicを分離できるため、OpenAIだけの構成より研究上の説得力が高くなります。

## 内部共通ランナー

```text
05c_TOEICメタ最適化API実験を自動実行.py
```

これはOpenAI版の共通実験ロジックを保持する内部ファイルです。通常は直接実行せず、分かりやすい名前の`05c_TOEIC_OpenAI単一キー実験を自動実行.py`を使用します。

## 一括実行スクリプト

### OpenAIのみ

```text
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

### OpenAI・Gemini・Claude

```text
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

APIを呼ばずに構文・入力・設定だけ検査する場合：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Validate
```

3社を実際に1プロンプト・少数データで確認する場合：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Smoke
```

正式実験：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Full
```

## 設定ファイル

```text
日本語版設定/
├─ TOEIC_OpenAI単一キー実験設定_v1.json
└─ TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
```

モデルID、API提供元、単価、温度、出力上限、予算停止条件はコードから分離しています。

## 出力フォルダも分離

### OpenAIのみ

```text
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/
```

### OpenAI・Gemini・Claude

```text
日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
```

異なるモデル構成の結果を同じフォルダへ混ぜません。

## 再開と予算停止

両ランナーとも、入力・モデル・工程から作成した`job_id`で成功結果をJSONLへ保存します。途中停止後に同じコマンドを実行すると、成功済みジョブは再課金せずキャッシュから再利用します。

3社版では、OpenAI・Google・Anthropicの推定費用を合算し、20ドル、50ドル、80ドルで警告し、既定100ドルで停止します。

## APIキー管理

`.env.example`をコピーして、リポジトリ直下へ`.env`を作ります。実際のキーは`.env`だけへ保存し、GitHub、チャット、スクリーンショットへ載せません。
