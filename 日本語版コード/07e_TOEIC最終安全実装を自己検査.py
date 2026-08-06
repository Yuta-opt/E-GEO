from __future__ import annotations

"""最終安全ランナーをAPIなしで自己検査する。"""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


FINAL_RUNNER = Path(__file__).with_name("05i_TOEIC最終安全実行.py")
CANDIDATE_RUNNER = Path(__file__).with_name(
    "04d_TOEIC候補10商品を安全に選ぶ.py"
)
TWO_PROVIDER_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini実験設定_v1.json"
)
THREE_PROVIDER_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


final = load_module(FINAL_RUNNER, "toeic_egeo_final_self_check")
candidate = load_module(CANDIDATE_RUNNER, "toeic_candidate_final_self_check")
base = final.base


class FakeCache:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def get(self, job_id: str) -> dict[str, Any] | None:
        for row in reversed(self.rows):
            if row.get("job_id") == job_id and row.get("status") == "success":
                return row
        return None

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)

    @property
    def spent_usd(self) -> float:
        return float(sum(float(row.get("cost_usd", 0)) for row in self.rows))


class FakeRunner:
    def __init__(self) -> None:
        self.cache = FakeCache()
        self.max_retries = 2
        self.retry_max_wait_seconds = 0
        self.warning_thresholds = []
        self.warned = set()
        self.calls = 0

    def _provider_call(
        self,
        role: Any,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, int], str]:
        self.calls += 1
        return (
            '{"ok": true}',
            {
                "input_tokens": 100,
                "cached_input_tokens": 60,
                "uncached_input_tokens": 40,
                "output_tokens": 20,
                "reasoning_output_tokens": 0,
                "total_tokens": 120,
            },
            f"response-{self.calls}",
        )

    def _check_budget(self) -> None:
        return


def check_provider_sdk_imports() -> bool:
    try:
        from anthropic import Anthropic
        from google import genai
        from openai import OpenAI
    except Exception:
        return False
    return bool(OpenAI and genai.Client and Anthropic)


def check_candidate_unsorted_normalization() -> bool:
    raw = [0, 3, 11, 12, 17, 23, 27, 28, 6, 19]
    expected = [0, 3, 6, 11, 12, 17, 19, 23, 27, 28]
    normalized, observed_raw, changed = candidate.parse_candidate_selection(
        json.dumps(raw)
    )
    if normalized != expected or observed_raw != raw or not changed:
        return False

    already_sorted, observed_sorted, changed_sorted = (
        candidate.parse_candidate_selection(json.dumps(expected))
    )
    if (
        already_sorted != expected
        or observed_sorted != expected
        or changed_sorted
    ):
        return False

    invalid_samples = [
        [0, 0, 1, 2, 3, 4, 5, 6, 7, 8],
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 30],
        [0, 1, 2],
    ]
    for value in invalid_samples:
        try:
            candidate.parse_candidate_selection(json.dumps(value))
        except ValueError:
            continue
        return False
    return True


def check_cached_input_cost() -> bool:
    role = SimpleNamespace(
        provider="openai",
        model_id="gpt-4.1-2025-04-14",
        input_usd_per_million=2.0,
        output_usd_per_million=8.0,
    )
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 800,
        "output_tokens": 100,
    }
    actual = final.final_role_cost(role, usage)
    expected = 0.0016
    return abs(actual - expected) < 1e-12


def check_failed_parse_cost() -> bool:
    runner = FakeRunner()
    role = SimpleNamespace(
        role_name="heldout_reranker",
        anonymous_label="Model E",
        provider="openai",
        model_id="gpt-5-2025-08-07",
        temperature=None,
        supports_temperature=False,
        cost=lambda usage: 0.123,
    )
    original_preflight = final.safe.strict_preflight_budget_check
    final.safe.strict_preflight_budget_check = lambda self, provider: None
    attempts = {"count": 0}

    def parser(text: str) -> dict[str, bool]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("intentional parse failure")
        return {"ok": True}

    try:
        _, parsed, _ = final.final_generate(
            runner,
            kind="selfcheck",
            context_id="failed-cost",
            role=role,
            system_prompt="system",
            user_prompt="user",
            parser=parser,
        )
    finally:
        final.safe.strict_preflight_budget_check = original_preflight

    failed = [
        row for row in runner.cache.rows if row.get("status") == "failed"
    ]
    return bool(
        parsed == {"ok": True}
        and len(failed) == 1
        and float(failed[0]["cost_usd"]) == 0.123
        and int(failed[0]["usage"]["total_tokens"]) == 120
    )


def check_shared_test_rewrite() -> bool:
    calls = {"rewrite": 0}
    original_rewrite = base.rewrite_description
    original_rank = base.original_rank
    original_rank_instance = base.rank_instance
    original_conditions = final.budgeted.conditions_for_role

    def fake_rewrite(
        api: Any,
        role: Any,
        system_prompt: str,
        instance: dict[str, Any],
        rewriting_prompt: str,
        context_id: str,
    ) -> tuple[str, dict[str, str]]:
        calls["rewrite"] += 1
        return (
            f"rewrite-{calls['rewrite']}",
            {"job_id": f"rewrite-job-{calls['rewrite']}"},
        )

    def fake_original_rank(
        api: Any,
        role: Any,
        ranking_template: str,
        instance: dict[str, Any],
        query_form: str,
    ) -> tuple[int, dict[str, list[int]], dict[str, str]]:
        return 5, {"questionable_products": []}, {
            "job_id": f"original-{query_form}"
        }

    def fake_rank_instance(**kwargs: Any) -> tuple[
        int,
        dict[str, list[int]],
        dict[str, str],
    ]:
        return 3, {"questionable_products": []}, {
            "job_id": (
                f"rerank-{kwargs['query_form']}-"
                f"{kwargs['role'].anonymous_label}"
            )
        }

    base.rewrite_description = fake_rewrite
    base.original_rank = fake_original_rank
    base.rank_instance = fake_rank_instance
    final.budgeted.conditions_for_role = lambda role: {
        "test_initial_long",
        "test_optimized_long",
        "test_optimized_short",
    }

    api = SimpleNamespace(cache=SimpleNamespace(spent_usd=0.0))
    role = SimpleNamespace(
        anonymous_label="Model E",
        model_id="gpt-5-2025-08-07",
    )
    prompts = [
        {
            "id": "sample",
            "faithful_translation_ja": "書換: {description}",
        }
    ]
    finals = {
        "sample": {
            "best_version_label": "sample__e1_b1",
            "optimized_prompt": "最適化: {description}",
        }
    }
    instances = {
        "test-1": {
            "target_product_id": "p1",
            "target_candidate_position": 1,
        }
    }
    try:
        rows = final.final_run_test(
            api=api,
            prompts=prompts,
            final_prompts=finals,
            instances=instances,
            test_ids=["test-1"],
            rewriter=SimpleNamespace(),
            heldout_rerankers=[role],
            rewriter_system_prompt="system",
            ranking_template="{query}\n{formatted_products}",
        )
    finally:
        base.rewrite_description = original_rewrite
        base.original_rank = original_rank
        base.rank_instance = original_rank_instance
        final.budgeted.conditions_for_role = original_conditions

    frame = {row["condition"]: row for row in rows}
    return bool(
        calls["rewrite"] == 2
        and len(rows) == 3
        and frame["test_optimized_long"]["rewrite_job_id"]
        == frame["test_optimized_short"]["rewrite_job_id"]
        and frame["test_optimized_long"]["rewritten_description"]
        == frame["test_optimized_short"]["rewritten_description"]
    )


def check_profiles() -> bool:
    for path in [TWO_PROVIDER_PROFILE, THREE_PROVIDER_PROFILE]:
        profile = json.loads(path.read_text(encoding="utf-8"))
        heldout = {
            str(item["anonymous_label"]): item
            for item in profile["roles"]["heldout_rerankers"]
        }
        gpt5 = heldout["Model E"]
        gemini = heldout["Model F"]
        if int(gpt5["max_output_tokens"]) < 1000:
            return False
        if gemini.get("temperature") is not None:
            return False
        if bool(gemini.get("supports_temperature")):
            return False
        execution = profile["execution"]
        if execution.get("gpt5_reasoning_effort") != "minimal":
            return False
        if execution.get("shared_rewrite_across_long_short") is not True:
            return False
        if execution.get("failed_usage_counted_before_parse") is not True:
            return False
    return True


def main() -> None:
    checks = {
        "provider_sdks_import": check_provider_sdk_imports(),
        "candidate_unsorted_output_is_normalized": (
            check_candidate_unsorted_normalization()
        ),
        "cached_input_discount_is_accounted": check_cached_input_cost(),
        "failed_parse_cost_is_recorded": check_failed_parse_cost(),
        "optimized_long_short_share_one_rewrite": check_shared_test_rewrite(),
        "model_profiles_are_safe": check_profiles(),
    }
    print("07e 最終安全実装セルフチェック")
    for key, value in checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
