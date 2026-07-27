# TOEIC商品データ

このフォルダには、楽天ブックスから取得したTOEIC教材データと、その加工結果を保存します。

## 元データ

```text
元データ/rakuten_toeic_raw_20260727.xlsx
```

Octoparseで取得した未加工データです。直接編集せず、再処理が必要な場合の原本として保持します。Git管理外です。

## クレンジング後の4ファイル

### `toeic_products_clean.csv`

次工程で使用する主データです。

- 電子書籍ではない
- TOEIC関連タイトルである
- ISBNと商品URLが有効である
- 商品説明が存在する
- 重複として除外されていない

`review`対象の商品も含まれます。したがって、これは「完全に問題なし」ではなく、「自動除外条件を通過した商品一覧」です。

### `toeic_products_excluded.csv`

クレンジング時に自動除外された商品です。通常の実験入力には使用しません。

除外理由の確認、集計、処理の妥当性確認、研究報告での除外フロー説明に使用します。

### `toeic_products_review.csv`

`clean`の中から、追加確認が必要な商品だけを抜き出した部分集合です。

例：

- 商品説明が短い
- 著者情報がない
- 価格情報がない
- 商品説明が非常に長い
- カテゴリ判定が `other`
- 謝恩価格本・バーゲン本

このファイルを別の入力データとして結合してはいけません。`clean`と重複しています。

### `toeic_cleaning_summary.json`

件数、説明文長、カテゴリ数、除外理由、要確認理由をまとめた集計ファイルです。

データ品質確認、README、ポスターのデータ作成フローに使用します。

## 次工程で使うファイル

商品プール作成の入力は次の1ファイルです。

```text
加工済み/toeic_products_clean.csv
```

`excluded`は実験に戻さず、`review`は選定ルールの確認に使い、`summary`は件数報告に使います。

## 商品プール作成後

`08_TOEIC商品プール作成.py`を実行すると、次が作られます。

```text
実験データ/toeic_product_pool_200.csv
実験データ/toeic_product_pool_holdout.csv
実験データ/toeic_product_pool_phase_excluded.csv
実験データ/toeic_product_pool_summary.json
実験データ/toeic_product_pool_review.xlsx
```

- `pool_200`：80購入意図と候補集合を作るための固定商品プール
- `holdout`：条件は満たしたが200件に入らなかった予備商品
- `phase_excluded`：商品プール段階の追加条件で外れた商品
- `summary`：選定件数とカテゴリ構成
- `review.xlsx`：人間が確認しやすい一覧
