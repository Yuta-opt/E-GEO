# Amazon ESCI 日本語データ

このフォルダには、E-GEO日本語転移実験で使用するAmazon Shopping Queries Dataset（ESCI）の日本語データを置きます。

## 1. データの出典

データセット名：Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product Search

公開元：Amazon Science / amazon-science/esci-data

主な内容：

- 検索クエリ
- クエリID
- 商品ID
- 商品言語
- E/S/C/I関連度ラベル
- 商品名
- 商品説明
- 箇条書き
- ブランド
- 色

本研究では `product_locale == "jp"` の日本語データを使用します。

## 2. フォルダ構成

```text
ESCI/
├── README.MD
├── 元データ/
│   ├── shopping_queries_dataset_examples.parquet
│   ├── shopping_queries_dataset_products.parquet
│   └── shopping_queries_dataset_sources.csv
└── 加工済み/
    └── esci_jp_preview.csv
```

### 元データ

Amazonが公開する未加工データです。原本として扱い、直接編集しません。

ファイルサイズが大きいため、`.gitignore`でGit管理から除外しています。

### 加工済み

日本語データの抽出、商品情報との結合、欠損処理、HTML除去、実験用データ作成などの結果を保存します。

## 3. 現在の処理

`日本語版コード/05_ESCI日本語データ確認.py`で次を行います。

1. 必要な3ファイルが存在するか確認
2. `product_locale == "jp"` の行だけを読込
3. `small_version == 1` のデータを抽出
4. 候補商品が10件以上あるクエリを確認
5. 商品メタデータと結合
6. 最初の5クエリ分を確認用CSVへ保存

実行コマンド：

```powershell
uv run python "日本語版コード/05_ESCI日本語データ確認.py"
```

出力：

```text
日本語版データ/ESCI/加工済み/esci_jp_preview.csv
```

## 4. 本研究での利用方針

ESCIの日本語クエリは短い検索キーワードが中心です。

そのため、本研究では次の2種類のクエリを比較する予定です。

- ESCIの元の短文クエリ
- 同じ検索意図を保って自然な日本語へ拡張した長文クエリ

短文と長文で、候補商品10件と書き換え対象商品1件は共通にします。

## 5. 暫定データ規模

全体分析とAPIパイロット後に確定しますが、現在の目安は次のとおりです。

| 分割 | 件数 |
|---|---:|
| Train | 80 |
| Validation | 40 |
| Test | 120 |
| 合計 | 240 |

追加検証用の長文クエリは、60〜80件程度を想定しています。

## 6. 今後の加工

今後、次を順番に実施します。

- クエリ文字数の分布分析
- 商品説明・箇条書きの欠損率分析
- HTMLタグの除去
- 商品説明の長さの確認
- 候補商品10件の固定
- 書き換え対象商品1件の固定
- Train・Validation・Testへの分割
- 長文クエリの作成
- 重複と欠損の最終検査

## 7. 再現性のために記録する項目

- 使用した元ファイル名
- 抽出条件
- 乱数seed
- 除外条件
- 最終件数
- クエリID
- 商品ID
- 書き換え対象商品ID
- データ分割
- 長文化前後のクエリ対応

## 8. 注意事項

- 元データをGitHubへpushしない
- 元データを直接編集しない
- APIキーをデータやREADMEへ書かない
- 商品説明の事実関係を変更しない
- Testデータをプロンプト最適化に使用しない
- データセットのライセンスと引用情報をポスター・報告書へ記載する
