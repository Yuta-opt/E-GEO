from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_INPUT = Path(
    "日本語版データ/TOEIC/加工済み/toeic_products_clean.csv"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/実験データ")

REQUIRED_COLUMNS = [
    "product_id",
    "isbn",
    "title",
    "author_clean",
    "price_yen",
    "category_hint",
    "score_hint",
    "release_info",
    "publisher",
    "book_format",
    "series_name",
    "description_clean",
    "description_length",
    "product_url",
    "image_url",
    "needs_review",
    "review_reasons",
]

DISCOUNT_PREFIX_PATTERN = re.compile(
    r"^【(?:謝恩価格本|バーゲン本)】\s*",
    flags=re.IGNORECASE,
)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", normalize_text(value)).casefold()


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def parse_number(value: Any) -> int:
    text = re.sub(r"[^0-9.-]", "", normalize_text(value))
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def same_book_key(title: Any) -> str:
    """
    明確に同じ本だけを検出するためのキー。

    謝恩価格本・バーゲン本の接頭辞だけを除去する。
    「改訂版」「新版」などの版表記は除去しないため、旧版と改訂版は別商品として残る。
    """
    text = normalize_text(title)
    text = DISCOUNT_PREFIX_PATTERN.sub("", text)
    return compact_text(text)


def identity_key(row: pd.Series) -> str:
    """ISBN、商品ID、URLの順で同一レコードを識別する。"""
    isbn = compact_text(row.get("isbn", ""))
    if isbn:
        return f"isbn:{isbn}"

    product_id = compact_text(row.get("product_id", ""))
    if product_id:
        return f"product_id:{product_id}"

    product_url = compact_text(row.get("product_url", ""))
    if product_url:
        return f"url:{product_url}"

    return f"row:{int(row['_source_order'])}"


def description_group_id(value: Any) -> str:
    normalized = compact_text(value)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def choose_group_representative(group: pd.DataFrame) -> int:
    """
    同じ本が通常版と謝恩価格本等で重複した場合、通常版を優先して1件残す。
    版表記の違いは同じグループにならないため、改訂版・旧版には影響しない。
    """
    ranked = group.copy()
    ranked["_discount_listing"] = ranked["title"].map(
        lambda value: bool(DISCOUNT_PREFIX_PATTERN.match(normalize_text(value)))
    )
    ranked = ranked.sort_values(
        ["_discount_listing", "_source_order"],
        ascending=[True, True],
    )
    return int(ranked.index[0])


def build_pool(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    work = raw.copy().fillna("")
    work["_source_order"] = range(len(work))
    work["price_yen_num"] = work["price_yen"].map(parse_number)
    work["description_length_num"] = pd.to_numeric(
        work["description_length"], errors="coerce"
    ).fillna(0).astype(int)
    work["needs_review_bool"] = work["needs_review"].map(parse_bool)
    work["same_book_key"] = work["title"].map(same_book_key)
    work["identity_key"] = work.apply(identity_key, axis=1)
    work["description_group_id"] = work["description_clean"].map(
        description_group_id
    )
    work["revised_exclusion_reason"] = ""

    # 価格がない商品だけを除外する。説明文の文字数、発売年、版、カテゴリは除外条件にしない。
    work.loc[
        work["price_yen_num"].le(0),
        "revised_exclusion_reason",
    ] = "price_missing"

    active = work.loc[work["revised_exclusion_reason"].eq("")].copy()

    # 完全に同じISBN・商品ID・URLの重複を除く。
    for _, group in active.groupby("identity_key", sort=False):
        if len(group) <= 1:
            continue
        keep_idx = int(group.sort_values("_source_order").index[0])
        for idx in group.index:
            if int(idx) != keep_idx:
                work.at[idx, "revised_exclusion_reason"] = "duplicate_identity"

    active = work.loc[work["revised_exclusion_reason"].eq("")].copy()

    # 通常版と謝恩価格本など、タイトル上明確に同じ本だけを1件にする。
    for _, group in active.groupby("same_book_key", sort=False):
        if len(group) <= 1 or not str(group.iloc[0]["same_book_key"]):
            continue
        keep_idx = choose_group_representative(group)
        for idx in group.index:
            if int(idx) != keep_idx:
                work.at[idx, "revised_exclusion_reason"] = "same_book_duplicate"
                work.at[idx, "kept_product_id"] = work.at[keep_idx, "product_id"]
                work.at[idx, "kept_title"] = work.at[keep_idx, "title"]

    final = work.loc[work["revised_exclusion_reason"].eq("")].copy()
    removed = work.loc[work["revised_exclusion_reason"].ne("")].copy()

    # 説明文が同一の別商品は削除せず、確認用フラグだけ付ける。
    final["description_group_size"] = final.groupby(
        "description_group_id"
    )["product_id"].transform("size")
    final["duplicate_description"] = (
        final["description_group_id"].ne("")
        & final["description_group_size"].gt(1)
    )

    # 文字数は分析変数として残すが、対象商品の除外条件には使用しない。
    final["target_eligible_final"] = True
    final["target_ineligible_reasons"] = ""

    # 後続の10番スクリプトとの互換性用。選定には使用しない。
    final["quality_score"] = 0.0
    final["source_pool"] = "revised_all"
    final["source_rank"] = final["_source_order"] + 1

    final = final.sort_values("_source_order").reset_index(drop=True)
    final.insert(0, "final_pool_rank", range(1, len(final) + 1))
    removed = removed.sort_values(
        ["revised_exclusion_reason", "_source_order"]
    ).reset_index(drop=True)

    category_counts = {
        str(key): int(value)
        for key, value in final["category_hint"]
        .value_counts()
        .sort_index()
        .items()
    }

    summary = {
        "input_rows": int(len(work)),
        "price_missing_rows": int(
            work["revised_exclusion_reason"].eq("price_missing").sum()
        ),
        "duplicate_identity_rows": int(
            work["revised_exclusion_reason"].eq("duplicate_identity").sum()
        ),
        "same_book_duplicate_rows": int(
            work["revised_exclusion_reason"].eq("same_book_duplicate").sum()
        ),
        "final_pool_rows": int(len(final)),
        "description_lt_100_rows_retained": int(
            final["description_length_num"].lt(100).sum()
        ),
        "description_100_to_199_rows_retained": int(
            final["description_length_num"].between(100, 199).sum()
        ),
        "description_ge_200_rows_retained": int(
            final["description_length_num"].ge(200).sum()
        ),
        "duplicate_description_rows_retained": int(
            final["duplicate_description"].sum()
        ),
        "category_counts": category_counts,
        "rules": [
            "価格情報がない商品だけを除外",
            "商品説明の文字数は除外条件にしない",
            "古い教材を除外しない",
            "改訂版・旧版・新版を別商品として残す",
            "TOEIC BridgeとSpeaking/Writing教材も候補プールに残す",
            "ISBN・商品ID・URLが同じレコードは重複として除外",
            "謝恩価格本・バーゲン本の接頭辞を除くとタイトルが完全一致する商品は1件に統合",
            "説明文が同じ別商品は削除せずフラグのみ付与",
            "レビュー数・評価点・ランキング・販売実績は使用しない",
        ],
    }
    return final, removed, summary


def final_output_columns(final: pd.DataFrame) -> list[str]:
    preferred = [
        "final_pool_rank",
        "source_pool",
        "source_rank",
        "product_id",
        "isbn",
        "title",
        "author_clean",
        "price_yen_num",
        "category_hint",
        "score_hint",
        "release_info",
        "publisher",
        "book_format",
        "series_name",
        "description_clean",
        "description_length_num",
        "description_group_id",
        "description_group_size",
        "duplicate_description",
        "target_eligible_final",
        "target_ineligible_reasons",
        "quality_score",
        "needs_review_bool",
        "review_reasons",
        "product_url",
        "image_url",
        "same_book_key",
    ]
    return [column for column in preferred if column in final.columns]


def removed_output_columns(removed: pd.DataFrame) -> list[str]:
    preferred = [
        "product_id",
        "isbn",
        "title",
        "price_yen_num",
        "category_hint",
        "description_length_num",
        "revised_exclusion_reason",
        "kept_product_id",
        "kept_title",
        "product_url",
    ]
    return [column for column in preferred if column in removed.columns]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "クレンジング済みTOEIC商品から、文字数・発売年・版を除外条件にせず、"
            "価格欠損と明確な同一商品だけを除いて商品プールを再構成する。"
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(
            f"入力ファイルが見つかりません: {args.input}\n"
            "07_TOEIC商品データクレンジング.pyを先に実行してください。"
        )

    raw = pd.read_csv(
        args.input,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError("必要な列がありません: " + ", ".join(missing))

    final, removed, summary = build_pool(raw)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    final_path = args.output_dir / "toeic_product_pool_final.csv"
    removed_path = args.output_dir / "toeic_product_pool_removed.csv"
    summary_path = args.output_dir / "toeic_product_pool_final_summary.json"
    review_path = args.output_dir / "toeic_product_pool_final_review.xlsx"

    final[final_output_columns(final)].to_csv(
        final_path,
        index=False,
        encoding="utf-8-sig",
    )
    removed[removed_output_columns(removed)].to_csv(
        removed_path,
        index=False,
        encoding="utf-8-sig",
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pd.ExcelWriter(review_path, engine="openpyxl") as writer:
        final[final_output_columns(final)].to_excel(
            writer,
            sheet_name="final_pool",
            index=False,
        )
        removed[removed_output_columns(removed)].to_excel(
            writer,
            sheet_name="removed",
            index=False,
        )
        pd.DataFrame(
            {
                "metric": list(summary.keys()),
                "value": [
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else value
                    for value in summary.values()
                ],
            }
        ).to_excel(writer, sheet_name="summary", index=False)

    print("条件緩和版の商品プール再構成が完了しました。")
    print(f"入力: {len(raw)}件")
    print(f"最終商品プール: {len(final)}件")
    print(f"除外: {len(removed)}件")
    print(f"出力: {final_path}")
    print(f"出力: {removed_path}")
    print(f"出力: {summary_path}")
    print(f"出力: {review_path}")


if __name__ == "__main__":
    main()
