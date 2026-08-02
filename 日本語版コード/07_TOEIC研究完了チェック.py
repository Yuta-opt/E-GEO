from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_INSTANCES = Path(
    "日本語版データ/TOEIC/04_候補商品/08_toeic_experiment_instances.json"
)
DEFAULT_RUN_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行"
)
DEFAULT_ANALYSIS_DIR = Path("日本語版データ/TOEIC/06_分析結果")
DEFAULT_REPORT = Path(
    "日本語版データ/TOEIC/07_本番前チェック/02_research_completion_check.json"
)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONLが見つかりません: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONLを読めません: {path}:{number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONLの各行はobjectである必要があります: {number}")
        rows.append(value)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "候補80件、15プロンプト×8版、Test長文・短文、分析ファイル、"
            "費用上限を確認し、研究数値結果の完成状態を判定する。APIは呼び出さない。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--hard-stop-usd", type=float, default=100.0)
    parser.add_argument(
        "--allow-smoke",
        action="store_true",
        help="正式80件ではなくsmoke出力の構造確認として判定する。",
    )
    args = parser.parse_args()

    instances = read_json(args.instances)
    versions = read_jsonl(args.run_dir / "02_optimization_versions.jsonl")
    final_prompts = read_json(args.run_dir / "03_final_prompts.json")
    test_rows = read_jsonl(args.run_dir / "04_test_results.jsonl")
    run_summary = read_json(args.run_dir / "06_run_summary.json")

    instance_frame = pd.DataFrame(instances)
    test_frame = pd.DataFrame(test_rows)
    version_frame = pd.DataFrame(versions)

    split_counts = (
        instance_frame["split"].value_counts().to_dict()
        if "split" in instance_frame
        else {}
    )
    condition_counts = (
        test_frame["condition"].value_counts().to_dict()
        if "condition" in test_frame
        else {}
    )

    expected_analysis_files = [
        "01_test_summary.csv",
        "02_initial_vs_optimized_paired.csv",
        "03_prompt_convergence.csv",
        "04_prompt_feature_matrix.csv",
        "05_prompt_feature_summary.csv",
        "06_results_summary.json",
        "07_initial_vs_optimized.png",
        "08_long_vs_short.png",
        "09_prompt_convergence.png",
        "10_results_review.xlsx",
    ]
    missing_analysis = [
        name for name in expected_analysis_files if not (args.analysis_dir / name).exists()
    ]

    duplicate_test = False
    if not test_frame.empty:
        key_columns = [
            "condition",
            "prompt_id",
            "intent_id",
            "query_form",
            "reranker_label",
        ]
        duplicate_test = bool(test_frame.duplicated(key_columns).any())

    if args.allow_smoke:
        checks = {
            "instances_available": len(instances) >= 4,
            "at_least_one_prompt": len(final_prompts) >= 1,
            "two_versions_per_smoke_prompt": len(versions) == len(final_prompts) * 2,
            "test_conditions_present": set(condition_counts) == {
                "test_initial_long",
                "test_optimized_long",
                "test_optimized_short",
            },
            "test_rows_unique": not duplicate_test,
            "analysis_complete": not missing_analysis,
            "cost_below_hard_stop": float(
                run_summary.get("total_api_cost_usd_estimate", 0)
            ) < args.hard_stop_usd,
        }
        status = "smoke_complete" if all(checks.values()) else "smoke_incomplete"
    else:
        expected_test_per_condition = 15 * 30 * 1
        checks = {
            "instances_80": len(instances) == 80,
            "split_40_10_30": split_counts == {
                "train": 40,
                "validation": 10,
                "test": 30,
            },
            "final_prompts_15": len(final_prompts) == 15,
            "optimization_versions_120": len(versions) == 15 * 8,
            "each_prompt_has_8_versions": bool(
                not version_frame.empty
                and version_frame.groupby("prompt_id").size().eq(8).all()
            ),
            "test_initial_long_450": int(
                condition_counts.get("test_initial_long", 0)
            ) == expected_test_per_condition,
            "test_optimized_long_450": int(
                condition_counts.get("test_optimized_long", 0)
            ) == expected_test_per_condition,
            "test_optimized_short_450": int(
                condition_counts.get("test_optimized_short", 0)
            ) == expected_test_per_condition,
            "test_rows_1350": len(test_rows) == expected_test_per_condition * 3,
            "test_rows_unique": not duplicate_test,
            "analysis_complete": not missing_analysis,
            "run_status_complete": run_summary.get("status") == "complete",
            "cost_below_hard_stop": float(
                run_summary.get("total_api_cost_usd_estimate", 0)
            ) < args.hard_stop_usd,
        }
        status = "research_numeric_results_complete" if all(checks.values()) else "incomplete"

    report = {
        "status": status,
        "allow_smoke": bool(args.allow_smoke),
        "checks": checks,
        "instance_count": len(instances),
        "split_counts": {str(k): int(v) for k, v in split_counts.items()},
        "optimization_version_count": len(versions),
        "final_prompt_count": len(final_prompts),
        "test_result_count": len(test_rows),
        "test_condition_counts": {
            str(k): int(v) for k, v in condition_counts.items()
        },
        "missing_analysis_files": missing_analysis,
        "estimated_api_cost_usd": float(
            run_summary.get("total_api_cost_usd_estimate", 0)
        ),
        "hard_stop_usd": args.hard_stop_usd,
        "meaning": (
            "research_numeric_results_completeは、数値結果・統計・図表がそろった状態を示す。"
            "ポスター本文の最終解釈とレイアウト確認は別途必要である。"
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("07 研究完了チェック")
    for key, value in checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    print(f"  status: {status}")
    print(f"  report: {args.report}")

    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
