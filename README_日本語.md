# E-GEO 日本語TOEIC縮小再現実験

E-GEO v2の中核である、**複数Re-rankerの順位結果を用いたプロンプトのメタ最適化**を、日本語のTOEIC教材領域で小規模に再現する研究です。

## 研究の中心

```text
15種類の初期リライトプロンプト
        ↓
Trainで複数Re-rankerの順位改善量を測定
        ↓
履歴をMeta-optimizerへ渡してプロンプトを更新
        ↓
Validation平均が最も高い版を固定
        ↓
未使用のTestと評価専用Re-rankerで最終評価
        ↓
初期版と最適化版、長文と短文、プロンプト収束を分析
```

位置づけは、**E-GEO v2のscaled-down replicationと、日本語・TOEIC・短文検索への拡張**です。

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

## 本体実験は2経路に分離

### A. OpenAI単一キー版

実行入口：

```text
日本語版コード/05c_TOEIC_OpenAI単一キー実験を自動実行.py
tools/実行_TOEIC研究_OpenAI単一キー.ps1
```

必要なキー：

```env
OPENAI_API_KEY=
```

モデル構成：

```text
Rewriter              GPT-4.1
Meta-optimizer         GPT-4.1
Training Model A       GPT-4.1
Training Model B       GPT-4.1 mini
Held-out Model E       GPT-5
```

実装は簡単ですが、全モデルが同じ提供元である点が制約です。

### B. OpenAI・Gemini・Claude版（正式実験の第一候補）

実行入口：

```text
日本語版コード/05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py
tools/実行_TOEIC研究_OpenAI_Gemini_Claude.ps1
```

必要なキー：

```env
OPENAI_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

モデル構成：

```text
Candidate selector     OpenAI GPT-5 mini
Rewriter               OpenAI GPT-4.1
Meta-optimizer          OpenAI GPT-4.1
Training Model A        OpenAI GPT-4.1
Training Model B        Google Gemini 3 Flash Preview
Held-out Model E        Anthropic Claude Sonnet 4.5
```

先行研究の4学習＋2評価モデルから2学習＋1評価へ縮小していますが、OpenAI・Google・Anthropicを分離できるため、OpenAI単一キー版より提供元をまたぐ一般化検証が強くなります。

## ファイル名と出力を混ぜない

### OpenAIのみ

```text
日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json
日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行/
```

### OpenAI・Gemini・Claude

```text
日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json
日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/
日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude/
```

異なる構成のAPI結果や分析結果を同じフォルダへ混ぜません。

## 3社版の実行方法

APIを使わない構文・入力・設定確認：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Validate
```

3社すべてを少数データで確認：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Smoke
```

正式実験：

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\実行_TOEIC研究_OpenAI_Gemini_Claude.ps1" -Mode Full
```

20・50・80ドルで警告し、既定100ドルで停止します。成功済みジョブはJSONLキャッシュから再利用するため、途中停止後に同じコマンドで再開できます。

## 現在地

完了：

- 商品クレンジングと270商品固定
- 購入意図80件、長文・短文クエリ
- Dense Retrieval上位30件
- Dense入力の完全一致検証
- 初期プロンプト15種類
- メタ最適化スケジュール
- OpenAI単一キー版ランナー
- OpenAI・Gemini・Claude版ランナー
- 統計・収束・図表の自動分析コード
- 研究完了チェック
- 2経路の設定・実行・出力フォルダ分離

未完了：

- GPT-5 miniによる候補30件→10件の有料選定
- 3社APIのsmoke実行
- 実測トークンによる最終費用確定
- 正式Train／Validation／Test
- ポスターへの結果反映

**有料API呼び出しはまだ0回です。**

## 正本ドキュメント

- `日本語版ドキュメント/TOEIC実験_現行設計と実施記録.md`
- `日本語版ドキュメント/TOEIC_API費用と完了見込み.md`
- `日本語版ドキュメント/TOEIC購入意図クエリ作成記録.md`
- `日本語版ドキュメント/先行研究/`
