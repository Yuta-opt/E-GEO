# 日本語版コード

このフォルダには、現在のE-GEO日本語TOEIC縮小再現実験で使うコードだけを置きます。

## 実行順

| 順番 | ファイル | 役割 | API |
|---:|---|---|---|
| 1 | `01_楽天TOEIC商品データをクレンジング.py` | 元商品データを整形し、明らかに使えない商品を除外する | なし |
| 2 | `02_実験用TOEIC商品プールを作成.py` | 価格欠損と明確な同一商品を除き、270件の商品プールを作る | なし |
| 3 | `03_TOEIC購入意図テンプレートを作成.py` | 商品を見ずに80件の購入意図を作る | なし |
| 4 | `04_TOEIC候補商品を割り当て.py` | 長文クエリと270商品を埋め込み、上位30件を取得する | なし |
| 5 | `04c_TOEIC候補検索入力を検証.py` | 上位30件が正式クエリ・最終商品説明から作られたことを検証する | なし |
| 6 | `04b_TOEIC候補10商品を選ぶ.py` | 上位30件からLLMで関連商品10件を選び、seed 42で対象商品を固定する | `--execute`時のみ |
| 7 | `05a_TOEICメタ最適化実験を計画.py` | 15初期プロンプトのTrain／ValidationスケジュールとAPI予定回数を作る | なし |
| 8 | `05b_TOEIC候補選定API直前チェック.py` | 最初の有料API工程を実行できる状態か検査する | なし |

## 04 Dense Retrieval

```powershell
uv run python ".\日本語版コード\04_TOEIC候補商品を割り当て.py" --require-approved --overwrite
```

主実験の長文クエリを使用し、次を行います。

```text
270商品のタイトル＋説明文を埋め込み
↓
80件の長文クエリを埋め込み
↓
コサイン類似度を計算
↓
各購入意図の上位30商品を固定
```

カテゴリ絞り込み、タイトル4倍、目標得点加点などの独自処理は使用しません。

## 04c Dense入力検証

```powershell
uv run python ".\日本語版コード\04c_TOEIC候補検索入力を検証.py"
```

次の完全一致を確認します。

- `toeic_query_intents_review.xlsx`の`long_query_final`
- `toeic_product_pool_final.csv`の`title`
- `toeic_product_pool_final.csv`の`description_clean`
- 作成済み`01_dense_retrieval_top30.csv`の2,400行

旧`toeic_query_intents_master.csv`は正式入力ではありません。

## 04b 候補10件選定

APIを使わず計画だけ確認する場合：

```powershell
uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" --model gpt-5-mini-2025-08-07
```

1件だけ有料パイロットを行う場合：

```powershell
uv run python ".\日本語版コード\04b_TOEIC候補10商品を選ぶ.py" --splits train --limit 1 --model gpt-5-mini-2025-08-07 --execute
```

`--execute`を付けるまでAPIは呼び出しません。候補選定モデルは、再現性のため固定スナップショット`gpt-5-mini-2025-08-07`を使用します。

全80件が成功すると、候補10件とseed 42による対象商品が自動生成されます。

## 05a メタ最適化計画

```powershell
uv run python ".\日本語版コード\05a_TOEICメタ最適化実験を計画.py"
```

次を検査・保存します。

- Train 40／Validation 10／Test 30
- 初期プロンプト15種類
- 2 epochs × 4 batches × 10件
- 各バッチ版のValidation評価
- 各初期プロンプト6回のMeta-optimizer更新
- Testロック
- 1モデル確認案、最小研究構成、先行研究に近い構成のAPI予定回数

このコード自体はAPIを呼び出しません。

## 05b 最初のAPI直前チェック

```powershell
uv run python ".\日本語版コード\05b_TOEIC候補選定API直前チェック.py"
```

次を確認します。

- Dense入力検証が合格済み
- 候補選定ジョブが80件
- 固定モデルが`gpt-5-mini-2025-08-07`
- 既存成功結果の件数
- `.env`から`OPENAI_API_KEY`を読み込めるか

このチェックはAPIを呼び出さず、キーの値も表示しません。

## 削除した旧コード

以下は、先行研究の結論を単一プロンプト比較と誤認して作成したため削除しました。

- 旧`05_TOEIC_API実験を実行.py`
- 旧`06_TOEIC実験結果を分析.py`
- 旧`07_TOEIC本番前チェック.py`
- `99_旧版/`内の保存用コード

今後の05本体、06分析、07本番前チェックは、15プロンプトのメタ最適化設計に沿って新規作成します。
