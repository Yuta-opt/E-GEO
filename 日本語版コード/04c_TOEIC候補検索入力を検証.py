from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_REVIEW = Path(
    "日本語版データ/TOEIC/03_購入意図/toeic_query_intents_review.xlsx"
)
DEFAULT_MASTER = Path(
    "日本語版データ/TOEIC/03_購入意図/toeic_query_intents_master.csv"
)
DEFAULT_PRODUCTS = Path(
    "日本語版データ/TOEIC/02_商品プール/toeic_product_pool_final.csv"
)
DEFAULT_RETRIEVAL = Path(
    "日本語版データ/TOEIC/04_候補商品/01_dense_retrieval_top30.csv"
)
DEFAULT_REPORT = Path(
    "日本語版データ/TOEIC/04_候補商品/00_dense_retrieval_input_verification.json"
)


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def read_review(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"正式レビューExcelが見つかりません: {path}")
    frame = pd.read_excel(path, sheet_name="query_intents", dtype=str).fillna("")
    required = [
        "intent_id",
        "short_query_final",
        "long_query_final",
        "review_status",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("レビューExcelに必要な列がありません: " + ", ".join(missing))
    if frame["intent_id"].duplicated().any():
        raise ValueError("レビューExcelのintent_idが重複しています。")
    frame["short_query_final_normalized"] = frame["short_query_final"].map(clean)
    frame["long_query_final_normalized"] = frame["long_query_final"].map(clean)
    return frame


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    ).fillna("")


def compare_master(review: pd.DataFrame, master_path: Path) -> dict[str, Any]:
    if not master_path.exists():
        return {
            "exists": False,
            "note": "master.csvは存在しない。正式入力はreview.xlsxである。",
        }

    master = read_csv(master_path)
    if "intent_id" not in master.columns:
        return {
            "exists": True,
            "comparable": False,
            "reason": "intent_id列がない",
        }

    short_column = (
        "short_query_final"
        if "short_query_final" in master.columns
        else "short_query_draft"
        if "short_query_draft" in master.columns
        else None
    )
    long_column = (
        "long_query_final"
        if "long_query_final" in master.columns
        else "long_query_draft"
        if "long_query_draft" in master.columns
        else None
    )
    if short_column is None or long_column is None:
        return {
            "exists": True,
            "comparable": False,
            "reason": "比較できる短文・長文列がない",
        }

    left = review[
        [
            "intent_id",
            "short_query_final_normalized",
            "long_query_final_normalized",
        ]
    ].copy()
    right = master[["intent_id", short_column, long_column]].copy()
    right["master_short"] = right[short_column].map(clean)
    right["master_long"] = right[long_column].map(clean)
    merged = left.merge(
        right[["intent_id", "master_short", "master_long"]],
        on="intent_id",
        how="outer",
        indicator=True,
    )
    short_diff = merged[
        merged["short_query_final_normalized"].fillna("")
        != merged["master_short"].fillna("")
    ]
    long_diff = merged[
        merged["long_query_final_normalized"].fillna("")
        != merged["master_long"].fillna("")
    ]
    return {
        "exists": True,
        "comparable": True,
        "master_short_column": short_column,
        "master_long_column": long_column,
        "short_query_difference_count": int(len(short_diff)),
        "long_query_difference_count": int(len(long_diff)),
        "note": (
            "差分があってもDense Retrievalの入力には影響しない。"
            "04の正式入力はreview.xlsxである。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dense Retrievalが正式review.xlsxのlong_query_finalと、"
            "最終商品プールのtitle・description_cleanを使ったことを検証する。"
        )
    )
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--retrieval", type=Path, default=DEFAULT_RETRIEVAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    review = read_review(args.review)
    products = read_csv(args.products)
    retrieval = read_csv(args.retrieval)

    approved_count = int(review["review_status"].eq("承認").sum())
    empty_short = int(review["short_query_final_normalized"].eq("").sum())
    empty_long = int(review["long_query_final_normalized"].eq("").sum())

    expected_query = review.set_index("intent_id")[
        "long_query_final_normalized"
    ].to_dict()
    retrieval["query_normalized"] = retrieval["query"].map(clean)
    retrieval["expected_query"] = retrieval["intent_id"].map(expected_query).fillna("")
    query_mismatches = retrieval[
        retrieval["query_normalized"] != retrieval["expected_query"]
    ]

    required_product_columns = ["product_id", "title", "description_clean"]
    missing_product = [c for c in required_product_columns if c not in products.columns]
    missing_retrieval = [c for c in required_product_columns if c not in retrieval.columns]
    if missing_product:
        raise ValueError("商品プールに必要な列がありません: " + ", ".join(missing_product))
    if missing_retrieval:
        raise ValueError("Dense出力に必要な列がありません: " + ", ".join(missing_retrieval))
    if products["product_id"].duplicated().any():
        raise ValueError("商品プールのproduct_idが重複しています。")

    product_lookup = products.set_index("product_id")[["title", "description_clean"]]
    retrieval_check = retrieval.merge(
        product_lookup,
        left_on="product_id",
        right_index=True,
        how="left",
        suffixes=("_retrieval", "_pool"),
        indicator=True,
    )
    retrieval_check["title_matches"] = (
        retrieval_check["title_retrieval"].map(clean)
        == retrieval_check["title_pool"].map(clean)
    )
    retrieval_check["description_matches"] = (
        retrieval_check["description_clean_retrieval"].map(clean)
        == retrieval_check["description_clean_pool"].map(clean)
    )
    product_missing = retrieval_check[retrieval_check["_merge"] != "both"]
    title_mismatches = retrieval_check[~retrieval_check["title_matches"]]
    description_mismatches = retrieval_check[
        ~retrieval_check["description_matches"]
    ]

    query_source_counts = (
        retrieval["query_source"].value_counts().to_dict()
        if "query_source" in retrieval.columns
        else {}
    )

    report = {
        "review_file": str(args.review),
        "master_file": str(args.master),
        "product_pool_file": str(args.products),
        "retrieval_file": str(args.retrieval),
        "review_rows": int(len(review)),
        "approved_rows": approved_count,
        "empty_short_query_final": empty_short,
        "empty_long_query_final": empty_long,
        "retrieval_rows": int(len(retrieval)),
        "retrieval_intents": int(retrieval["intent_id"].nunique()),
        "query_source_counts": {str(k): int(v) for k, v in query_source_counts.items()},
        "query_mismatch_rows": int(len(query_mismatches)),
        "product_id_missing_rows": int(len(product_missing)),
        "title_mismatch_rows": int(len(title_mismatches)),
        "description_mismatch_rows": int(len(description_mismatches)),
        "master_comparison": compare_master(review, args.master),
        "verification_passed": bool(
            len(review) == 80
            and approved_count == 80
            and empty_short == 0
            and empty_long == 0
            and retrieval["intent_id"].nunique() == 80
            and len(retrieval) == 2400
            and len(query_mismatches) == 0
            and len(product_missing) == 0
            and len(title_mismatches) == 0
            and len(description_mismatches) == 0
            and query_source_counts == {"final": 2400}
        ),
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("04c Dense Retrieval入力検証")
    print(f"  review.xlsx: {len(review)}件、承認={approved_count}件")
    print(f"  final空欄: short={empty_short}, long={empty_long}")
    print(f"  Dense出力: {len(retrieval)}行、{retrieval['intent_id'].nunique()}購入意図")
    print(f"  query_source: {query_source_counts}")
    print(f"  reviewのlong_query_finalとの不一致: {len(query_mismatches)}行")
    print(f"  商品ID欠損: {len(product_missing)}行")
    print(f"  商品タイトル不一致: {len(title_mismatches)}行")
    print(f"  商品説明不一致: {len(description_mismatches)}行")
    master_result = report["master_comparison"]
    if master_result.get("exists") and master_result.get("comparable"):
        print(
            "  master.csvとの差: "
            f"short={master_result['short_query_difference_count']}件、"
            f"long={master_result['long_query_difference_count']}件"
        )
    elif not master_result.get("exists"):
        print("  master.csv: なし（正式入力には不使用）")
    else:
        print(f"  master.csv: 比較不可 ({master_result.get('reason', '')})")
    print(f"  検証結果: {'合格' if report['verification_passed'] else '要確認'}")
    print(f"  レポート: {args.report}")

    if not report["verification_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
