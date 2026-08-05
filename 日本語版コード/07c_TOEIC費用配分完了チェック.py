from __future__ import annotations

"""GPTを主評価、Gemini・Claudeを低予算評価にした正式実験の完了検査。"""

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
    "05_費用配分研究完了チェック.json"
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


def expected_condition_counts(
    policy: dict[str, list[str]],
    prompt_count: int,
    test_count: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    per_model_condition = prompt_count * test_count
    for conditions in policy.values():
        for condition in conditions:
            counts[condition] = counts.get(condition, 0) + per_model_condition
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Providerごとに異なるTest条件と個別予算上限を含め、"
            "正式80件・15×8版・分析結果を検査する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--expected-heldout-count", type=int, default=2)
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
    actual_condition_counts = {
        str(key): int(value)
        for key, value in test_frame["condition"].value_counts().to_dict().items()
    }
    heldout_labels = sorted(
        test_frame["reranker_label"].astype(str).unique().tolist()
    )
    heldout_models = sorted(
        test_frame["reranker_model"].astype(str).unique().tolist()
    )
    policy = {
        str(label): [str(item) for item in conditions]
        for label, conditions in run_summary.get(
            "heldout_test_policy",
            {},
        ).items()
    }
    expected_counts = expected_condition_counts(
        policy,
        prompt_count=15,
        test_count=30,
    )

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
    provider_costs = {
        str(key): float(value)
        for key, value in run_summary.get("provider_cost_usd", {}).items()
    }
    provider_limits = {
        str(key): float(value)
        for key, value in run_summary.get(
            "provider_hard_stops_usd",
            {},
        ).items()
    }
    provider_budget_ok = all(
        provider_costs.get(provider, 0.0) < limit
        for provider, limit in provider_limits.items()
    )

    condition_count_ok = bool(expected_counts) and all(
        actual_condition_counts.get(condition, 0) == expected
        for condition, expected in expected_counts.items()
    )
    unexpected_conditions = sorted(
        set(actual_condition_counts) - set(expected_counts)
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
        "heldout_reranker_count": len(heldout_labels)
        == args.expected_heldout_count,
        "heldout_test_policy_recorded": bool(policy),
        "condition_counts_match_policy": condition_count_ok,
        "no_unexpected_conditions": not unexpected_conditions,
        "test_rows_expected": len(test_rows) == sum(expected_counts.values()),
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
        "rewriter_uses_listing_text": compliance.get("rewriter_input")
        == "target listing title + description; query blind",
        "cost_control_variant_recorded": run_summary.get(
            "cost_control_variant"
        )
        is True,
        "provider_costs_within_limits": provider_budget_ok,
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
    }
    if args.require_manual_features:
        checks["manual_feature_scoring_complete"] = manual_complete

    core_complete = all(checks.values())
    if core_complete and manual_complete:
        status = "research_and_manual_analysis_complete"
    elif core_complete:
        status = "numeric_and_embedding_complete_manual_review_pending"
    else:
        status = "incomplete"

    report = {
        "status": status,
        "checks": checks,
        "heldout_test_policy": policy,
        "expected_condition_counts": expected_counts,
        "actual_condition_counts": actual_condition_counts,
        "unexpected_conditions": unexpected_conditions,
        "provider_cost_usd": provider_costs,
        "provider_hard_stops_usd": provider_limits,
        "manual_feature_scoring_complete": manual_complete,
        "instance_count": len(instances),
        "split_counts": {str(k): int(v) for k, v in split_counts.items()},
        "optimization_version_count": len(versions),
        "final_prompt_count": len(final_prompts),
        "heldout_reranker_labels": heldout_labels,
        "heldout_reranker_models": heldout_models,
        "test_result_count": len(test_rows),
        "missing_analysis_files": missing_analysis,
        "meaning": (
            "GPTは全条件、Geminiは長文条件、Claudeは最適化済み長文条件"
            "という非対称Test設計を、記録済みpolicyどおりに検査する。"
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("07c 費用配分完了チェック")
    for key, value in checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    print(f"  provider costs: {provider_costs}")
    print(f"  status: {status}")
    print(f"  report: {args.report}")

    if not core_complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
