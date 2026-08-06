from __future__ import annotations

"""06bの出力へ95% bootstrap CIとHolm補正を追加する最終統計ラッパー。"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests


BASE_ANALYSIS = Path(__file__).with_name(
    "06b_TOEIC先行研究準拠結果分析.py"
)
DEFAULT_RUN_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


analysis = load_module(BASE_ANALYSIS, "toeic_egeo_analysis_base")


def argument_path(flag: str, default: Path) -> Path:
    for index, value in enumerate(sys.argv):
        if value == flag and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return default


def stable_seed(*parts: str) -> int:
    raw = "\n".join(parts).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def bootstrap_mean_ci(
    values: np.ndarray,
    *,
    seed: int,
    resamples: int = 10_000,
) -> tuple[float, float]:
    clean = np.asarray(values, dtype=np.float64)
    clean = clean[np.isfinite(clean)]
    if len(clean) == 0:
        return float("nan"), float("nan")
    if len(clean) == 1:
        value = float(clean[0])
        return value, value
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(clean), size=(resamples, len(clean)))
    means = clean[indexes].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def add_test_summary_ci(
    test_frame: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    group_columns = [
        "condition",
        "query_form",
        "prompt_id",
        "reranker_label",
        "reranker_model",
    ]
    ci_map: dict[tuple[str, ...], tuple[float, float]] = {}
    for keys, group in test_frame.groupby(group_columns, dropna=False):
        key = tuple(str(item) for item in keys)
        values = pd.to_numeric(
            group["rank_improvement"],
            errors="coerce",
        ).dropna().to_numpy(dtype=np.float64)
        ci_map[key] = bootstrap_mean_ci(
            values,
            seed=stable_seed(*key),
        )

    output = summary.copy()
    lows: list[float] = []
    highs: list[float] = []
    for row in output.itertuples(index=False):
        key = tuple(str(getattr(row, column)) for column in group_columns)
        low, high = ci_map[key]
        lows.append(low)
        highs.append(high)
    output["mean_rank_improvement_ci95_low"] = lows
    output["mean_rank_improvement_ci95_high"] = highs
    output["ci_method"] = "percentile bootstrap, 10000 resamples"
    return output


def paired_difference_groups(
    test_frame: pd.DataFrame,
) -> dict[tuple[str, str], np.ndarray]:
    long_frame = test_frame.loc[
        test_frame["condition"].isin(
            ["test_initial_long", "test_optimized_long"]
        )
    ].copy()
    pivot = long_frame.pivot_table(
        index=["prompt_id", "reranker_label", "intent_id"],
        columns="condition",
        values="rank_improvement",
        aggfunc="first",
    ).reset_index()
    required = ["test_initial_long", "test_optimized_long"]
    for column in required:
        if column not in pivot:
            pivot[column] = np.nan
    pivot = pivot.dropna(subset=required)
    pivot["difference"] = (
        pivot["test_optimized_long"] - pivot["test_initial_long"]
    )
    groups: dict[tuple[str, str], np.ndarray] = {}
    for (prompt_id, reranker), group in pivot.groupby(
        ["prompt_id", "reranker_label"],
        dropna=False,
    ):
        groups[(str(prompt_id), str(reranker))] = pd.to_numeric(
            group["difference"],
            errors="coerce",
        ).dropna().to_numpy(dtype=np.float64)
    return groups


def add_paired_inference(
    test_frame: pd.DataFrame,
    paired: pd.DataFrame,
) -> pd.DataFrame:
    output = paired.copy()
    groups = paired_difference_groups(test_frame)
    lows: list[float] = []
    highs: list[float] = []
    for row in output.itertuples(index=False):
        key = (str(row.prompt_id), str(row.reranker_label))
        low, high = bootstrap_mean_ci(
            groups[key],
            seed=stable_seed(*key, "paired_difference"),
        )
        lows.append(low)
        highs.append(high)
    output["mean_difference_ci95_low"] = lows
    output["mean_difference_ci95_high"] = highs
    output["ci_method"] = "percentile bootstrap, 10000 resamples"

    p_values = pd.to_numeric(
        output["wilcoxon_p_value"],
        errors="raise",
    ).to_numpy(dtype=np.float64)
    _, adjusted, _, _ = multipletests(
        p_values,
        alpha=0.05,
        method="holm",
    )
    output["wilcoxon_p_holm_global"] = adjusted
    output["significant_holm_global_0_05"] = adjusted < 0.05

    output["wilcoxon_p_holm_within_reranker"] = np.nan
    output["significant_holm_within_reranker_0_05"] = False
    for _, indexes in output.groupby("reranker_label").groups.items():
        index_list = list(indexes)
        local_p = p_values[index_list]
        _, local_adjusted, _, _ = multipletests(
            local_p,
            alpha=0.05,
            method="holm",
        )
        output.loc[
            index_list,
            "wilcoxon_p_holm_within_reranker",
        ] = local_adjusted
        output.loc[
            index_list,
            "significant_holm_within_reranker_0_05",
        ] = local_adjusted < 0.05
    return output


def replace_workbook_sheets(
    path: Path,
    test_summary: pd.DataFrame,
    paired: pd.DataFrame,
) -> None:
    with pd.ExcelWriter(
        path,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace",
    ) as writer:
        test_summary.to_excel(
            writer,
            sheet_name="test_summary",
            index=False,
        )
        paired.to_excel(
            writer,
            sheet_name="paired_test",
            index=False,
        )


def main() -> None:
    run_dir = argument_path("--run-dir", DEFAULT_RUN_DIR)
    output_dir = argument_path("--output-dir", DEFAULT_OUTPUT_DIR)

    analysis.main()

    test_rows = analysis.read_jsonl(run_dir / "04_test_results.jsonl")
    test_frame = pd.DataFrame(test_rows)
    test_frame["rank_improvement"] = pd.to_numeric(
        test_frame["rank_improvement"],
        errors="raise",
    )
    test_summary_path = output_dir / "01_test_summary.csv"
    paired_path = output_dir / "02_initial_vs_optimized_paired.csv"
    test_summary = pd.read_csv(test_summary_path, encoding="utf-8-sig")
    paired = pd.read_csv(paired_path, encoding="utf-8-sig")

    test_summary = add_test_summary_ci(test_frame, test_summary)
    paired = add_paired_inference(test_frame, paired)
    test_summary.to_csv(
        test_summary_path,
        index=False,
        encoding="utf-8-sig",
    )
    paired.to_csv(
        paired_path,
        index=False,
        encoding="utf-8-sig",
    )

    review_path = output_dir / "10_results_review.xlsx"
    replace_workbook_sheets(review_path, test_summary, paired)

    method_summary = {
        "confidence_interval": {
            "level": 0.95,
            "method": "percentile bootstrap",
            "resamples": 10000,
            "unit": "Test intent",
            "seed_rule": "deterministic SHA-256 by comparison key",
        },
        "multiple_testing": {
            "raw_test": "paired Wilcoxon signed-rank",
            "correction": "Holm",
            "global_family_size": int(len(paired)),
            "within_reranker_families": {
                str(key): int(value)
                for key, value in paired["reranker_label"]
                .value_counts()
                .to_dict()
                .items()
            },
        },
    }
    (output_dir / "12_statistical_inference.json").write_text(
        json.dumps(method_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_path = output_dir / "06_results_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["statistical_inference"] = method_summary
    summary["holm_correction_complete"] = True
    summary["confidence_intervals_95_complete"] = True
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("06c 最終統計補強完了")
    print(f"  Holm補正対象: {len(paired)}比較")
    print("  95% CI: Test平均と初期対最適化の平均差へ追加")
    print(f"  出力先: {output_dir}")


if __name__ == "__main__":
    main()
