# E-GEO 日本語版ガイド

この文書は、英語版E-GEOの先行研究を保持しながら、日本語TOEIC教材版の実験を初心者でも追いやすくするための案内です。コマンドは、リポジトリ直下の `E-GEO/` で実行してください。

## この研究の目的

原版E-GEOは、商品説明を書き換えることで、生成AIの商品ランキング上の順位がどのように変化するかを調べる研究基盤です。書き換え対象の商品について、事実を変えず、検索クエリを直接見ないという条件で順位改善を測定します。

この日本語版では、その考え方を日本語の架空TOEIC教材に当てはめます。現在は、10冊の商品候補と3件の検索クエリを使い、データ作成、内容確認、ランキング入力確認、初期順位取得までを実装しています。

## 原版E-GEOと日本語版の違い

| 項目 | 原版E-GEO | 日本語版 |
|---|---|---|
| 主な目的 | 公開データを使ったE-GEO研究・評価・提出 | 日本語TOEIC教材を使った小規模実験 |
| 商品・クエリ | 英語の実商品と長文ショッピングクエリ | 研究用に作成した架空の日本語教材とクエリ |
| コード | `src/` | `日本語版コード/` |
| データ | `data/` | `日本語版データ/` |
| 規模 | テスト2,000件を含む大規模データ | 3クエリ、各10商品 |
| 現在の到達点 | 書き換え、最適化、複数モデル評価、提出 | 初期順位取得まで |

原版の `src/`、`data/`、`submissions/`、`README.md`、`data.md`、`submission.md`、`pyproject.toml`、`uv.lock` は原著者の領域です。日本語版の整理では変更しません。

## フォルダ構成図

```text
E-GEO/
├── README.md                         # 原版の研究概要
├── README_日本語.md                  # この日本語ガイド
├── data.md                           # 原版データの説明
├── submission.md                     # 原版リーダーボードへの提出方法
├── pyproject.toml / uv.lock           # Python環境と依存関係
├── assets/                            # 原版READMEの画像
├── src/                               # 原版E-GEOコード
│   └── multi_model_optimization/      # 複数モデル・プロンプト最適化
├── data/                              # 原版E-GEOデータ
│   └── initial_ranking/               # 原版の初期順位
├── submissions/                       # 原版の提出例
├── 日本語版コード/
│   ├── README.md
│   ├── 01_サンプルデータ作成.py
│   ├── 02_サンプルデータ確認.py
│   ├── 03_順位付け入力確認.py
│   └── 04_初期順位取得.py
└── 日本語版データ/
    ├── 元データ/
    │   └── toeic_products_sample.csv
    ├── 実験用データ/
    │   ├── test_data_ja.json
    │   ├── test_selected_products_ja.json
    │   └── ranking_prompt_preview.txt
    └── 実験結果/
        ├── .gitkeep
        └── initial_ranking_ja.json     # 04番の実行後に作成
```

`.git/`、`.cache/`、`.env`、仮想環境、Pythonキャッシュなどのローカル管理ファイルは、上の図と説明表から除外しています。

## 実行前の準備

原版E-GEOと同じく、Python 3.11以上と `uv` を使用します。初回だけ、原版の `README.md` に従って `uv` を用意し、リポジトリ直下で依存関係を準備してください。

```powershell
uv sync
```

以降の実行例は `uv run python` を使用します。これにより、E-GEO用の仮想環境でスクリプトが実行されます。

## 各Pythonファイルの実行順序

| 順序 | ファイル・処理 | 内容 | API通信 |
|---:|---|---|---|
| 1 | `01_サンプルデータ作成.py` | 架空の商品、クエリ、書き換え対象をCSV・JSONに保存 | なし |
| 2 | `02_サンプルデータ確認.py` | 商品数と書き換え対象の対応を確認 | なし |
| 3 | `03_順位付け入力確認.py` | ランキング用プロンプトを作成して目視確認 | なし |
| 4 | `04_初期順位取得.py` | LLMから書き換え前の順位を取得 | あり |
| 5 | 今後追加する商品説明書き換え | 対象商品の説明文を書き換える | 未実装 |
| 6 | 書き換え後順位取得 | 書き換えた商品を再順位付けする | 未実装 |
| 7 | 順位改善の計算 | 書き換え前後の順位差を計算する | 未実装 |

01番から03番までは、次の順でローカル実行できます。

```powershell
uv run python "日本語版コード/01_サンプルデータ作成.py"
uv run python "日本語版コード/02_サンプルデータ確認.py"
uv run python "日本語版コード/03_順位付け入力確認.py"
```

## API課金が発生する処理

日本語版でAPI通信を行うのは `04_初期順位取得.py` だけです。`--execute` を付けたうえで確認画面に `y` または `yes` と入力した場合、OpenAIまたはOpenRouterへリクエストを送信し、利用料金が発生する可能性があります。

- `--execute` なしではAPIを呼び出しません。
- このリポジトリ整理時の確認では、04番を実行していません。
- 構文確認はファイルを実行せず、Pythonソースをコンパイルするだけです。
- 原版の `src/submission.py` と `src/multi_model_optimization/` にもAPI処理があります。原版の説明に従い、料金を確認してから使用してください。

## OpenRouter APIキーの設定方法

1. OpenRouterでアカウントを作成し、APIキーを発行します。
2. APIキーを画面共有、README、ソースコード、Git履歴へ書かないでください。
3. PowerShellの現在の画面だけで使う場合は、次のように環境変数へ設定します。`<自分のAPIキー>` は実際の値に置き換えます。

```powershell
$env:OPENROUTER_API_KEY = "<自分のAPIキー>"
```

4. リポジトリ直下の `.env` を使う場合は、次の形式で自分の端末上だけに保存します。

```dotenv
OPENROUTER_API_KEY=<自分のAPIキー>
```

`.env` は `.gitignore` の対象です。`git status` に表示されないことを確認し、内容を表示・共有・コミットしないでください。

OpenRouterを使って04番を実行する場合の形式は次のとおりです。これは課金を伴う可能性があるため、モデル名と料金を確認してから実行してください。

```powershell
uv run python "日本語版コード/04_初期順位取得.py" --provider openrouter --model "<OpenRouterのモデルID>" --execute
```

04番のデフォルトはOpenAIです。デフォルト設定を使う場合は `OPENAI_API_KEY` が必要です。APIキーやモデルのデフォルト値は、実験条件を確認せず変更しないでください。

## 全ファイルの説明表

| ファイル・フォルダ | 所属 | 役割 | 入力 | 出力 | 実行順 |
|---|---|---|---|---|---|
| `.gitignore` | 共通 | Gitへ登録しないファイルを指定 | なし | Git除外規則 | — |
| `README.md` | 原版 | 原版E-GEOの研究概要とセットアップ | なし | 説明文 | — |
| `README_日本語.md` | 日本語版 | 日本語版を含むリポジトリ全体の案内 | リポジトリ構成 | 説明文 | — |
| `data.md` | 原版 | 原版データの構造と取得方法 | なし | 説明文 | — |
| `submission.md` | 原版 | リーダーボードへの提出・評価方法 | なし | 説明文 | — |
| `pyproject.toml` | 原版 | Pythonバージョンと依存関係を定義 | なし | 環境設定 | — |
| `uv.lock` | 原版 | 依存パッケージのバージョンを固定 | `pyproject.toml` | 固定済み依存情報 | — |
| `assets/GEO_in_e-commerce.png` | 原版 | E-GEOの流れを示すREADME画像 | なし | 画像 | — |
| `data/queries_products.json` | 原版 | 全クエリと各10商品の候補を収録 | Hugging Face配布データ | 原版実験の入力 | — |
| `data/test_data.json` | 原版 | 固定テストクエリ2,000件 | 原版データ作成処理 | テスト入力 | — |
| `data/test_selected_products.json` | 原版 | テストごとの書き換え対象商品 | 原版データ作成処理 | 対象商品情報 | — |
| `data/train1000_val500.json` | 原版 | 論文の学習1,000件・検証500件 | 原版データ作成処理 | 最適化入力 | — |
| `data/train_selected_products.json` | 原版 | 学習・検証ごとの対象商品 | 原版データ作成処理 | 対象商品情報 | — |
| `data/train_val_full.json` | 原版 | テスト以外の全クエリ | 原版データ作成処理 | 拡張実験入力 | — |
| `data/initial_ranking/test_initial_ranking_claude.json` | 原版 | Claudeによるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/test_initial_ranking_deepseek.json` | 原版 | DeepSeekによるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/test_initial_ranking_gemini.json` | 原版 | Geminiによるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/test_initial_ranking_gpt41.json` | 原版 | GPT-4.1によるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/test_initial_ranking_gpt5.json` | 原版 | GPT-5によるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/test_initial_ranking_llama.json` | 原版 | Llamaによるテスト初期順位 | `test_data.json` | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_claude.json` | 原版 | Claudeによる学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_deepseek.json` | 原版 | DeepSeekによる学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_gemini.json` | 原版 | Geminiによる学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_gpt41.json` | 原版 | GPT-4.1による学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_gpt5.json` | 原版 | GPT-5による学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `data/initial_ranking/train_val_initial_ranking_llama.json` | 原版 | Llamaによる学習・検証初期順位 | 学習・検証データ | 初期順位 | — |
| `src/__init__.py` | 原版 | `src` をPythonパッケージとして扱う | なし | パッケージ定義 | — |
| `src/all_init_prompts.py` | 原版 | 初期・攻撃的書き換えプロンプトを定義 | なし | プロンプト辞書 | — |
| `src/analysis.py` | 原版 | 実験CSVの統計計算とグラフ作成 | 実験結果CSV | 統計・グラフ | 原版手順 |
| `src/length_structure_analysis.py` | 原版 | 文の長さ・構造と順位改善を分析 | `results/` | 分析結果 | 原版手順 |
| `src/optimized_prompts.json` | 原版 | 最適化済みプロンプト15種類 | 原版最適化結果 | 書き換えプロンプト | — |
| `src/prompts.py` | 原版 | モデル別・最適化用プロンプトを定義 | なし | プロンプト文字列 | — |
| `src/submission.py` | 原版 | 書き換え、評価、提出ファイル作成の入口 | `data/`、プロンプトまたは書き換え | `submissions/` | 原版手順 |
| `src/utils.py` | 原版 | 商品整形、JSON抽出、統計表示の共通関数 | 各処理のデータ | 整形済みデータ | — |
| `src/multi_model_optimization/adversarial_benchmark.py` | 原版 | 14種類の攻撃的書き換えを評価 | 原版テストデータ・プロンプト | CSV・JSON結果 | 原版手順 |
| `src/multi_model_optimization/config.py` | 原版 | モデル、料金、パス、トークン上限を定義 | なし | 共通設定 | — |
| `src/multi_model_optimization/cross_engine_optimization.py` | 原版 | 複数順位付けモデル向けにプロンプトを改善 | プロンプト・評価履歴 | 改善プロンプト | 原版手順 |
| `src/multi_model_optimization/leaderboard.py` | 原版 | 書き換えモデルと評価モデルを横断比較 | 原版実験結果 | リーダーボードJSON | 原版手順 |
| `src/multi_model_optimization/llm_helpers.py` | 原版 | LLM書き換え・順位付けの共通処理 | 商品・クエリ・プロンプト | 書き換え・順位 | — |
| `src/multi_model_optimization/make_feature_heatmap.py` | 原版 | 書き換え特徴のヒートマップを作成 | 特徴量・結果 | 画像 | 原版手順 |
| `src/multi_model_optimization/optimizing_prompts.py` | 原版 | 初期プロンプトのベースライン評価 | 原版データ・プロンプト | 評価結果 | 原版手順 |
| `src/multi_model_optimization/reranking_claude_caching.py` | 原版 | Claudeキャッシュを使って再順位付け | 書き換え商品 | Claude順位結果 | 原版手順 |
| `src/multi_model_optimization/reranking_prompts.py` | 原版 | 書き換え商品を各モデルで再順位付け | 書き換え商品 | 順位結果 | 原版手順 |
| `src/multi_model_optimization/run_meta_optimization.py` | 原版 | メタプロンプト最適化を実行 | 学習・検証データ | 最適化履歴・最良プロンプト | 原版手順 |
| `submissions/README.md` | 原版 | 提出フォルダの形式を説明 | なし | 説明文 | — |
| `submissions/example/README.md` | 原版 | 提出サンプルを説明 | サンプルファイル | 説明文 | — |
| `submissions/example/metadata.json` | 原版 | 提出者・モデル・条件のサンプル | 提出設定 | メタデータ | — |
| `submissions/example/results.json` | 原版 | モデル別評価値のサンプル | 評価結果 | 集計結果 | — |
| `submissions/example/rewrites.jsonl` | 原版 | 商品説明書き換えのサンプル | 原商品説明 | 書き換え行 | — |
| `日本語版コード/README.md` | 日本語版 | 日本語版コードの実行順と注意事項 | 日本語版構成 | 説明文 | — |
| `日本語版コード/01_サンプルデータ作成.py` | 日本語版 | 架空の教材・クエリ・対象商品を作成 | なし | CSV、JSON2ファイル | 1 |
| `日本語版コード/02_サンプルデータ確認.py` | 日本語版 | 2つのJSONの対応と商品数を確認 | 日本語版JSON2ファイル | 画面表示 | 2 |
| `日本語版コード/03_順位付け入力確認.py` | 日本語版 | 順位付け用入力プロンプトを生成 | `test_data_ja.json` | `ranking_prompt_preview.txt` | 3 |
| `日本語版コード/04_初期順位取得.py` | 日本語版 | LLMから書き換え前順位を取得 | `test_data_ja.json`、APIキー | `initial_ranking_ja.json` | 4 |
| `日本語版データ/元データ/toeic_products_sample.csv` | 日本語版 | 架空のTOEIC教材10冊の元データ | 01番内の商品定義 | 01番のCSV出力 | 1で生成 |
| `日本語版データ/実験用データ/test_data_ja.json` | 日本語版 | 3クエリと各10商品の候補 | 01番内の商品・クエリ | 02～04番の入力 | 1で生成 |
| `日本語版データ/実験用データ/test_selected_products_ja.json` | 日本語版 | クエリごとの書き換え対象商品 | 01番内の対象番号 | 02番の入力 | 1で生成 |
| `日本語版データ/実験用データ/ranking_prompt_preview.txt` | 日本語版 | LLMに渡す順位付け入力の確認用 | `test_data_ja.json` | 読みやすいプロンプト | 3で生成 |
| `日本語版データ/実験結果/.gitkeep` | 日本語版 | 空の実験結果フォルダをGitで保持 | なし | なし | — |
| `日本語版データ/実験結果/initial_ranking_ja.json` | 日本語版 | APIから取得した初期順位を保存 | 04番のAPI応答 | クエリ別順位 | 4で生成 |

## 現在までに完了した作業

- 原版E-GEOのコード、データ、説明文を保持した。
- `src_ja/` を `日本語版コード/` へ整理した。
- 4つのPythonファイルを、実行順が分かる日本語名へ整理した。
- `data_ja/` を `日本語版データ/` へ整理した。
- データを `元データ/`、`実験用データ/`、`実験結果/` に分けた。
- 各Pythonファイルへ目的、入出力、処理手順、課金、変更箇所の説明を追加した。
- 各関数へ日本語docstringまたはコメントを追加した。
- README内のパスと実行コマンドを日本語名へ統一した。
- Python構文、JSON、CSV、パス、01～03番のローカル動作をAPIなしで確認した。
- 04番は構文だけを確認し、API通信は実行していない。

## 次に行う作業

1. 商品説明を書き換える処理を追加する。
2. 書き換え後の商品を同じ条件で再順位付けする。
3. `初期順位 - 書き換え後順位` を計算し、順位改善を集計する。
4. 必要に応じて複数モデルで同じ実験を行い、結果を比較する。

## トラブル時の確認項目

- コマンドをリポジトリ直下の `E-GEO/` で実行しているか。
- Python 3.11以上を使用しているか。
- `uv` がインストールされ、`uv sync` が完了しているか。
- フォルダ名が `日本語版コード`、`日本語版データ`、`元データ`、`実験用データ`、`実験結果` と完全に一致しているか。
- 01番の実行後にCSVと2つのJSONが存在するか。
- JSONがUTF-8、CSVがUTF-8 BOM付きとして読み込めるか。
- 03番で `src/utils.py` の読み込みエラーが出ていないか。
- 04番を実行する場合、`--provider` と対応するAPIキーが一致しているか。
- API実行前にモデル名、料金、利用上限を確認したか。
- `.env` やAPIキーが `git status`、画面共有、ログへ出ていないか。
- 原版の `src/` と `data/` を日本語版の出力先にしていないか。
