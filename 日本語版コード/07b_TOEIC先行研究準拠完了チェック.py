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
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)
DEFAULT_ANALYSIS_DIR = Path(
    "日本語版データ/TOEIC/06_分析結果/02_OpenAI_Gemini_Claude"
)
DEFAULT_REPORT = Path(
    "日本語版データ/TOEIC/07_本番前チェック/"
    "04_先行研究準拠研究完了チェック.json"
)


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
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONLを読めません: {path}:{number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL各行はobjectである必要があります: {number}")
        rows.append(value)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "正式80件、15×8版、3 Held-outモデル、先行研究準拠パッチ、"
            "text-embedding-3-large分析、人手特徴評価状態を検査する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--hard-stop-usd", type=float, default=100.0)
    parser.add_argument("--expected-heldout-count", type=int, default=3)
    parser.add_argument("--require-manual-features", action="store_true")
    args = parser.parse_args()

    instances = read_json(args.instances)
    versions = read_jsonl(args.run_dir / "02_optimization_versions.jsonl")
    final_prompts = read_json(args.run_dir / "03_final_prompts.json")
    test_rows = read_jsonl(args.run_dir / "04_test_results.jsonl")
    run_summary = read_json(args.run_dir / "06_run_summary.json")
    analysis_summary = read_json(args.analysis_dir / "06_results_summary.json")

    instance_frame = pd.DataFrame(instances)
    version_frame = pd.DataFrame(versions)
    test_frame = pd.DataFrame(test_rows)

    split_counts = instance_frame["split"].value_counts().to_dict()
    condition_counts = test_frame["condition"].value_counts().to_dict()
    heldout_labels = sorted(
        test_frame["reranker_label"].astype(str).unique().tolist()
    )
    heldout_models = sorted(
        test_frame["reranker_model"].astype(str).unique().tolist()
    )
    expected_per_condition = 15 * 30 * args.expected_heldout_count

    key_columns = [
        "condition",
        "prompt_id",
        "intent_id",
        "query_form",
        "reranker_label",
    ]
    duplicate_test = bool(test_frame.duplicated(key_columns).any())

    required_analysis_files = [
        "01_test_summary.csv",
        "02_initial_vs_optimized_paired.csv",
        "03_prompt_convergence_trajectory.csv",
        "03b_prompt_trajectory.csv",
        "04_prompt_feature_manual_review.xlsx",
        "06_results_summary.json",
        "07_initial_vs_optimized.png",
        "08_long_vs_short.png",
        "09_prompt_convergence.png",
        "10_results_review.xlsx",
        "11_embedding_cache.jsonl",
    ]
    missing_analysis = [
        name
        for name in required_analysis_files
        if not (args.analysis_dir / name).exists()
    ]

    compliance = run_summary.get("prior_study_compliance", {})
    meta_history_description = str(
        compliance.get("meta_optimizer_history", "")
    ).lower()
    manual_complete = bool(
        analysis_summary.get("manual_feature_scoring_complete", False)
    )

    checks = {
        "instances_80": len(instances) == 80,
        "split_40_10_30": split_counts
        == {"train": 40, "validation": 10, "test": 30},
        "final_prompts_15": len(final_prompts) == 15,
        "optimization_versions_120": len(versions) == 15 * 8,
        "each_prompt_has_8_versions": bool(
            not version_frame.empty
            and version_frame.groupby("prompt_id").size().eq(8).all()
        ),
        "heldout_reranker_count_3": len(heldout_labels)
        == args.expected_heldout_count,
        "test_initial_long_expected": int(
            condition_counts.get("test_initial_long", 0)
        )
        == expected_per_condition,
        "test_optimized_long_expected": int(
            condition_counts.get("test_optimized_long", 0)
        )
        == expected_per_condition,
        "test_optimized_short_expected": int(
            condition_counts.get("test_optimized_short", 0)
        )
        == expected_per_condition,
        "test_rows_expected": len(test_rows) == expected_per_condition * 3,
        "test_rows_unique": not duplicate_test,
        "validation_not_visible_to_meta_optimizer": compliance.get(
            "validation_visible_to_meta_optimizer"
        )
        is False,
        "train_prompt_and_per_engine_history": (
            "training" in meta_history_description
            and "per-engine" in meta_history_description
            and "prompt" in meta_history_description
        ),
        "model_family_system_prompts": "model-family-specific"
        in str(compliance.get("reranker_system_prompts", "")),
        "rewriter_uses_listing_text": compliance.get("rewriter_input")
        == "target listing title + description; query blind",
        "embedding_model_matches_paper": analysis_summary.get(
            "embedding_model"
        )
        == "text-embedding-3-large",
        "automatic_keyword_feature_scoring_disabled": analysis_summary.get(
            "automatic_keyword_feature_scoring_used"
        )
        is False,
        "analysis_files_complete": not missing_analysis,
        "run_status_complete": run_summary.get("status") == "complete",
        "cost_below_hard_stop": float(
            run_summary.get("total_api_cost_usd_estimate", 0)
        )
        < args.hard_stop_usd,
    }
    if args.require_manual_features:
        checks["manual_feature_scoring_complete"] = manual_complete

    core_complete = all(checks.values())
    if core_complete and manual_complete:
        status = "research_and_prior_study_analyses_complete"
    elif core_complete:
        status = "numeric_and_embedding_complete_manual_feature_review_pending"
    else:
        status = "incomplete"

    report = {
        "status": status,
        "checks": checks,
        "manual_feature_scoring_complete": manual_complete,
        "manual_feature_scoring_required_for_this_check": bool(
            args.require_manual_features
        ),
        "instance_count": len(instances),
        "split_counts": {str(k): int(v) for k, v in split_counts.items()},
        "optimization_version_count": len(versions),
        "final_prompt_count": len(final_prompts),
        "heldout_reranker_labels": heldout_labels,
        "heldout_reranker_models": heldout_models,
        "test_result_count": len(test_rows),
        "test_condition_counts": {
            str(k): int(v) for k, v in condition_counts.items()
        },
        "missing_analysis_files": missing_analysis,
        "estimated_main_experiment_api_cost_usd": float(
            run_summary.get("total_api_cost_usd_estimate", 0)
        ),
        "meaning": (
            "numeric_and_embedding_complete_manual_feature_review_pendingは、"
            "順位結果・統計・埋め込み収束が完成し、論文Section 5.5.1対応の"
            "人手0/1/2評価だけが未入力であることを示す。"
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("07b 先行研究準拠完了チェック")
    for key, value in checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    print(
        "  manual_feature_scoring_complete: "
        + ("OK" if manual_complete else "PENDING")
    )
    print(f"  status: {status}")
    print(f"  report: {args.report}")

    if not core_complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
