from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_INPUT = Path(
    "日本語版データ/TOEIC/加工済み/toeic_products_clean.csv"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/実験データ")
DEFAULT_POOL_SIZE = 200
DEFAULT_SEED = 20260727

CATEGORY_WEIGHTS = {
    "general": 50,
    "vocabulary": 35,
    "grammar": 30,
    "mock_test": 30,
    "listening": 20,
    "reading": 20,
    "other": 15,
}
EXCLUDED_CATEGORIES = {"bridge", "speaking_writing"}
SEVERE_REVIEW_REASONS = {
    "description_short_lt_100",
    "price_missing",
    "discount_edition",
}

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


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def parse_reasons(value: Any) -> list[str]:
    return [part for part in str(value).split(";") if part]


def add_reason(current: str, reason: str) -> str:
    return reason if not current else f"{current};{reason}"


def scaled_quotas(pool_size: int) -> dict[str, int]:
    """既定の比率を保ったまま、任意の商品プール数へ整数配分する。"""
    if pool_size <= 0:
        raise ValueError("pool_sizeは1以上にしてください。")

    total_weight = sum(CATEGORY_WEIGHTS.values())
    raw = {
        category: pool_size * weight / total_weight
        for category, weight in CATEGORY_WEIGHTS.items()
    }
    quotas = {category: int(value) for category, value in raw.items()}
    remainder = pool_size - sum(quotas.values())

    order = sorted(
        raw,
        key=lambda category: (
            raw[category] - quotas[category],
            CATEGORY_WEIGHTS[category],
        ),
        reverse=True,
    )
    for category in order[:remainder]:
        quotas[category] += 1
    return quotas


def quality_score(row: pd.Series) -> float:
    """
    商品の内容充実度を比較するための機械的な優先度。
    人気度・レビュー・ランキングは使用しない。
    """
    description_length = float(row["description_length_num"])
    score = min(description_length, 2000.0) / 100.0

    if row["price_yen_num"] > 0:
        score += 2.0
    if str(row["author_clean"]).strip():
        score += 1.0
    if row["category_hint"] != "other":
        score += 2.0

    reasons = set(parse_reasons(row["review_reasons"]))
    score -= 2.0 * len(reasons)
    if "description_long_gt_2000" in reasons:
        score += 1.0
    if "publication_series_only" in reasons:
        score += 0.5

    return round(score, 4)


def prepare_candidates(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    work = df.copy().fillna("")

    work["category_hint"] = work["category_hint"].replace("", "other")
    work["description_length_num"] = pd.to_numeric(
        work["description_length"], errors="coerce"
    ).fillna(0).astype(int)
    work["price_yen_num"] = pd.to_numeric(
        work["price_yen"], errors="coerce"
    ).fillna(0).astype(int)
    work["needs_review_bool"] = work["needs_review"].map(parse_bool)

    work["phase_exclusion_reasons"] = ""
    for idx, row in work.iterrows():
        reason = ""

        if row["description_length_num"] < 100:
            reason = add_reason(reason, "description_lt_100")
        if row["price_yen_num"] <= 0:
            reason = add_reason(reason, "price_missing")
        if row["category_hint"] in EXCLUDED_CATEGORIES:
            reason = add_reason(
                reason,
                f"category_{row['category_hint']}_outside_lr_scope",
            )

        review_reasons = set(parse_reasons(row["review_reasons"]))
        for severe_reason in sorted(SEVERE_REVIEW_REASONS & review_reasons):
            reason = add_reason(reason, f"review_{severe_reason}")

        work.at[idx, "phase_exclusion_reasons"] = reason

    work["phase_eligible"] = work["phase_exclusion_reasons"].eq("")
    work["quality_score"] = work.apply(quality_score, axis=1)

    rng = np.random.default_rng(seed)
    work["random_tiebreaker"] = rng.random(len(work))

    work["target_eligible"] = (
        work["phase_eligible"]
        & work["category_hint"].isin(
            [
                "general",
                "vocabulary",
                "grammar",
                "mock_test",
                "listening",
                "reading",
            ]
        )
        & work["description_length_num"].ge(200)
        & ~work["review_reasons"].map(
            lambda value: bool(
                set(parse_reasons(value))
                & {
                    "price_missing",
                    "discount_edition",
                    "description_short_lt_100",
                }
            )
        )
    )

    return work


def select_pool(
    eligible: pd.DataFrame,
    pool_size: int,
    quotas: dict[str, int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(eligible) < pool_size:
        raise ValueError(
            f"商品プール候補が不足しています。候補={len(eligible)}件、"
            f"必要={pool_size}件"
        )

    ordered = eligible.sort_values(
        ["category_hint", "quality_score", "random_tiebreaker", "product_id"],
        ascending=[True, False, True, True],
    ).copy()

    selected_indices: list[int] = []
    selection_reason: dict[int, str] = {}

    for category, quota in quotas.items():
        category_rows = ordered.loc[
            (ordered["category_hint"] == category)
            & ~ordered.index.isin(selected_indices)
        ]
        chosen = category_rows.head(quota)
        for idx in chosen.index:
            selected_indices.append(idx)
            selection_reason[idx] = f"category_quota:{category}"

    remaining = pool_size - len(selected_indices)
    if remaining > 0:
        fill = ordered.loc[~ordered.index.isin(selected_indices)].sort_values(
            ["quality_score", "random_tiebreaker", "product_id"],
            ascending=[False, True, True],
        ).head(remaining)
        for idx in fill.index:
            selected_indices.append(idx)
            selection_reason[idx] = "quality_fill"

    selected = ordered.loc[selected_indices].copy()
    selected["selection_reason"] = selected.index.map(selection_reason)
    selected = selected.sort_values(
        ["category_hint", "quality_score", "random_tiebreaker", "product_id"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
    selected.insert(0, "pool_rank", range(1, len(selected) + 1))

    holdout = ordered.loc[~ordered.index.isin(selected_indices)].copy()
    holdout = holdout.sort_values(
        ["quality_score", "random_tiebreaker", "product_id"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    holdout.insert(0, "holdout_rank", range(1, len(holdout) + 1))

    return selected, holdout


def reason_counts(series: pd.Series) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in series:
        counts.update(parse_reasons(value))
    return dict(sorted(counts.items()))


def output_columns(prefix: str) -> list[str]:
    first = "pool_rank" if prefix == "selected" else "holdout_rank"
    columns = [
        first,
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
        "target_eligible",
        "quality_score",
        "needs_review_bool",
        "review_reasons",
        "product_url",
        "image_url",
    ]
    if prefix == "selected":
        target_position = columns.index("target_eligible") + 1
        columns.insert(target_position, "selection_reason")
    return columns


def main() -> None:
    parser = argparse.ArgumentParser(
        description="クレンジング済みTOEIC商品から実験用の商品プールを固定する。"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
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

    prepared = prepare_candidates(raw, seed=args.seed)
    eligible = prepared.loc[prepared["phase_eligible"]].copy()
    phase_excluded = prepared.loc[~prepared["phase_eligible"]].copy()

    quotas = scaled_quotas(args.pool_size)
    selected, holdout = select_pool(
        eligible=eligible,
        pool_size=args.pool_size,
        quotas=quotas,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    selected_path = args.output_dir / f"toeic_product_pool_{args.pool_size}.csv"
    holdout_path = args.output_dir / "toeic_product_pool_holdout.csv"
    excluded_path = args.output_dir / "toeic_product_pool_phase_excluded.csv"
    summary_path = args.output_dir / "toeic_product_pool_summary.json"
    workbook_path = args.output_dir / "toeic_product_pool_review.xlsx"

    selected[output_columns("selected")].to_csv(
        selected_path,
        index=False,
        encoding="utf-8-sig",
    )
    holdout[output_columns("holdout")].to_csv(
        holdout_path,
        index=False,
        encoding="utf-8-sig",
    )

    phase_excluded_columns = [
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
        "review_reasons",
        "phase_exclusion_reasons",
        "product_url",
    ]
    phase_excluded[phase_excluded_columns].to_csv(
        excluded_path,
        index=False,
        encoding="utf-8-sig",
    )

    categories = sorted(
        set(CATEGORY_WEIGHTS)
        | set(eligible["category_hint"].unique())
        | set(selected["category_hint"].unique())
    )
    category_summary = pd.DataFrame(
        {
            "category": categories,
            "clean_count": [
                int((prepared["category_hint"] == category).sum())
                for category in categories
            ],
            "eligible_count": [
                int((eligible["category_hint"] == category).sum())
                for category in categories
            ],
            "requested_quota": [
                int(quotas.get(category, 0)) for category in categories
            ],
            "selected_count": [
                int((selected["category_hint"] == category).sum())
                for category in categories
            ],
            "target_eligible_count": [
                int(
                    (
                        (selected["category_hint"] == category)
                        & selected["target_eligible"]
                    ).sum()
                )
                for category in categories
            ],
        }
    )

    summary = {
        "input_file": str(args.input),
        "seed": args.seed,
        "requested_pool_size": args.pool_size,
        "clean_rows": int(len(prepared)),
        "phase_eligible_rows": int(len(eligible)),
        "phase_excluded_rows": int(len(phase_excluded)),
        "selected_rows": int(len(selected)),
        "holdout_rows": int(len(holdout)),
        "selected_target_eligible_rows": int(selected["target_eligible"].sum()),
        "requested_category_quotas": quotas,
        "selected_category_counts": {
            str(key): int(value)
            for key, value in selected["category_hint"]
            .value_counts()
            .sort_index()
            .items()
        },
        "phase_exclusion_reason_counts": reason_counts(
            phase_excluded["phase_exclusion_reasons"]
        ),
        "selection_rules": [
            "商品説明100文字以上",
            "価格情報あり",
            "TOEIC BridgeとSpeaking/WritingはL&R主実験の対象外",
            "カテゴリ別の固定比率を優先",
            "カテゴリ不足分はquality_score上位から補充",
            "乱数シードを固定し、同じ入力から同じ200商品を再現",
            "レビュー数・評価点・ランキング・販売実績は使用しない",
        ],
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        selected[output_columns("selected")].to_excel(
            writer,
            sheet_name="selected_200",
            index=False,
        )
        holdout[output_columns("holdout")].to_excel(
            writer,
            sheet_name="holdout",
            index=False,
        )
        phase_excluded[phase_excluded_columns].to_excel(
            writer,
            sheet_name="phase_excluded",
            index=False,
        )
        category_summary.to_excel(
            writer,
            sheet_name="category_summary",
            index=False,
        )

    print("TOEIC実験用の商品プールを作成しました。")
    print(f"  clean入力: {len(prepared)}件")
    print(f"  商品プール候補: {len(eligible)}件")
    print(f"  商品プール段階の除外: {len(phase_excluded)}件")
    print(f"  固定商品プール: {len(selected)}件")
    print(f"  予備商品: {len(holdout)}件")
    print(f"  対象商品候補: {int(selected['target_eligible'].sum())}件")
    print("  カテゴリ構成:")
    for category, count in (
        selected["category_hint"].value_counts().sort_index().items()
    ):
        print(f"    {category}: {count}件")
    print(f"  出力: {selected_path}")
    print(f"        {holdout_path}")
    print(f"        {excluded_path}")
    print(f"        {summary_path}")
    print(f"        {workbook_path}")


if __name__ == "__main__":
    main()
