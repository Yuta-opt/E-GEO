from __future__ import annotations

"""07cへリライト共有・接続Smoke・統計補強の検査を追加する。"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


BASE_CHECKER = Path(__file__).with_name(
    "07c_TOEIC費用配分完了チェック.py"
)
DEFAULT_RUN_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)
DEFAULT_ANALYSIS_DIR = Path(
    "日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude"
)
DEFAULT_REPORT = Path(
    "日本語版データ/TOEIC/07_本番前チェック/"
    "05_費用配分研究完了チェック.json"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


checker = load_module(BASE_CHECKER, "toeic_egeo_completion_base")


def argument_path(flag: str, default: Path) -> Path:
    for index, value in enumerate(sys.argv):
        if value == flag and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return default


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONLが見つかりません: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL各行はobjectである必要があります: {number}")
        rows.append(value)
    return rows


def shared_rewrite_check(test_frame: pd.DataFrame) -> dict[str, Any]:
    optimized = test_frame.loc[
        test_frame["condition"].isin(
            ["test_optimized_long", "test_optimized_short"]
        )
    ].copy()
    key_columns = ["prompt_id", "intent_id"]
    long_rows = optimized.loc[
        optimized["condition"].eq("test_optimized_long")
    ]
    short_rows = optimized.loc[
        optimized["condition"].eq("test_optimized_short")
    ]

    long_map = (
        long_rows.groupby(key_columns)
        .agg(
            long_rewrite_job_count=("rewrite_job_id", "nunique"),
            long_text_count=("rewritten_description", "nunique"),
            long_rewrite_job_id=("rewrite_job_id", "first"),
            long_text=("rewritten_description", "first"),
        )
        .reset_index()
    )
    short_map = (
        short_rows.groupby(key_columns)
        .agg(
            short_rewrite_job_count=("rewrite_job_id", "nunique"),
            short_text_count=("rewritten_description", "nunique"),
            short_rewrite_job_id=("rewrite_job_id", "first"),
            short_text=("rewritten_description", "first"),
        )
        .reset_index()
    )
    merged = long_map.merge(
        short_map,
        on=key_columns,
        how="outer",
        indicator=True,
    )
    merged["job_matches"] = (
        merged["long_rewrite_job_id"]
        == merged["short_rewrite_job_id"]
    )
    merged["text_matches"] = merged["long_text"] == merged["short_text"]
    merged["single_rewrite_each_condition"] = (
        merged["long_rewrite_job_count"].eq(1)
        & merged["short_rewrite_job_count"].eq(1)
        & merged["long_text_count"].eq(1)
        & merged["short_text_count"].eq(1)
    )
    passed = bool(
        not merged.empty
        and merged["_merge"].eq("both").all()
        and merged["job_matches"].all()
        and merged["text_matches"].all()
        and merged["single_rewrite_each_condition"].all()
    )
    return {
        "passed": passed,
        "comparison_count": int(len(merged)),
        "missing_pair_count": int((merged["_merge"] != "both").sum()),
        "rewrite_job_mismatch_count": int((~merged["job_matches"]).sum()),
        "rewrite_text_mismatch_count": int((~merged["text_matches"]).sum()),
        "multiple_rewrite_count": int(
            (~merged["single_rewrite_each_condition"]).sum()
        ),
    }


def argv_without_option(values: list[str], flag: str) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(values):
        if values[index] == flag:
            index += 2
            continue
        output.append(values[index])
        index += 1
    return output


def main() -> None:
    run_dir = argument_path("--run-dir", DEFAULT_RUN_DIR)
    analysis_dir = argument_path("--analysis-dir", DEFAULT_ANALYSIS_DIR)
    report_path = argument_path("--report", DEFAULT_REPORT)
    connectivity_dir = argument_path(
        "--connectivity-dir",
        run_dir.parent / "00_API接続Smoke",
    )

    original_argv = list(sys.argv)
    sys.argv = argv_without_option(original_argv, "--connectivity-dir")
    try:
        checker.main()
    finally:
        sys.argv = original_argv

    report = read_json(report_path)
    test_frame = pd.DataFrame(
        read_jsonl(run_dir / "04_test_results.jsonl")
    )
    run_summary = read_json(run_dir / "06_run_summary.json")
    analysis_summary = read_json(
        analysis_dir / "06_results_summary.json"
    )
    paired = pd.read_csv(
        analysis_dir / "02_initial_vs_optimized_paired.csv",
        encoding="utf-8-sig",
    )
    test_summary = pd.read_csv(
        analysis_dir / "01_test_summary.csv",
        encoding="utf-8-sig",
    )
    connectivity = read_json(
        connectivity_dir / "02_connectivity_summary.json"
    )

    rewrite_result = shared_rewrite_check(test_frame)
    patches = run_summary.get("final_safety_patches", {})
    required_paired_columns = {
        "mean_difference_ci95_low",
        "mean_difference_ci95_high",
        "wilcoxon_p_holm_global",
        "significant_holm_global_0_05",
    }
    required_summary_columns = {
        "mean_rank_improvement_ci95_low",
        "mean_rank_improvement_ci95_high",
    }

    extra_checks = {
        "connectivity_smoke_passed": connectivity.get("status") == "passed",
        "optimized_long_short_share_rewrite": rewrite_result["passed"],
        "failed_usage_costed_before_parse": patches.get(
            "failed_response_usage_costed_before_parse"
        )
        is True,
        "gpt5_minimal_reasoning_recorded": patches.get(
            "gpt5_reasoning_effort"
        )
        == "minimal",
        "provider_preflight_hard_stop_recorded": patches.get(
            "provider_preflight_hard_stop"
        )
        is True,
        "paired_ci_and_holm_columns_complete": required_paired_columns.issubset(
            paired.columns
        )
        and not paired[list(required_paired_columns)].isna().any().any(),
        "test_summary_ci_columns_complete": required_summary_columns.issubset(
            test_summary.columns
        )
        and not test_summary[list(required_summary_columns)]
        .isna()
        .any()
        .any(),
        "analysis_summary_records_holm": analysis_summary.get(
            "holm_correction_complete"
        )
        is True,
        "analysis_summary_records_ci95": analysis_summary.get(
            "confidence_intervals_95_complete"
        )
        is True,
        "statistical_method_file_exists": (
            analysis_dir / "12_statistical_inference.json"
        ).exists(),
    }
    final_complete = all(extra_checks.values())

    report["final_safety_checks"] = extra_checks
    report["shared_rewrite_check"] = rewrite_result
    report["connectivity_smoke"] = {
        "status": connectivity.get("status"),
        "provider_cost_usd": connectivity.get("provider_cost_usd", {}),
        "total_cost_usd": connectivity.get("total_cost_usd"),
    }
    if not final_complete:
        report["status"] = "incomplete"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("07d 最終安全完了チェック")
    for key, value in extra_checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    print(
        "  shared rewrite comparisons: "
        f"{rewrite_result['comparison_count']}"
    )
    print(f"  report: {report_path}")
    if not final_complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
