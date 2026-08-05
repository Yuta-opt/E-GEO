from __future__ import annotations

"""OpenAIへ主予算を置き、Gemini・Claudeを低予算で追加する正式ランナー。

費用配分の基本方針
------------------
- OpenAI: 正式メタ最適化と全Test条件を担当。上限100 USD。
- Gemini: 安価なFlash-Lite系列で学習・長文Testを担当。短文Testは省略。
- Claude: 強いHeld-out評価器として最適化後の長文Testだけを担当。
- Provider別hard stopを設け、1社の超過で他社予算を食い潰さない。

研究上の位置付け
----------------
先行研究の中核である「複数エンジンのTrain結果によるメタ最適化」と
「プロンプト固定後の未学習モデル評価」は維持する。一方、費用を抑えるため、
Gemini・Claudeのモデル、System Prompt、Test条件を縮小したscaled replicationである。

APIは --execute を付けない限り呼び出さない。
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


PRIOR_ALIGNED_RUNNER = Path(__file__).with_name(
    "05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py"
)
DEFAULT_MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)

COMPACT_GEMINI_RERANKER_SYSTEM = (
    "You are Gemini acting as a strict product-search re-ranker. "
    "Use only the query and the ten supplied product listings. "
    "Follow the requested JSON schema exactly and return no extra text."
)
COMPACT_CLAUDE_RERANKER_SYSTEM = (
    "You are Claude acting as a strict product-search re-ranker. "
    "Use only the query and the ten supplied product listings. "
    "Follow the requested JSON schema exactly and return no extra text."
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


prior = load_module(
    PRIOR_ALIGNED_RUNNER,
    "toeic_egeo_prior_aligned_budgeted",
)
legacy = prior.legacy
base = prior.base

ACTIVE_PROFILE: dict[str, Any] = {}
PROVIDER_HARD_STOPS: dict[str, float] = {}
PROVIDER_WARNING_THRESHOLDS: dict[str, list[float]] = {}
TEST_CONDITIONS_BY_PROVIDER: dict[str, list[str]] = {}


def argument_path(flag: str, default: Path) -> Path:
    for index, value in enumerate(sys.argv):
        if value == flag and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return default


def output_dir_from_argv() -> Path:
    return argument_path("--output-dir", DEFAULT_OUTPUT_DIR)


def load_active_profile() -> dict[str, Any]:
    path = argument_path("--model-profile", DEFAULT_MODEL_PROFILE)
    if not path.exists():
        raise FileNotFoundError(f"モデル設定が見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def configure_policy(profile: dict[str, Any]) -> None:
    global ACTIVE_PROFILE
    global PROVIDER_HARD_STOPS
    global PROVIDER_WARNING_THRESHOLDS
    global TEST_CONDITIONS_BY_PROVIDER

    ACTIVE_PROFILE = profile
    budget = profile.get("budget", {})
    PROVIDER_HARD_STOPS = {
        str(provider): float(value)
        for provider, value in budget.get(
            "provider_hard_stops_usd",
            {},
        ).items()
    }
    PROVIDER_WARNING_THRESHOLDS = {
        str(provider): [float(item) for item in values]
        for provider, values in budget.get(
            "provider_warning_thresholds_usd",
            {},
        ).items()
    }
    comparison = profile.get("comparison_policy", {})
    TEST_CONDITIONS_BY_PROVIDER = {
        str(provider): [str(item) for item in values]
        for provider, values in comparison.get(
            "test_conditions_by_provider",
            {},
        ).items()
    }


def provider_spend(cache: Any) -> dict[str, float]:
    totals: dict[str, float] = {}
    for event in cache.events:
        provider = str(event.get("provider", "unknown"))
        totals[provider] = totals.get(provider, 0.0) + float(
            event.get("cost_usd", 0) or 0
        )
    return totals


def provider_aware_check_budget(self: Any) -> None:
    total_spent = float(self.cache.spent_usd)
    for threshold in self.warning_thresholds:
        if total_spent >= threshold and threshold not in self.warned:
            print(
                f"[総予算警告] 累計概算 ${total_spent:.2f} "
                f"（${threshold:.0f}到達）"
            )
            self.warned.add(threshold)
    if total_spent >= self.hard_stop_usd:
        raise RuntimeError(
            f"全社合計${total_spent:.2f}が総hard stop "
            f"${self.hard_stop_usd:.2f}へ到達しました。"
        )

    if not hasattr(self, "provider_warned"):
        self.provider_warned = set()
    totals = provider_spend(self.cache)
    for provider, spent in totals.items():
        for threshold in PROVIDER_WARNING_THRESHOLDS.get(provider, []):
            key = (provider, threshold)
            if spent >= threshold and key not in self.provider_warned:
                print(
                    f"[Provider予算警告] {provider}=${spent:.2f} "
                    f"（${threshold:.0f}到達）"
                )
                self.provider_warned.add(key)
        limit = PROVIDER_HARD_STOPS.get(provider)
        if limit is not None and spent >= limit:
            raise RuntimeError(
                f"{provider}累計${spent:.2f}がProvider hard stop "
                f"${limit:.2f}へ到達しました。"
            )


def cache_aware_role_cost(self: Any, usage: dict[str, int]) -> float:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    if self.provider != "anthropic":
        return (
            input_tokens / 1_000_000 * self.input_usd_per_million
            + output_tokens / 1_000_000 * self.output_usd_per_million
        )

    cache_creation = int(
        usage.get("cache_creation_input_tokens", 0) or 0
    )
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    return (
        input_tokens / 1_000_000 * self.input_usd_per_million
        + cache_creation
        / 1_000_000
        * self.input_usd_per_million
        * 1.25
        + cache_read
        / 1_000_000
        * self.input_usd_per_million
        * 0.10
        + output_tokens / 1_000_000 * self.output_usd_per_million
    )


def cached_anthropic_call(
    client: Any,
    role: Any,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, int], str | None]:
    kwargs: dict[str, Any] = {
        "model": role.model_id,
        "max_tokens": role.max_output_tokens,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if role.supports_temperature and role.temperature is not None:
        kwargs["temperature"] = role.temperature
    response = client.messages.create(**kwargs)
    text = "".join(
        str(getattr(block, "text", ""))
        for block in getattr(response, "content", [])
        if getattr(block, "type", "") == "text"
    ).strip()
    metadata = getattr(response, "usage", None)
    input_tokens = int(getattr(metadata, "input_tokens", 0) or 0)
    output_tokens = int(getattr(metadata, "output_tokens", 0) or 0)
    cache_creation = int(
        getattr(metadata, "cache_creation_input_tokens", 0) or 0
    )
    cache_read = int(
        getattr(metadata, "cache_read_input_tokens", 0) or 0
    )
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "total_tokens": (
            input_tokens + output_tokens + cache_creation + cache_read
        ),
    }
    return text, usage, getattr(response, "id", None)


def cost_aware_family_system_prompt(role: Any) -> str:
    provider = str(getattr(role, "provider", "")).lower()
    model_id = str(getattr(role, "model_id", "")).lower()
    if provider == "google":
        return COMPACT_GEMINI_RERANKER_SYSTEM
    if provider == "anthropic":
        return COMPACT_CLAUDE_RERANKER_SYSTEM
    prompts = prior.original_family_prompts()
    if provider == "openai":
        return prompts["gpt5"] if "gpt-5" in model_id else prompts["gpt41"]
    raise ValueError(
        f"System Promptを選べません: provider={provider}, model={model_id}"
    )


def conditions_for_role(role: Any) -> set[str]:
    configured = TEST_CONDITIONS_BY_PROVIDER.get(str(role.provider))
    if configured is None:
        return {
            "test_initial_long",
            "test_optimized_long",
            "test_optimized_short",
        }
    return set(configured)


def cost_aware_run_test(
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
    condition_specs = [
        (
            "test_initial_long",
            "long",
            "initial",
        ),
        (
            "test_optimized_long",
            "long",
            "optimized",
        ),
        (
            "test_optimized_short",
            "short",
            "optimized",
        ),
    ]

    for prompt in prompts:
        prompt_id = str(prompt["id"])
        final = final_prompts[prompt_id]
        for condition, query_form, prompt_kind in condition_specs:
            rerankers = [
                role
                for role in heldout_rerankers
                if condition in conditions_for_role(role)
            ]
            if not rerankers:
                continue
            if prompt_kind == "initial":
                rewriting_prompt = str(prompt["faithful_translation_ja"])
                version_label = "initial"
            else:
                rewriting_prompt = str(final["optimized_prompt"])
                version_label = str(final["best_version_label"])
            labels = ", ".join(
                f"{role.anonymous_label}/{role.provider}" for role in rerankers
            )
            print(
                f"\n[test] {prompt_id}: {condition} -> {labels}"
            )
            rows.extend(
                base.evaluate_prompt(
                    api=api,
                    rewriter=rewriter,
                    rerankers=rerankers,
                    rewriter_system_prompt=rewriter_system_prompt,
                    ranking_template=ranking_template,
                    instances=instances,
                    intent_ids=test_ids,
                    rewriting_prompt=rewriting_prompt,
                    prompt_id=prompt_id,
                    version_label=version_label,
                    split="test",
                    query_form=query_form,
                    condition=condition,
                )
            )
    return rows


def test_policy_by_label(profile: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in profile["roles"].get("heldout_rerankers", []):
        provider = str(item["provider"])
        label = str(item["anonymous_label"])
        result[label] = sorted(
            TEST_CONDITIONS_BY_PROVIDER.get(
                provider,
                [
                    "test_initial_long",
                    "test_optimized_long",
                    "test_optimized_short",
                ],
            )
        )
    return result


def annotate_budget_summary(profile: dict[str, Any]) -> None:
    output_dir = output_dir_from_argv()
    cache_path = output_dir / "01_llm_cache.jsonl"
    totals: dict[str, float] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            provider = str(row.get("provider", "unknown"))
            totals[provider] = totals.get(provider, 0.0) + float(
                row.get("cost_usd", 0) or 0
            )

    provider_report = {
        "provider_cost_usd": {
            key: round(value, 6) for key, value in totals.items()
        },
        "provider_hard_stops_usd": PROVIDER_HARD_STOPS,
        "test_conditions_by_provider": TEST_CONDITIONS_BY_PROVIDER,
        "heldout_test_policy": test_policy_by_label(profile),
        "cost_control_changes": [
            "Gemini uses Flash-Lite models",
            "Gemini skips supplemental short-query Test",
            "Claude evaluates optimized long-query prompts only",
            "Gemini and Claude use compact model-specific reranker system prompts",
            "Claude uses ephemeral prompt caching",
        ],
    }
    (output_dir / "05b_provider_cost_summary.json").write_text(
        json.dumps(provider_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_path = output_dir / "06_run_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["provider_cost_usd"] = provider_report["provider_cost_usd"]
        summary["provider_hard_stops_usd"] = PROVIDER_HARD_STOPS
        summary["heldout_test_policy"] = provider_report[
            "heldout_test_policy"
        ]
        summary["cost_control_variant"] = True
        summary["prior_study_compliance"]["reranker_system_prompts"] = (
            "full original model-family prompts for OpenAI; compact "
            "model-specific prompts for Gemini and Claude"
        )
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def install_cost_controls(profile: dict[str, Any]) -> None:
    configure_policy(profile)
    legacy.MultiProviderRunner._check_budget = provider_aware_check_budget
    legacy.MultiProviderRole.cost = cache_aware_role_cost
    legacy.MultiProviderRunner._anthropic_call = staticmethod(
        cached_anthropic_call
    )
    prior.family_system_prompt = cost_aware_family_system_prompt
    base.run_test = cost_aware_run_test


def main() -> None:
    profile = load_active_profile()
    install_cost_controls(profile)
    prior.main()
    annotate_budget_summary(profile)


if __name__ == "__main__":
    main()
