from __future__ import annotations

"""TOEIC版E-GEOの最終安全ランナー。

既存05hへ次の本番前修正を追加する。
- 長文・短文Testで同一の最適化リライトを再利用する。
- API応答取得後、JSON解析より先にusageと費用を確定する。
- GPT-5系列のResponses APIへminimal reasoningを明示する。
- OpenAIのcached inputを実際の割引単価で費用計上する。
- 成功キャッシュは従来どおり再利用し、Provider別hard stopを維持する。
"""

import importlib.util
import json
import random
import sys
import time
from pathlib import Path
from typing import Any


SAFE_RUNNER = Path(__file__).with_name("05h_TOEIC費用配分安全実行.py")
RUNNER_REVISION = "05i-final-safety-v2"
OPENAI_CACHED_INPUT_USD_PER_MILLION = {
    "gpt-4.1-2025-04-14": 0.50,
    "gpt-5-2025-08-07": 0.125,
    "gpt-5-mini-2025-08-07": 0.025,
}


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


safe = load_module(SAFE_RUNNER, "toeic_egeo_safe_runner_base")
budgeted = safe.budgeted
legacy = budgeted.legacy
base = budgeted.base
prior = budgeted.prior
ORIGINAL_SAFE_INSTALL = safe.safe_install_cost_controls


def openai_usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 0,
        }
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(
        getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
    )
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    cached = int(getattr(input_details, "cached_tokens", 0) or 0)
    reasoning = int(getattr(output_details, "reasoning_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(input_tokens - cached, 0),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def final_role_cost(self: Any, usage: dict[str, int]) -> float:
    if str(self.provider) == "anthropic":
        return float(budgeted.cache_aware_role_cost(self, usage))

    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    if str(self.provider) != "openai":
        return (
            input_tokens / 1_000_000 * self.input_usd_per_million
            + output_tokens / 1_000_000 * self.output_usd_per_million
        )

    cached = min(
        int(usage.get("cached_input_tokens", 0) or 0),
        input_tokens,
    )
    uncached = max(input_tokens - cached, 0)
    cached_rate = OPENAI_CACHED_INPUT_USD_PER_MILLION.get(
        str(self.model_id),
        self.input_usd_per_million,
    )
    return (
        uncached / 1_000_000 * self.input_usd_per_million
        + cached / 1_000_000 * cached_rate
        + output_tokens / 1_000_000 * self.output_usd_per_million
    )


def final_openai_call(
    client: Any,
    role: Any,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, int], str | None]:
    kwargs: dict[str, Any] = {
        "model": role.model_id,
        "instructions": system_prompt,
        "input": user_prompt,
        "store": False,
        "max_output_tokens": role.max_output_tokens,
    }
    if str(role.model_id).startswith("gpt-5"):
        kwargs["reasoning"] = {"effort": "minimal"}
    if role.supports_temperature and role.temperature is not None:
        kwargs["temperature"] = role.temperature

    response = client.responses.create(**kwargs)
    text = base.response_text(response).strip()
    usage = openai_usage_dict(response)
    return text, usage, getattr(response, "id", None)


def empty_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }


def final_generate(
    self: Any,
    *,
    kind: str,
    context_id: str,
    role: Any,
    system_prompt: str,
    user_prompt: str,
    parser: Any,
) -> tuple[str, Any, dict[str, Any]]:
    identity = {
        "runner_revision": RUNNER_REVISION,
        "kind": kind,
        "context_id": context_id,
        "provider": role.provider,
        "model": role.model_id,
        "temperature": role.temperature if role.supports_temperature else None,
        "reasoning_effort": (
            "minimal" if str(role.model_id).startswith("gpt-5") else None
        ),
        "system_sha256": base.stable_hash(system_prompt),
        "user_sha256": base.stable_hash(user_prompt),
    }
    job_id = f"{kind}__{base.stable_hash(identity)[:24]}"
    cached = self.cache.get(job_id)
    if cached is not None:
        return str(cached["output_text"]), cached.get("parsed"), cached

    last_error: Exception | None = None
    for attempt in range(1, self.max_retries + 1):
        safe.strict_preflight_budget_check(self, str(role.provider))
        started = base.utc_now()
        text = ""
        response_id: str | None = None
        usage = empty_usage()
        cost = 0.0
        try:
            text, usage, response_id = self._provider_call(
                role,
                system_prompt,
                user_prompt,
            )
            cost = float(role.cost(usage))
            if not text:
                raise ValueError("API応答が空です。")
            parsed = parser(text)
            row = {
                "job_id": job_id,
                "status": "success",
                "kind": kind,
                "context_id": context_id,
                "role": role.role_name,
                "anonymous_label": role.anonymous_label,
                "provider": role.provider,
                "model": role.model_id,
                "attempt": attempt,
                "output_text": text,
                "parsed": parsed,
                "usage": usage,
                "cost_usd": cost,
                "response_id": response_id,
                "started_at": started,
                "finished_at": base.utc_now(),
                "identity": identity,
            }
            self.cache.add(row)
            self._check_budget()
            return text, parsed, row
        except Exception as exc:
            last_error = exc
            row = {
                "job_id": job_id,
                "status": "failed",
                "kind": kind,
                "context_id": context_id,
                "role": role.role_name,
                "anonymous_label": role.anonymous_label,
                "provider": role.provider,
                "model": role.model_id,
                "attempt": attempt,
                "output_text": text,
                "usage": usage,
                "cost_usd": cost,
                "response_id": response_id,
                "error": str(exc),
                "started_at": started,
                "finished_at": base.utc_now(),
                "identity": identity,
            }
            self.cache.add(row)
            self._check_budget()
            if attempt < self.max_retries:
                wait = min(
                    2 ** (attempt - 1) + random.random(),
                    self.retry_max_wait_seconds,
                )
                time.sleep(wait)
    raise RuntimeError(f"API処理に失敗しました: {last_error}") from last_error


def result_row(
    *,
    condition: str,
    query_form: str,
    prompt_id: str,
    version_label: str,
    intent_id: str,
    instance: dict[str, Any],
    reranker: Any,
    rewritten: str,
    rewrite_record: dict[str, Any],
    api: Any,
    ranking_template: str,
) -> dict[str, Any]:
    base_rank, base_parsed, base_record = base.original_rank(
        api,
        reranker,
        ranking_template,
        instance,
        query_form,
    )
    rewritten_rank, rerank_parsed, rerank_record = base.rank_instance(
        api=api,
        role=reranker,
        ranking_template=ranking_template,
        instance=instance,
        query_form=query_form,
        rewritten_description=rewritten,
        context_id=(
            f"{condition}__{prompt_id}__{version_label}__{intent_id}__"
            f"{query_form}__{reranker.anonymous_label}"
        ),
    )
    return {
        "condition": condition,
        "split": "test",
        "query_form": query_form,
        "prompt_id": prompt_id,
        "version_label": version_label,
        "intent_id": intent_id,
        "target_product_id": instance["target_product_id"],
        "target_candidate_position": int(instance["target_candidate_position"]),
        "reranker_label": reranker.anonymous_label,
        "reranker_model": reranker.model_id,
        "original_rank": base_rank,
        "rewritten_rank": rewritten_rank,
        "rank_improvement": base_rank - rewritten_rank,
        "original_questionable_products": base_parsed["questionable_products"],
        "rewritten_questionable_products": rerank_parsed[
            "questionable_products"
        ],
        "rewritten_target_flagged_questionable": int(
            instance["target_candidate_position"]
            in rerank_parsed["questionable_products"]
        ),
        "rewritten_description": rewritten,
        "rewrite_job_id": rewrite_record["job_id"],
        "original_rank_job_id": base_record["job_id"],
        "rewritten_rank_job_id": rerank_record["job_id"],
    }


def final_run_test(
    *,
    api: Any,
    prompts: list[dict[str, Any]],
    final_prompts: dict[str, dict[str, Any]],
    instances: dict[str, dict[str, Any]],
    test_ids: list[str],
    rewriter: Any,
    heldout_rerankers: list[Any],
    rewriter_system_prompt: str,
    ranking_template: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    is_smoke = len(prompts) == 1 and len(test_ids) == 1

    for prompt in prompts:
        prompt_id = str(prompt["id"])
        final = final_prompts[prompt_id]
        optimized_version = str(final["best_version_label"])

        for offset, intent_id in enumerate(test_ids, start=1):
            instance = instances[intent_id]

            initial_rewritten, initial_record = base.rewrite_description(
                api,
                rewriter,
                rewriter_system_prompt,
                instance,
                str(prompt["faithful_translation_ja"]),
                f"test_shared_rewrite__initial__{prompt_id}__{intent_id}",
            )
            optimized_rewritten, optimized_record = base.rewrite_description(
                api,
                rewriter,
                rewriter_system_prompt,
                instance,
                str(final["optimized_prompt"]),
                (
                    f"test_shared_rewrite__optimized__{prompt_id}__"
                    f"{optimized_version}__{intent_id}"
                ),
            )

            condition_specs = [
                (
                    "test_initial_long",
                    "long",
                    "initial",
                    initial_rewritten,
                    initial_record,
                ),
                (
                    "test_optimized_long",
                    "long",
                    optimized_version,
                    optimized_rewritten,
                    optimized_record,
                ),
                (
                    "test_optimized_short",
                    "short",
                    optimized_version,
                    optimized_rewritten,
                    optimized_record,
                ),
            ]

            for (
                condition,
                query_form,
                version_label,
                rewritten,
                rewrite_record,
            ) in condition_specs:
                rerankers = [
                    role
                    for role in heldout_rerankers
                    if is_smoke
                    or condition in budgeted.conditions_for_role(role)
                ]
                for reranker in rerankers:
                    rows.append(
                        result_row(
                            condition=condition,
                            query_form=query_form,
                            prompt_id=prompt_id,
                            version_label=version_label,
                            intent_id=intent_id,
                            instance=instance,
                            reranker=reranker,
                            rewritten=rewritten,
                            rewrite_record=rewrite_record,
                            api=api,
                            ranking_template=ranking_template,
                        )
                    )

            print(
                f"    shared Test rewrite: {offset}/{len(test_ids)} "
                f"{prompt_id}/{intent_id} (cost=${api.cache.spent_usd:.2f})"
            )
    return rows


def final_install_cost_controls(profile: dict[str, Any]) -> None:
    ORIGINAL_SAFE_INSTALL(profile)
    legacy.MultiProviderRunner._openai_call = staticmethod(final_openai_call)
    legacy.MultiProviderRunner.generate = final_generate
    legacy.MultiProviderRole.cost = final_role_cost
    base.run_test = final_run_test


def annotate_final_summary() -> None:
    output_dir = budgeted.output_dir_from_argv()
    summary_path = output_dir / "06_run_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["final_safety_patches"] = {
        "runner_revision": RUNNER_REVISION,
        "shared_optimized_rewrite_for_long_and_short": True,
        "failed_response_usage_costed_before_parse": True,
        "openai_cached_input_priced_from_usage_details": True,
        "gpt5_reasoning_effort": "minimal",
        "provider_preflight_hard_stop": True,
        "connectivity_smoke_required_before_full_candidate_selection": True,
        "full_budget_projection_required_after_smoke": True,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    budgeted.install_cost_controls = final_install_cost_controls
    budgeted.main()
    annotate_final_summary()


if __name__ == "__main__":
    main()
