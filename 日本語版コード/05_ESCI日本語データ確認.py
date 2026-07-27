from pathlib import Path

import pandas as pd


# このファイルが置かれている「日本語版コード」の1つ上＝E-GEOルート
PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = PROJECT_ROOT / "日本語版データ" / "ESCI" / "元データ"
OUTPUT_DIR = PROJECT_ROOT / "日本語版データ" / "ESCI" / "加工済み"

EXAMPLES_PATH = RAW_DIR / "shopping_queries_dataset_examples.parquet"
PRODUCTS_PATH = RAW_DIR / "shopping_queries_dataset_products.parquet"
SOURCES_PATH = RAW_DIR / "shopping_queries_dataset_sources.csv"

PREVIEW_PATH = OUTPUT_DIR / "esci_jp_preview.csv"


def check_files() -> None:
    """必要な元データが存在するか確認する。"""
    required_files = [
        EXAMPLES_PATH,
        PRODUCTS_PATH,
        SOURCES_PATH,
    ]

    missing_files = [path for path in required_files if not path.exists()]

    if missing_files:
        missing_text = "\n".join(f"- {path}" for path in missing_files)
        raise FileNotFoundError(
            "必要なESCIファイルが見つかりません。\n"
            f"{missing_text}\n"
            "READMEの手順に従ってダウンロードしてください。"
        )


def main() -> None:
    check_files()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("ESCIの日本語クエリを読み込んでいます……")

    # 日本語のquery-product対応だけを読み込む
    examples = pd.read_parquet(
        EXAMPLES_PATH,
        engine="pyarrow",
        columns=[
            "example_id",
            "query",
            "query_id",
            "product_id",
            "product_locale",
            "esci_label",
            "small_version",
            "large_version",
            "split",
        ],
        filters=[("product_locale", "==", "jp")],
    )

    # 今回は扱いやすい小規模版を利用する
    jp_small = examples[examples["small_version"] == 1].copy()

    candidate_counts = jp_small.groupby("query_id").size()
    valid_query_ids = candidate_counts[candidate_counts >= 10].index

    print()
    print("===== 日本語ESCIデータの概要 =====")
    print(f"query-product行数       : {len(jp_small):,}")
    print(f"ユニーククエリ数       : {jp_small['query_id'].nunique():,}")
    print(f"候補10商品以上のクエリ : {len(valid_query_ids):,}")
    print(f"候補商品数の最小値     : {candidate_counts.min()}")
    print(f"候補商品数の中央値     : {candidate_counts.median():.1f}")
    print(f"候補商品数の最大値     : {candidate_counts.max()}")

    print()
    print("===== ESCIラベル件数 =====")
    print(jp_small["esci_label"].value_counts(dropna=False).sort_index())

    print()
    print("日本語の商品情報を読み込んでいます……")

    products = pd.read_parquet(
        PRODUCTS_PATH,
        engine="pyarrow",
        columns=[
            "product_id",
            "product_title",
            "product_description",
            "product_bullet_point",
            "product_brand",
            "product_color",
            "product_locale",
        ],
        filters=[("product_locale", "==", "jp")],
    )

    # 候補が10件以上あるクエリから、最初の5件だけ確認用に保存
    preview_query_ids = (
        pd.Series(valid_query_ids)
        .sort_values()
        .head(5)
        .tolist()
    )

    preview_examples = jp_small[
        jp_small["query_id"].isin(preview_query_ids)
    ].copy()

    preview = preview_examples.merge(
        products,
        how="left",
        on=["product_locale", "product_id"],
        validate="many_to_one",
    )

    preview = preview.sort_values(
        ["query_id", "esci_label", "product_id"]
    )

    preview.to_csv(
        PREVIEW_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    print()
    print("===== 商品情報の欠損率 =====")
    for column in [
        "product_title",
        "product_description",
        "product_bullet_point",
        "product_brand",
    ]:
        missing_rate = preview[column].isna().mean() * 100
        print(f"{column:24s}: {missing_rate:6.2f}%")

    print()
    print("確認用CSVを保存しました。")
    print(PREVIEW_PATH)


if __name__ == "__main__":
    main()