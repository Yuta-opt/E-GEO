from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


DEFAULT_INSTANCES = Path(
    "日本語版データ/TOEIC/04_候補商品/toeic_experiment_instances.json"
)
DEFAULT_RANKINGS = Path(
    "日本語版データ/TOEIC/05_API実験/ranking_results.jsonl"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/06_分析結果")


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl_latest(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"順位結果が見つかりません: {path}\n"
            "APIをまだ実行していない場合は --self-test を付けてください。"
        )

    latest: dict[str, dict[str, Any]] = {}
    invalid_json_lines: list[int] = []
    total_lines = 0
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        total_lines += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            invalid_json_lines.append(line_number)
            continue
        key = str(row.get("job_id") or f"line-{line_number}")
        latest[key] = row

    metadata = {
        "total_nonempty_lines": total_lines,
        "latest_unique_jobs": len(latest),
        "superseded_duplicate_rows": max(total_lines - len(latest) - len(invalid_json_lines), 0),
        "invalid_json_lines": invalid_json_lines,
    }
    return list(latest.values()), metadata


def validate_instances(value: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        raise ValueError("04の実験インスタンスJSONが空です。")

    by_id: dict[str, dict[str, Any]] = {}
    for instance in value:
        intent_id = str(instance.get("intent_id", ""))
        if not intent_id or intent_id in by_id:
            raise ValueError(f"intent_idが空または重複しています: {intent_id}")
        products = instance.get("products", [])
        if len(products) != 10:
            raise ValueError(f"{intent_id}: 候補商品が10件ではありません。")
        target_position = int(instance.get("target_candidate_position", 0))
        target_id = str(instance.get("target_product_id", ""))
        target_matches = [
            product
            for product in products
            if int(product.get("candidate_position", 0)) == target_position
            and str(product.get("product_id", "")) == target_id
        ]
        if len(target_matches) != 1:
            raise ValueError(f"{intent_id}: 対象商品の位置またはIDが不正です。")
        by_id[intent_id] = instance
    return value, by_id


def normalized_ranking(value: Any) -> list[int]:
    ranking = [int(number) for number in value]
    if sorted(ranking) != list(range(1, 11)):
        raise ValueError(f"1〜10の完全な順位ではありません: {ranking}")
    return ranking


def target_rank(ranking: list[int], target_position: int) -> int:
    return ranking.index(target_position) + 1


def make_mock_rankings(
    instances: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """分析コードの動作確認専用。研究結果には使用しない架空順位を作る。"""
    rows: list[dict[str, Any]] = []
    conditions = ("original", "en_zero", "ja_zero")
    forms = ("short", "long")

    for instance_index, instance in enumerate(instances[:limit]):
        target_position = int(instance["target_candidate_position"])
        other_positions = [
            number for number in range(1, 11) if number != target_position
        ]
        initial_rank = 2 + (instance_index % 7)
        base = other_positions.copy()
        base.insert(initial_rank - 1, target_position)

        for form_index, form in enumerate(forms):
            for condition in conditions:
                ranking = base.copy()
                if condition != "original":
                    current = ranking.index(target_position)
                    if condition == "en_zero":
                        movement = 1 if (instance_index + form_index) % 3 != 0 else -1
                    else:
                        movement = 2 if (instance_index + form_index) % 4 != 0 else 0
                    destination = max(0, min(9, current - movement))
                    ranking.pop(current)
                    ranking.insert(destination, target_position)

                rows.append(
                    {
                        "job_id": (
                            f"mock__{instance['intent_id']}__{condition}__{form}"
                        ),
                        "status": "success",
                        "intent_id": instance["intent_id"],
                        "split": instance["split"],
                        "condition": condition,
                        "query_form": form,
                        "target_product_id": instance["target_product_id"],
                        "model": "mock-reranker",
                        "ranking": ranking,
                        "questionable_products": [],
                        "is_mock_data": True,
                    }
                )
    return rows


def build_pair_rows(
    ranking_rows: list[dict[str, Any]],
    instances_by_id: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    failures = [row for row in ranking_rows if row.get("status") != "success"]
    successes = [row for row in ranking_rows if row.get("status") == "success"]
    parsed: list[dict[str, Any]] = []
    invalid_rankings: list[str] = []
    unknown_intents: list[str] = []

    for row in successes:
        intent_id = str(row.get("intent_id", ""))
        instance = instances_by_id.get(intent_id)
        if instance is None:
            unknown_intents.append(intent_id)
            continue
        try:
            ranking = normalized_ranking(row.get("ranking", []))
        except (TypeError, ValueError) as exc:
            invalid_rankings.append(f"{row.get('job_id', '')}: {exc}")
            continue

        target_position = int(instance["target_candidate_position"])
        parsed.append(
            {
                "job_id": row.get("job_id", ""),
                "intent_id": intent_id,
                "split": str(row.get("split") or instance.get("split", "")),
                "category": str(instance.get("category", "")),
                "condition": str(row.get("condition", "")),
                "query_form": str(row.get("query_form", "")),
                "model": str(row.get("model", "")),
                "target_product_id": str(instance["target_product_id"]),
                "target_candidate_position": target_position,
                "target_rank": target_rank(ranking, target_position),
                "target_flagged_questionable": target_position
                in {int(value) for value in row.get("questionable_products", [])},
                "ranking": json.dumps(ranking, ensure_ascii=False),
                "is_mock_data": bool(row.get("is_mock_data", False)),
            }
        )

    rank_frame = pd.DataFrame(parsed)
    if rank_frame.empty:
        raise ValueError("解析できる成功済み順位結果がありません。")

    duplicate_keys = [
        "intent_id", "condition", "query_form", "model"
    ]
    duplicate_count = int(rank_frame.duplicated(duplicate_keys, keep=False).sum())
    if duplicate_count:
        rank_frame = rank_frame.drop_duplicates(duplicate_keys, keep="last")

    original = rank_frame.loc[
        rank_frame["condition"].eq("original"),
        [
            "intent_id",
            "query_form",
            "model",
            "target_rank",
            "target_flagged_questionable",
        ],
    ].rename(
        columns={
            "target_rank": "initial_rank",
            "target_flagged_questionable": "initial_target_flagged",
        }
    )

    compared = rank_frame.loc[~rank_frame["condition"].eq("original")].merge(
        original,
        on=["intent_id", "query_form", "model"],
        how="left",
        validate="many_to_one",
    )
    missing_original = compared.loc[
        compared["initial_rank"].isna(),
        ["intent_id", "condition", "query_form", "model"],
    ].to_dict("records")
    compared = compared.loc[compared["initial_rank"].notna()].copy()
    compared["initial_rank"] = compared["initial_rank"].astype(int)
    compared = compared.rename(columns={"target_rank": "rewritten_rank"})
    compared["rank_improvement"] = (
        compared["initial_rank"] - compared["rewritten_rank"]
    )
    compared["outcome"] = np.select(
        [
            compared["rank_improvement"].gt(0),
            compared["rank_improvement"].lt(0),
        ],
        ["improved", "worsened"],
        default="unchanged",
    )
    compared["reached_top1"] = compared["rewritten_rank"].le(1)
    compared["reached_top3"] = compared["rewritten_rank"].le(3)
    compared["reached_top5"] = compared["rewritten_rank"].le(5)

    integrity = {
        "success_rows": len(successes),
        "failed_rows": len(failures),
        "failure_examples": [
            {
                "job_id": row.get("job_id", ""),
                "error": row.get("error", ""),
            }
            for row in failures[:10]
        ],
        "invalid_ranking_count": len(invalid_rankings),
        "invalid_ranking_examples": invalid_rankings[:10],
        "unknown_intent_count": len(unknown_intents),
        "unknown_intent_examples": unknown_intents[:10],
        "duplicate_comparison_key_rows": duplicate_count,
        "missing_original_count": len(missing_original),
        "missing_original_examples": missing_original[:10],
        "parsed_original_rows": int(rank_frame["condition"].eq("original").sum()),
        "paired_rewrite_rows": int(len(compared)),
        "mock_data_detected": bool(rank_frame["is_mock_data"].any()),
    }
    return compared, integrity


def confidence_interval(values: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(clean) < 2:
        value = float(clean.iloc[0]) if len(clean) == 1 else math.nan
        return value, value
    sem = stats.sem(clean)
    if not np.isfinite(sem) or sem == 0:
        mean = float(clean.mean())
        return mean, mean
    low, high = stats.t.interval(
        confidence=0.95,
        df=len(clean) - 1,
        loc=float(clean.mean()),
        scale=float(sem),
    )
    return float(low), float(high)


def summarize_group(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouper: Any = group_columns[0] if len(group_columns) == 1 else group_columns
    for keys, group in frame.groupby(grouper, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        ci_low, ci_high = confidence_interval(group["rank_improvement"])
        row = dict(zip(group_columns, keys))
        row.update(
            {
                "n": int(len(group)),
                "mean_rank_improvement": float(group["rank_improvement"].mean()),
                "median_rank_improvement": float(group["rank_improvement"].median()),
                "std_rank_improvement": float(group["rank_improvement"].std(ddof=1))
                if len(group) > 1
                else 0.0,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "improvement_rate": float(group["outcome"].eq("improved").mean()),
                "unchanged_rate": float(group["outcome"].eq("unchanged").mean()),
                "worsened_rate": float(group["outcome"].eq("worsened").mean()),
                "mean_initial_rank": float(group["initial_rank"].mean()),
                "mean_rewritten_rank": float(group["rewritten_rank"].mean()),
                "top1_rate_after": float(group["reached_top1"].mean()),
                "top3_rate_after": float(group["reached_top3"].mean()),
                "top5_rate_after": float(group["reached_top5"].mean()),
                "target_flag_rate_after": float(
                    group["target_flagged_questionable"].mean()
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def add_all_split(frame: pd.DataFrame) -> pd.DataFrame:
    combined = frame.copy()
    all_rows = frame.copy()
    all_rows["split"] = "all"
    return pd.concat([combined, all_rows], ignore_index=True)


def make_charts(summary: pd.DataFrame, pairs: pd.DataFrame, output_dir: Path) -> list[str]:
    chart_dir = output_dir / "poster_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    display = summary.loc[
        summary["split"].eq("all")
        & summary["model"].eq(summary["model"].iloc[0])
    ].copy()
    if not display.empty:
        display["label"] = (
            display["condition"].astype(str)
            + " / "
            + display["query_form"].astype(str)
        )
        display = display.sort_values(["condition", "query_form"])
        figure = plt.figure(figsize=(9, 5))
        plt.bar(display["label"], display["mean_rank_improvement"])
        plt.axhline(0, linewidth=1)
        plt.ylabel("Mean rank improvement")
        plt.xlabel("Condition / query form")
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        path = chart_dir / "01_mean_rank_improvement.png"
        figure.savefig(path, dpi=200)
        plt.close(figure)
        outputs.append(str(path))

    figure = plt.figure(figsize=(8, 5))
    bins = np.arange(-9.5, 10.5, 1)
    for condition, group in pairs.groupby("condition", sort=True):
        plt.hist(
            group["rank_improvement"],
            bins=bins,
            alpha=0.5,
            label=str(condition),
        )
    plt.xlabel("Rank improvement")
    plt.ylabel("Number of pairs")
    plt.legend()
    plt.tight_layout()
    path = chart_dir / "02_rank_improvement_distribution.png"
    figure.savefig(path, dpi=200)
    plt.close(figure)
    outputs.append(str(path))
    return outputs


def write_outputs(
    pairs: pd.DataFrame,
    integrity: dict[str, Any],
    output_dir: Path,
    source_metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    expanded = add_all_split(pairs)

    summary = summarize_group(
        expanded,
        ["split", "condition", "query_form", "model"],
    )
    category_summary = summarize_group(
        expanded,
        ["split", "category", "condition", "query_form", "model"],
    )
    condition_summary = summarize_group(
        expanded,
        ["split", "condition", "model"],
    )

    pairs.to_csv(
        output_dir / "pair_level_rank_improvement.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary.to_csv(
        output_dir / "summary_by_condition_and_query_form.csv",
        index=False,
        encoding="utf-8-sig",
    )
    category_summary.to_csv(
        output_dir / "summary_by_category.csv",
        index=False,
        encoding="utf-8-sig",
    )
    condition_summary.to_csv(
        output_dir / "summary_by_condition.csv",
        index=False,
        encoding="utf-8-sig",
    )

    charts = make_charts(summary, pairs, output_dir)
    report = {
        "analysis_status": "mock_self_test"
        if integrity.get("mock_data_detected")
        else "real_api_results",
        "warning": (
            "これは架空順位による分析コードの動作確認です。研究結果として使用しないでください。"
            if integrity.get("mock_data_detected")
            else ""
        ),
        "source_metadata": source_metadata,
        "integrity": integrity,
        "output_files": [
            "pair_level_rank_improvement.csv",
            "summary_by_condition_and_query_form.csv",
            "summary_by_category.csv",
            "summary_by_condition.csv",
            *charts,
        ],
    }
    (output_dir / "analysis_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("06 分析処理が完了しました。")
    print(f"  比較可能な順位ペア: {len(pairs)}件")
    print(
        "  平均順位改善量の範囲: "
        f"{pairs['rank_improvement'].min()}〜{pairs['rank_improvement'].max()}"
    )
    print(f"  出力先: {output_dir}")
    if integrity.get("mock_data_detected"):
        print("  注意: 架空データによる動作確認です。APIは使用していません。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "05の順位結果から、対象商品の書き換え前後の順位改善量を計算し、"
            "集計CSV・検査レポート・ポスター用グラフを作成する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--rankings", type=Path, default=DEFAULT_RANKINGS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="APIを使わず、架空順位で分析コードだけを動作確認する。",
    )
    parser.add_argument(
        "--self-test-limit",
        type=int,
        default=8,
        help="self-testで使う購入意図数。",
    )
    args = parser.parse_args()

    instances, instances_by_id = validate_instances(read_json(args.instances))

    if args.self_test:
        ranking_rows = make_mock_rankings(instances, args.self_test_limit)
        source_metadata = {
            "source": "generated_mock_rankings",
            "intent_count": min(args.self_test_limit, len(instances)),
            "api_calls": 0,
        }
        output_dir = args.output_dir / "動作確認_架空データ"
    else:
        ranking_rows, source_metadata = read_jsonl_latest(args.rankings)
        source_metadata["source"] = str(args.rankings)
        output_dir = args.output_dir / "本実験結果"

    pairs, integrity = build_pair_rows(ranking_rows, instances_by_id)
    write_outputs(pairs, integrity, output_dir, source_metadata)


if __name__ == "__main__":
    main()
