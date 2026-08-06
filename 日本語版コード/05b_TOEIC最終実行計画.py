from __future__ import annotations

"""05aのAPI予定回数をProvider別Test条件へ一致させる最終計画ラッパー。"""

import importlib.util
import sys
from pathlib import Path
from typing import Any


BASE_PLANNER = Path(__file__).with_name(
    "05a_TOEICメタ最適化実験を計画.py"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = load_module(BASE_PLANNER, "toeic_egeo_plan_base")
ORIGINAL_CALL_COMPONENTS = base.call_components


def final_call_components(
    plan: dict[str, Any],
    short_evaluates_initial: bool,
) -> list[dict[str, Any]]:
    rows = ORIGINAL_CALL_COMPONENTS(plan, short_evaluates_initial)
    heldout_total = int(plan["heldout_reranker_count"])
    heldout_long = int(
        plan.get("heldout_long_reranker_count", heldout_total)
    )
    default_short = heldout_total
    if str(plan.get("id")) == "formal_scaled_replication_openai_gemini":
        default_short = 1
    heldout_short = int(
        plan.get("heldout_short_reranker_count", default_short)
    )
    if not 0 <= heldout_long <= heldout_total:
        raise ValueError("heldout_long_reranker_countが不正です。")
    if not 0 <= heldout_short <= heldout_total:
        raise ValueError("heldout_short_reranker_countが不正です。")

    long_stages = {
        "original_rank_test_long",
        "test_rank_initial_long",
        "test_rank_optimized_long",
    }
    short_stages = {
        "original_rank_test_short",
        "test_rank_optimized_short",
        "test_rank_initial_short",
    }
    for row in rows:
        stage = str(row["stage"])
        if stage in long_stages:
            row["api_calls"] = (
                int(row["api_calls"]) * heldout_long // heldout_total
            )
        elif stage in short_stages:
            row["api_calls"] = (
                int(row["api_calls"]) * heldout_short // heldout_total
            )
    return rows


def main() -> None:
    base.call_components = final_call_components
    base.main()


if __name__ == "__main__":
    main()
