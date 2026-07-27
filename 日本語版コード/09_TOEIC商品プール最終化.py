from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SELECTED = Path(
    "日本語版データ/TOEIC/実験データ/toeic_product_pool_200.csv"
)
DEFAULT_HOLDOUT = Path(
    "日本語版データ/TOEIC/実験データ/toeic_product_pool_holdout.csv"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/実験データ")
SOURCE_DATE = date(2026, 7, 27)

EDITION_PATTERN = re.compile(
    r"増補改訂版|完全改訂版|改訂新版|改訂版|新装版|新版",
    flags=re.IGNORECASE,
)
LEGACY_TITLE_PATTERN = re.compile(r"新\s*TOEIC\s*TEST", flags=re.IGNORECASE)


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def normalize_spaces(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def normalize_description(value: Any) -> str:
    return normalize_spaces(value).casefold()


def description_group_id(value: Any) -> str:
    normalized = normalize_description(value)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def base_title_key(value: Any) -> str:
    text = normalize_spaces(value).casefold()
    text = EDITION_PATTERN.sub(" ", text)
    text = re.sub(r"\[[^\]]*?\]|\([^)]*?\)|（[^）]*?）", " ", text)
    text = re.sub(
        r"toeic|listening\s*&\s*reading|l\s*&\s*r|test|テスト|®",
        " ",
        text,
    )
    return re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", "", text)


def extract_release_date(value: Any) -> date | None:
    text = normalize_spaces(value)
    full = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if full:
        year, month, day = map(int, full.groups())
        return date(year, month, day)
    month_only = re.search(r"(\d{4})年(\d{1,2})月", text)
    if month_only:
        year, month = map(int, month_only.groups())
        return date(year, month, 1)
    return None


def release_year(value: Any) -> int | None:
    match = re.search(r"(\d{4})年", normalize_spaces(value))
    return int(match.group(1)) if match else None


def edition_score(title: str) -> int:
    scores = {
        "増補改訂版": 6,
        "完全改訂版": 5,
        "改訂新版": 5,
        "新装版": 4,
        "改訂版": 3,
        "新版": 2,
    }
    return max(
        (score for word, score in scores.items() if word in title),
        default=0,
    )


def add_reason(current: str, reason: str) -> str:
    return reason if not current else f"{current};{reason}"


def load_pool(path: Path, source_pool: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {path}")
    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    df["source_pool"] = source_pool
    if "pool_rank" in df.columns:
        df["source_rank"] = df["pool_rank"]
    elif "holdout_rank" in df.columns:
        df["source_rank"] = df["holdout_rank"]
    else:
        df["source_rank"] = ""
    if "selection_reason" not in df.columns:
        df["selection_reason"] = ""
    return df


def mark_removals(combined: pd.DataFrame) -> pd.DataFrame:
    work = combined.copy().fillna("")
    work["release_date_parsed"] = work["release_info"].map(
        extract_release_date
    )
    work["release_year_parsed"] = work["release_info"].map(release_year)
    work["base_title_key"] = work["title"].map(base_title_key)
    work["description_group_id"] = work["description_clean"].map(
        description_group_id
    )
    work["removal_reasons"] = ""

    for idx, row in work.iterrows():
        reason = ""
        release_date = row["release_date_parsed"]
        year = row["release_year_parsed"]
        title = row["title"]

        if isinstance(release_date, date) and release_date > SOURCE_DATE:
            reason = add_reason(reason, "release_after_collection_date")
        if pd.notna(year) and int(year) < 2016:
            reason = add_reason(reason, "legacy_pre_2016")
        if (
            LEGACY_TITLE_PATTERN.search(title)
            and "L&R" not in title
            and "Listening & Reading" not in title
        ):
            reason = add_reason(reason, "legacy_new_toeic_test_title")

        work.at[idx, "removal_reasons"] = reason

    active = work.loc[work["removal_reasons"].eq("")].copy()
    duplicate_groups = active.groupby(
        ["base_title_key", "description_group_id"],
        dropna=False,
    )
    for (_, description_id), group in duplicate_groups:
        if len(group) <= 1 or not description_id:
            continue
        ranked = group.copy()
        ranked["_edition_score"] = ranked["title"].map(edition_score)
        ranked["_release_ordinal"] = ranked["release_date_parsed"].map(
            lambda value: value.toordinal()
            if isinstance(value, date)
            else 0
        )
        ranked["_quality"] = pd.to_numeric(
            ranked["quality_score"], errors="coerce"
        ).fillna(0.0)
        ranked["_selected_preference"] = ranked["source_pool"].eq(
            "selected"
        ).astype(int)
        ranked = ranked.sort_values(
            [
                "_edition_score",
                "_release_ordinal",
                "_quality",
                "_selected_preference",
                "product_id",
            ],
            ascending=[False, False, False, False, True],
        )
        keep_idx = ranked.index[0]
        for idx in ranked.index[1:]:
            work.at[idx, "removal_reasons"] = add_reason(
                work.at[idx, "removal_reasons"],
                "superseded_duplicate_edition",
            )
        work.at[keep_idx, "edition_group_representative"] = True

    work["is_removed"] = work["removal_reasons"].ne("")
    return work


def finalize_pool(
    marked: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    final = marked.loc[~marked["is_removed"]].copy()
    removed = marked.loc[marked["is_removed"]].copy()

    final["description_group_size"] = final.groupby(
        "description_group_id"
    )["product_id"].transform("size")
    final["duplicate_description"] = final[
        "description_group_size"
    ].gt(1)

    original_target = final["target_eligible"].map(parse_bool)
    final["target_eligible_final"] = (
        original_target
        & ~final["duplicate_description"]
        & pd.to_numeric(
            final["description_length_num"], errors="coerce"
        )
        .fillna(0)
        .ge(200)
    )
    final["target_ineligible_reasons"] = ""
    for idx, row in final.iterrows():
        reason = ""
        if not parse_bool(row["target_eligible"]):
            reason = add_reason(reason, "original_target_ineligible")
        if row["duplicate_description"]:
            reason = add_reason(reason, "duplicate_description_group")
        if int(float(row["description_length_num"] or 0)) < 200:
            reason = add_reason(reason, "description_lt_200")
        final.at[idx, "target_ineligible_reasons"] = reason

    final["_quality"] = pd.to_numeric(
        final["quality_score"], errors="coerce"
    ).fillna(0.0)
    final = final.sort_values(
        [
            "category_hint",
            "target_eligible_final",
            "_quality",
            "source_pool",
            "product_id",
        ],
        ascending=[True, False, False, True, True],
    ).reset_index(drop=True)
    final.insert(0, "final_pool_rank", range(1, len(final) + 1))
    final = final.drop(columns=["_quality"])

    removed = removed.sort_values(
        ["removal_reasons", "category_hint", "title"]
    ).reset_index(drop=True)
    return final, removed


def output_columns() -> list[str]:
    return [
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
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "TOEIC商品プールを発売日・旧形式・重複説明の観点から"
            "最終化する。"
        )
    )
    parser.add_argument("--selected", type=Path, default=DEFAULT_SELECTED)
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    selected = load_pool(args.selected, "selected")
    holdout = load_pool(args.holdout, "holdout")
    combined = pd.concat([selected, holdout], ignore_index=True, sort=False)
    marked = mark_removals(combined)
    final, removed = finalize_pool(marked)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    final_path = args.output_dir / "toeic_product_pool_final.csv"
    removed_path = args.output_dir / "toeic_product_pool_removed.csv"
    duplicate_path = (
        args.output_dir / "toeic_product_pool_duplicate_descriptions.csv"
    )
    summary_path = (
        args.output_dir / "toeic_product_pool_final_summary.json"
    )
    review_path = args.output_dir / "toeic_product_pool_final_review.xlsx"

    final[output_columns()].to_csv(
        final_path,
        index=False,
        encoding="utf-8-sig",
    )

    removed_columns = [
        "source_pool",
        "source_rank",
        "product_id",
        "isbn",
        "title",
        "release_info",
        "category_hint",
        "description_length_num",
        "removal_reasons",
        "product_url",
    ]
    removed[removed_columns].to_csv(
        removed_path,
        index=False,
        encoding="utf-8-sig",
    )

    duplicate_rows = final.loc[final["duplicate_description"]].copy()
    duplicate_rows[output_columns()].to_csv(
        duplicate_path,
        index=False,
        encoding="utf-8-sig",
    )

    category_counts = {
        str(key): int(value)
        for key, value in final["category_hint"]
        .value_counts()
        .sort_index()
        .items()
    }
    target_category_counts = {
        str(key): int(value)
        for key, value in final.loc[
            final["target_eligible_final"],
            "category_hint",
        ]
        .value_counts()
        .sort_index()
        .items()
    }
    removal_reason_counts: dict[str, int] = {}
    for value in removed["removal_reasons"]:
        for reason in str(value).split(";"):
            if reason:
                removal_reason_counts[reason] = (
                    removal_reason_counts.get(reason, 0) + 1
                )

    summary = {
        "source_date": SOURCE_DATE.isoformat(),
        "selected_input_rows": int(len(selected)),
        "holdout_input_rows": int(len(holdout)),
        "combined_rows": int(len(combined)),
        "final_pool_rows": int(len(final)),
        "removed_rows": int(len(removed)),
        "final_target_eligible_rows": int(
            final["target_eligible_final"].sum()
        ),
        "duplicate_description_rows": int(
            final["duplicate_description"].sum()
        ),
        "category_counts": category_counts,
        "target_category_counts": target_category_counts,
        "removal_reason_counts": dict(
            sorted(removal_reason_counts.items())
        ),
        "rules": [
            "収集日より後に発売される商品を候補プールから除外",
            "2016年より前の商品を旧形式候補として除外",
            "L&R表記がない「新TOEIC TEST」商品を旧形式候補として除外",
            "同一説明・同一基本タイトルの版違いは改訂版を優先",
            "説明文が完全一致する複数商品は候補には残すが対象商品には使用しない",
            "holdoutの商品も条件を満たす場合は最終候補へ追加",
        ],
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pd.ExcelWriter(review_path, engine="openpyxl") as writer:
        final[output_columns()].to_excel(
            writer,
            sheet_name="final_pool",
            index=False,
        )
        removed[removed_columns].to_excel(
            writer,
            sheet_name="removed",
            index=False,
        )
        duplicate_rows[output_columns()].to_excel(
            writer,
            sheet_name="duplicate_descriptions",
            index=False,
        )
        pd.DataFrame(
            {
                "metric": [
                    "final_pool_rows",
                    "removed_rows",
                    "final_target_eligible_rows",
                    "duplicate_description_rows",
                ],
                "value": [
                    len(final),
                    len(removed),
                    int(final["target_eligible_final"].sum()),
                    int(final["duplicate_description"].sum()),
                ],
            }
        ).to_excel(writer, sheet_name="summary", index=False)

    print("TOEIC商品プールの最終化が完了しました。")
    print(f"  入力（selected）: {len(selected)}件")
    print(f"  入力（holdout）: {len(holdout)}件")
    print(f"  最終候補プール: {len(final)}件")
    print(f"  除外: {len(removed)}件")
    print(
        "  対象商品候補: "
        f"{int(final['target_eligible_final'].sum())}件"
    )
    print(
        "  説明文完全一致の商品: "
        f"{int(final['duplicate_description'].sum())}件"
    )
    print(f"  出力: {final_path}")
    print(f"        {removed_path}")
    print(f"        {duplicate_path}")
    print(f"        {summary_path}")
    print(f"        {review_path}")


if __name__ == "__main__":
    main()
