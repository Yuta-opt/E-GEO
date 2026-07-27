from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "日本語版データ" / "ESCI" / "元データ"
OUTPUT_DIR = PROJECT_ROOT / "日本語版データ" / "ESCI" / "加工済み"

EXAMPLES_PATH = RAW_DIR / "shopping_queries_dataset_examples.parquet"
PRODUCTS_PATH = RAW_DIR / "shopping_queries_dataset_products.parquet"

SUMMARY_PATH = OUTPUT_DIR / "esci_jp_quality_summary.csv"
QUERY_REPORT_PATH = OUTPUT_DIR / "esci_jp_query_quality.csv"
SUSPICIOUS_PRODUCTS_PATH = OUTPUT_DIR / "esci_jp_suspicious_products.csv"
ELIGIBLE_QUERIES_PATH = OUTPUT_DIR / "esci_jp_eligible_queries.csv"
SETTINGS_PATH = OUTPUT_DIR / "esci_jp_quality_settings.json"

# 文字化けで頻出する断片。完全判定ではなく、要確認候補を拾うために使う。
MOJIBAKE_FRAGMENTS = (
    "�",
    "Ã",
    "Â",
    "â€",
    "縺",
    "繧",
    "譁",
    "蜿",
    "莨",
    "荳",
)

HTML_TAG_RE = re.compile(r"<[^>]+>")
HANGUL_RE = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")
JAPANESE_RE = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
WHITESPACE_RE = re.compile(r"\s+")

# この段階では削除を確定せず、「本番候補として使える可能性が高い」条件だけを定義する。
MIN_QUERY_LENGTH = 2
MIN_TITLE_LENGTH = 3
MIN_PRODUCT_TEXT_LENGTH = 20
MIN_USABLE_PRODUCTS_PER_QUERY = 10
SUSPICIOUS_SAMPLE_LIMIT = 1000


def check_files() -> None:
    missing = [path for path in (EXAMPLES_PATH, PRODUCTS_PATH) if not path.exists()]
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(
            "必要なESCI元データが見つかりません。\n"
            f"{missing_text}\n"
            "日本語版データ/ESCI/元データ に配置してください。"
        )


def normalize_text(value: object) -> str:
    """比較・分析用の軽い正規化。元データ自体は変更しない。"""
    if value is None or pd.isna(value):
        return ""

    text = str(value)
    text = html.unescape(text)
    text = HTML_TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def count_pattern(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def has_mojibake(text: str) -> bool:
    return any(fragment in text for fragment in MOJIBAKE_FRAGMENTS)


def unusual_character_count(text: str) -> int:
    """文字化けや制御文字の参考指標。記号や英数字は異常扱いしない。"""
    count = 0
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cc", "Cs", "Co", "Cn"}:
            count += 1
    return count


def make_product_text(row: pd.Series) -> str:
    parts = [
        row["product_title_clean"],
        row["product_description_clean"],
        row["product_bullet_point_clean"],
    ]
    return " ".join(part for part in parts if part).strip()


def metric_row(metric: str, value: object, note: str = "") -> dict[str, object]:
    return {"metric": metric, "value": value, "note": note}


def main() -> None:
    check_files()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("1/5 日本語ESCIのquery-product対応を読み込んでいます……")
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
    examples = examples[examples["small_version"] == 1].copy()

    print("2/5 日本語の商品情報を読み込んでいます……")
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
    ).copy()

    text_columns = [
        "product_title",
        "product_description",
        "product_bullet_point",
        "product_brand",
        "product_color",
    ]
    for column in text_columns:
        products[f"{column}_clean"] = products[column].map(normalize_text)

    products["product_text_clean"] = products.apply(make_product_text, axis=1)
    products["title_length"] = products["product_title_clean"].str.len()
    products["description_length"] = products["product_description_clean"].str.len()
    products["bullet_length"] = products["product_bullet_point_clean"].str.len()
    products["product_text_length"] = products["product_text_clean"].str.len()

    products["replacement_char_count"] = products["product_text_clean"].str.count("�")
    products["hangul_count"] = products["product_text_clean"].map(
        lambda text: count_pattern(HANGUL_RE, text)
    )
    products["japanese_char_count"] = products["product_text_clean"].map(
        lambda text: count_pattern(JAPANESE_RE, text)
    )
    products["unusual_char_count"] = products["product_text_clean"].map(
        unusual_character_count
    )
    products["has_mojibake"] = products["product_text_clean"].map(has_mojibake)
    products["has_html_raw"] = products[text_columns].fillna("").astype(str).apply(
        lambda row: any(bool(HTML_TAG_RE.search(value)) for value in row),
        axis=1,
    )

    products["product_suspicious"] = (
        (products["replacement_char_count"] > 0)
        | products["has_mojibake"]
        | (products["hangul_count"] >= 2)
        | (products["unusual_char_count"] > 0)
    )

    products["product_usable"] = (
        (products["title_length"] >= MIN_TITLE_LENGTH)
        & (products["product_text_length"] >= MIN_PRODUCT_TEXT_LENGTH)
        & ~products["product_suspicious"]
    )

    print("3/5 クエリの品質を分析しています……")
    queries = (
        examples[["query_id", "query", "split"]]
        .drop_duplicates(subset=["query_id"])
        .copy()
    )
    queries["query_clean"] = queries["query"].map(normalize_text)
    queries["query_length"] = queries["query_clean"].str.len()
    queries["replacement_char_count"] = queries["query_clean"].str.count("�")
    queries["hangul_count"] = queries["query_clean"].map(
        lambda text: count_pattern(HANGUL_RE, text)
    )
    queries["japanese_char_count"] = queries["query_clean"].map(
        lambda text: count_pattern(JAPANESE_RE, text)
    )
    queries["unusual_char_count"] = queries["query_clean"].map(
        unusual_character_count
    )
    queries["has_mojibake"] = queries["query_clean"].map(has_mojibake)
    queries["query_suspicious"] = (
        (queries["query_length"] < MIN_QUERY_LENGTH)
        | (queries["replacement_char_count"] > 0)
        | queries["has_mojibake"]
        | (queries["hangul_count"] >= 2)
        | (queries["unusual_char_count"] > 0)
    )

    print("4/5 クエリごとの利用可能商品数を計算しています……")
    merged = examples.merge(
        products[
            [
                "product_id",
                "product_locale",
                "product_usable",
                "product_suspicious",
                "product_text_length",
            ]
        ],
        on=["product_id", "product_locale"],
        how="left",
        validate="many_to_one",
    )
    merged["product_usable"] = merged["product_usable"].fillna(False).astype(bool)
    merged["product_suspicious"] = (
        merged["product_suspicious"].fillna(True).astype(bool)
    )

    counts = merged.groupby("query_id").agg(
        candidate_count=("product_id", "size"),
        usable_product_count=("product_usable", "sum"),
        suspicious_product_count=("product_suspicious", "sum"),
        missing_product_metadata_count=("product_text_length", lambda s: int(s.isna().sum())),
    )

    query_report = queries.merge(counts, on="query_id", how="left")
    query_report["eligible_for_experiment"] = (
        ~query_report["query_suspicious"]
        & (query_report["usable_product_count"] >= MIN_USABLE_PRODUCTS_PER_QUERY)
    )
    query_report = query_report.sort_values(
        ["eligible_for_experiment", "usable_product_count", "query_id"],
        ascending=[False, False, True],
    )

    suspicious_products = products[products["product_suspicious"]].copy()
    suspicious_products = suspicious_products.sort_values(
        [
            "replacement_char_count",
            "has_mojibake",
            "hangul_count",
            "unusual_char_count",
        ],
        ascending=False,
    ).head(SUSPICIOUS_SAMPLE_LIMIT)

    eligible_queries = query_report[query_report["eligible_for_experiment"]].copy()

    print("5/5 分析結果を保存しています……")
    summary = [
        metric_row("query_product_rows", len(examples), "small_version=1, locale=jp"),
        metric_row("unique_queries", examples["query_id"].nunique()),
        metric_row("unique_products_in_product_table", len(products)),
        metric_row("query_length_min", int(queries["query_length"].min())),
        metric_row("query_length_median", float(queries["query_length"].median())),
        metric_row("query_length_mean", round(float(queries["query_length"].mean()), 2)),
        metric_row("query_length_max", int(queries["query_length"].max())),
        metric_row("suspicious_queries", int(queries["query_suspicious"].sum())),
        metric_row("queries_with_hangul", int((queries["hangul_count"] >= 2).sum())),
        metric_row(
            "queries_with_replacement_or_mojibake",
            int(((queries["replacement_char_count"] > 0) | queries["has_mojibake"]).sum()),
        ),
        metric_row("missing_product_title", int((products["title_length"] == 0).sum())),
        metric_row(
            "missing_product_description",
            int((products["description_length"] == 0).sum()),
        ),
        metric_row("missing_product_bullet", int((products["bullet_length"] == 0).sum())),
        metric_row("products_with_html", int(products["has_html_raw"].sum())),
        metric_row("suspicious_products", int(products["product_suspicious"].sum())),
        metric_row("products_with_hangul", int((products["hangul_count"] >= 2).sum())),
        metric_row(
            "products_with_replacement_or_mojibake",
            int(
                (
                    (products["replacement_char_count"] > 0)
                    | products["has_mojibake"]
                ).sum()
            ),
        ),
        metric_row("usable_products", int(products["product_usable"].sum())),
        metric_row("eligible_queries", len(eligible_queries), "usable products >= 10"),
        metric_row(
            "eligible_train_queries",
            int((eligible_queries["split"] == "train").sum()),
        ),
        metric_row(
            "eligible_test_queries",
            int((eligible_queries["split"] == "test").sum()),
        ),
    ]

    pd.DataFrame(summary).to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    query_report.to_csv(QUERY_REPORT_PATH, index=False, encoding="utf-8-sig")
    suspicious_products[
        [
            "product_id",
            "product_title",
            "product_description",
            "product_bullet_point",
            "product_brand",
            "product_text_clean",
            "replacement_char_count",
            "has_mojibake",
            "hangul_count",
            "japanese_char_count",
            "unusual_char_count",
            "has_html_raw",
            "product_text_length",
        ]
    ].to_csv(SUSPICIOUS_PRODUCTS_PATH, index=False, encoding="utf-8-sig")
    eligible_queries.to_csv(ELIGIBLE_QUERIES_PATH, index=False, encoding="utf-8-sig")

    settings = {
        "min_query_length": MIN_QUERY_LENGTH,
        "min_title_length": MIN_TITLE_LENGTH,
        "min_product_text_length": MIN_PRODUCT_TEXT_LENGTH,
        "min_usable_products_per_query": MIN_USABLE_PRODUCTS_PER_QUERY,
        "hangul_suspicious_threshold": 2,
        "note": "06番では自動削除せず、品質フラグと利用候補だけを作成する。",
    }
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("===== 品質分析結果 =====")
    print(f"日本語クエリ数             : {len(queries):,}")
    print(f"要確認クエリ数             : {int(queries['query_suspicious'].sum()):,}")
    print(f"商品情報数                 : {len(products):,}")
    print(f"要確認商品数               : {int(products['product_suspicious'].sum()):,}")
    print(f"利用可能商品数             : {int(products['product_usable'].sum()):,}")
    print(f"候補10商品を確保できる件数 : {len(eligible_queries):,}")
    print()
    print("保存先:")
    print(f"- {SUMMARY_PATH}")
    print(f"- {QUERY_REPORT_PATH}")
    print(f"- {SUSPICIOUS_PRODUCTS_PATH}")
    print(f"- {ELIGIBLE_QUERIES_PATH}")
    print(f"- {SETTINGS_PATH}")
    print()
    print("この06番ではデータを削除していません。")
    print("CSVを確認してから、07番で正式なクレンジング条件を固定します。")


if __name__ == "__main__":
    main()
