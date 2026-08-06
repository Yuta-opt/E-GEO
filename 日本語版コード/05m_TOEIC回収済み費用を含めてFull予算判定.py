from __future__ import annotations

"""回収済みrerank応答の実測費用も使ってFull予算を判定する。"""

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


BASE_PROJECTION = Path(__file__).with_name(
    "05k_TOEIC_Smoke実測からFull予算を判定.py"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = load_module(BASE_PROJECTION, "toeic_egeo_budget_projection_base")


def recovery_aware_successful_smoke_costs(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str], list[float]]:
    result: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in events:
        if row.get("status") != "success":
            continue
        identity = row.get("identity") or {}
        if identity.get("runner_revision") != base.RUNNER_REVISION:
            continue
        role = str(row.get("role", ""))
        model = str(row.get("model", ""))
        if role not in base.SAFETY_FACTORS or not model:
            continue

        if row.get("recovered_without_api_call"):
            observed = float(
                row.get("recovered_call_cost_usd", 0) or 0
            )
            if observed <= 0:
                continue
            result[(role, model)].append(observed)
        else:
            result[(role, model)].append(
                float(row.get("cost_usd", 0) or 0)
            )
    return dict(result)


def main() -> None:
    base.successful_smoke_costs = recovery_aware_successful_smoke_costs
    base.main()


if __name__ == "__main__":
    main()
