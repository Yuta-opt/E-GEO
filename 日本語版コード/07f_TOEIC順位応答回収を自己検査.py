from __future__ import annotations

"""最終安全実装と順位応答回収をAPIなしで自己検査する。"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


BASE_CHECK = Path(__file__).with_name(
    "07e_TOEIC最終安全実装を自己検査.py"
)
RANK_RECOVERY = Path(__file__).with_name(
    "05l_TOEIC順位応答を安全に正規化.py"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base_check = load_module(BASE_CHECK, "toeic_egeo_base_selfcheck")
recovery = load_module(RANK_RECOVERY, "toeic_egeo_rank_recovery_selfcheck")


class FakeCache:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = list(events)
        self.success: dict[str, dict[str, Any]] = {}

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.success.get(job_id)

    def add(self, row: dict[str, Any]) -> None:
        self.events.append(row)
        if row.get("status") == "success":
            self.success[str(row["job_id"])] = row


class NoCallRunner:
    def __init__(self, cache: FakeCache) -> None:
        self.cache = cache
        self.calls = 0

    def _provider_call(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("回収時にAPIを呼んではいけません。")


def check_duplicate_only_ranking_normalization() -> bool:
    text = (
        '{"ranking":[6,3,5,1,2,9,5,4,10,7,8],'
        '"questionable_products":[5,5]}'
    )
    parsed = recovery.safe_parse_ranking(text)
    expected = [6, 3, 5, 1, 2, 9, 4, 10, 7, 8]
    try:
        recovery.safe_parse_ranking(
            '{"ranking":[1,2,3,4,5,6,7,8,9,9],'
            '"questionable_products":[]}'
        )
    except ValueError:
        missing_rejected = True
    else:
        missing_rejected = False
    return bool(
        parsed["ranking"] == expected
        and parsed["ranking_normalized"] is True
        and parsed["questionable_products"] == [5]
        and parsed["questionable_products_normalized"] is True
        and missing_rejected
    )


def check_failed_rerank_recovery_without_api() -> bool:
    role = SimpleNamespace(
        provider="openai",
        model_id="gpt-5-2025-08-07",
        temperature=None,
        supports_temperature=False,
    )
    identity = recovery.generation_identity(
        kind="rerank",
        context_id="selfcheck-ranking",
        role=role,
        system_prompt="system",
        user_prompt="user",
    )
    job_id = f"rerank__{recovery.base.stable_hash(identity)[:24]}"
    failed = {
        "job_id": job_id,
        "status": "failed",
        "kind": "rerank",
        "context_id": "selfcheck-ranking",
        "role": "heldout_reranker",
        "anonymous_label": "Model E",
        "provider": "openai",
        "model": "gpt-5-2025-08-07",
        "attempt": 3,
        "output_text": (
            '{"ranking":[6,3,5,1,2,9,5,4,10,7,8],'
            '"questionable_products":[]}'
        ),
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
        "cost_usd": 0.02,
        "response_id": "response-old",
        "identity": identity,
    }
    cache = FakeCache([failed])
    runner = NoCallRunner(cache)
    _, parsed, record = recovery.recovery_generate(
        runner,
        kind="rerank",
        context_id="selfcheck-ranking",
        role=role,
        system_prompt="system",
        user_prompt="user",
        parser=recovery.safe_parse_ranking,
    )
    return bool(
        runner.calls == 0
        and parsed["ranking"]
        == [6, 3, 5, 1, 2, 9, 4, 10, 7, 8]
        and record["status"] == "success"
        and record["recovered_without_api_call"] is True
        and float(record["cost_usd"]) == 0.0
        and float(record["recovered_call_cost_usd"]) == 0.02
        and cache.get(job_id) is record
    )


def main() -> None:
    checks = {
        "provider_sdks_import": base_check.check_provider_sdk_imports(),
        "candidate_unsorted_output_is_normalized": (
            base_check.check_candidate_order_normalization()
        ),
        "cached_input_discount_is_accounted": (
            base_check.check_cached_input_cost()
        ),
        "failed_parse_cost_is_recorded": (
            base_check.check_failed_parse_cost()
        ),
        "optimized_long_short_share_one_rewrite": (
            base_check.check_shared_test_rewrite()
        ),
        "model_profiles_are_safe": base_check.check_profiles(),
        "reranker_duplicate_only_output_is_normalized": (
            check_duplicate_only_ranking_normalization()
        ),
        "failed_rerank_is_recovered_without_api": (
            check_failed_rerank_recovery_without_api()
        ),
    }
    print("07f 最終安全実装・順位応答回収セルフチェック")
    for key, value in checks.items():
        print(f"  {key}: {'OK' if value else 'NG'}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
