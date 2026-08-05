from __future__ import annotations

"""05gの費用配分を安全に実行する最終ラッパー。

- hard stop超過をAPI呼び出し前に判定する。
- 成功応答を保存した直後の予算判定で再試行が起きる問題を防ぐ。
- 1回のリクエスト分だけ上限を超える可能性はあるが、次の呼び出し前に停止する。
- smokeでは全Held-outモデルを全3条件へ通し、接続と出力形式を確認する。
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any


BUDGETED_RUNNER = Path(__file__).with_name(
    "05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


budgeted = load_module(
    BUDGETED_RUNNER,
    "toeic_egeo_budgeted_safe_base",
)
ORIGINAL_GENERATE = budgeted.legacy.MultiProviderRunner.generate
ORIGINAL_INSTALL = budgeted.install_cost_controls
ORIGINAL_COST_AWARE_RUN_TEST = budgeted.cost_aware_run_test


def warning_only_budget_check(self: Any) -> None:
    total_spent = float(self.cache.spent_usd)
    for threshold in self.warning_thresholds:
        if total_spent >= threshold and threshold not in self.warned:
            print(
                f"[総予算警告] 累計概算 ${total_spent:.2f} "
                f"（${threshold:.0f}到達）"
            )
            self.warned.add(threshold)

    if not hasattr(self, "provider_warned"):
        self.provider_warned = set()
    totals = budgeted.provider_spend(self.cache)
    for provider, spent in totals.items():
        for threshold in budgeted.PROVIDER_WARNING_THRESHOLDS.get(
            provider,
            [],
        ):
            key = (provider, threshold)
            if spent >= threshold and key not in self.provider_warned:
                print(
                    f"[Provider予算警告] {provider}=${spent:.2f} "
                    f"（${threshold:.0f}到達）"
                )
                self.provider_warned.add(key)


def strict_preflight_budget_check(self: Any) -> None:
    total_spent = float(self.cache.spent_usd)
    if total_spent >= float(self.hard_stop_usd):
        raise RuntimeError(
            f"全社合計${total_spent:.2f}が総hard stop "
            f"${self.hard_stop_usd:.2f}へ到達済みです。"
        )
    totals = budgeted.provider_spend(self.cache)
    for provider, limit in budgeted.PROVIDER_HARD_STOPS.items():
        spent = float(totals.get(provider, 0.0))
        if spent >= float(limit):
            raise RuntimeError(
                f"{provider}累計${spent:.2f}がProvider hard stop "
                f"${float(limit):.2f}へ到達済みです。"
            )


def safe_generate(self: Any, *args: Any, **kwargs: Any) -> Any:
    strict_preflight_budget_check(self)
    return ORIGINAL_GENERATE(self, *args, **kwargs)


def smoke_symmetric_run_test(**kwargs: Any) -> list[dict[str, Any]]:
    prompts = kwargs["prompts"]
    test_ids = kwargs["test_ids"]
    if len(prompts) != 1 or len(test_ids) != 1:
        return ORIGINAL_COST_AWARE_RUN_TEST(**kwargs)

    previous = budgeted.TEST_CONDITIONS_BY_PROVIDER
    providers = {
        str(role.provider) for role in kwargs["heldout_rerankers"]
    }
    all_conditions = [
        "test_initial_long",
        "test_optimized_long",
        "test_optimized_short",
    ]
    budgeted.TEST_CONDITIONS_BY_PROVIDER = {
        provider: list(all_conditions) for provider in providers
    }
    try:
        return ORIGINAL_COST_AWARE_RUN_TEST(**kwargs)
    finally:
        budgeted.TEST_CONDITIONS_BY_PROVIDER = previous


def safe_install_cost_controls(profile: dict[str, Any]) -> None:
    ORIGINAL_INSTALL(profile)
    budgeted.legacy.MultiProviderRunner._check_budget = (
        warning_only_budget_check
    )
    budgeted.legacy.MultiProviderRunner.generate = safe_generate
    budgeted.base.run_test = smoke_symmetric_run_test


def main() -> None:
    budgeted.install_cost_controls = safe_install_cost_controls
    budgeted.main()


if __name__ == "__main__":
    main()
