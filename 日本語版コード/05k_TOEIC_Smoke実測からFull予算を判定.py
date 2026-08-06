from __future__ import annotations

"""正式工程Smokeの実測費用からFullのProvider別予算を保守的に外挿する。

Full実行前に必須。各role/modelのSmoke平均費用へ役割別安全係数を掛け、
正式な実行回数を乗じる。Provider hard stopの90%を超える見積りなら停止する。
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_RUN_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)
DEFAULT_EXPERIMENT_CONFIG = Path(
    "日本語版設定/TOEIC_EGEO実験設定_v3_先行研究準拠.json"
)
DEFAULT_MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini実験設定_v1.json"
)
RUNNER_REVISION = "05i-final-safety-v2"
SAFETY_FACTORS = {
    "rewriter": 2.0,
    "meta_optimizer": 4.0,
    "training_reranker": 1.5,
    "heldout_reranker": 1.5,
}


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Smokeキャッシュが見つかりません: {path}。先に-Mode Smokeを実行してください。"
        )
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONLの{number}行目がobjectではありません。")
        rows.append(value)
    return rows


def formal_counts(
    experiment: dict[str, Any],
    profile: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    dataset = experiment["dataset"]
    optimization = experiment["optimization"]
    prompt_count = int(experiment["prompt_policy"]["initial_prompt_count"])
    versions = int(optimization["epochs"]) * int(
        optimization["batches_per_epoch"]
    )
    batch_size = int(optimization["batch_size"])
    validation_count = int(dataset["validation"])
    test_count = int(dataset["test"])
    train_count = int(dataset["train"])

    roles = profile["roles"]
    output: dict[tuple[str, str], dict[str, Any]] = {}

    rewriter = roles["rewriter"]
    output[("rewriter", str(rewriter["model_id"]))] = {
        "provider": str(rewriter["provider"]),
        "formal_calls": (
            prompt_count * versions * (batch_size + validation_count)
            + prompt_count * test_count * 2
        ),
    }

    meta = roles["meta_optimizer"]
    output[("meta_optimizer", str(meta["model_id"]))] = {
        "provider": str(meta["provider"]),
        "formal_calls": prompt_count
        * int(optimization["meta_updates_per_prompt"]),
    }

    for item in roles["training_rerankers"]:
        output[("training_reranker", str(item["model_id"]))] = {
            "provider": str(item["provider"]),
            "formal_calls": (
                train_count
                + validation_count
                + prompt_count
                * versions
                * (batch_size + validation_count)
            ),
        }

    conditions_by_provider = profile["comparison_policy"][
        "test_conditions_by_provider"
    ]
    for item in roles["heldout_rerankers"]:
        provider = str(item["provider"])
        conditions = [
            str(value) for value in conditions_by_provider[provider]
        ]
        query_forms = {
            "short" if condition.endswith("_short") else "long"
            for condition in conditions
        }
        output[("heldout_reranker", str(item["model_id"]))] = {
            "provider": provider,
            "formal_calls": (
                test_count * len(query_forms)
                + prompt_count * test_count * len(conditions)
            ),
            "conditions": conditions,
        }
    return output


def successful_smoke_costs(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str], list[float]]:
    result: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in events:
        if row.get("status") != "success":
            continue
        identity = row.get("identity") or {}
        if identity.get("runner_revision") != RUNNER_REVISION:
            continue
        role = str(row.get("role", ""))
        model = str(row.get("model", ""))
        if role not in SAFETY_FACTORS or not model:
            continue
        result[(role, model)].append(float(row.get("cost_usd", 0) or 0))
    return dict(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke実測費用からFullの予算内完走可能性を判定する。"
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
    )
    parser.add_argument(
        "--model-profile",
        type=Path,
        default=DEFAULT_MODEL_PROFILE,
    )
    parser.add_argument(
        "--budget-fraction",
        type=float,
        default=0.90,
        help="Provider hard stopの何割までを合格とするか。既定0.90。",
    )
    args = parser.parse_args()

    if not 0 < args.budget_fraction < 1:
        raise ValueError("budget-fractionは0より大きく1未満にしてください。")

    experiment = read_json(args.experiment_config)
    profile = read_json(args.model_profile)
    events = read_jsonl(args.run_dir / "01_llm_cache.jsonl")
    counts = formal_counts(experiment, profile)
    observed = successful_smoke_costs(events)

    missing = sorted(set(counts) - set(observed))
    if missing:
        labels = ", ".join(f"{role}/{model}" for role, model in missing)
        raise RuntimeError(
            "費用外挿に必要なSmoke成功結果が不足しています: " + labels
        )

    rows: list[dict[str, Any]] = []
    provider_projection: dict[str, float] = defaultdict(float)
    for key, plan in counts.items():
        role, model = key
        values = observed[key]
        observed_mean = mean(values)
        factor = SAFETY_FACTORS[role]
        projected = observed_mean * int(plan["formal_calls"]) * factor
        provider = str(plan["provider"])
        provider_projection[provider] += projected
        rows.append(
            {
                "role": role,
                "provider": provider,
                "model": model,
                "smoke_successful_calls": len(values),
                "smoke_mean_cost_usd": observed_mean,
                "smoke_max_cost_usd": max(values),
                "formal_calls": int(plan["formal_calls"]),
                "safety_factor": factor,
                "projected_cost_usd": projected,
                "conditions": plan.get("conditions", []),
            }
        )

    hard_stops = {
        str(key): float(value)
        for key, value in profile["budget"][
            "provider_hard_stops_usd"
        ].items()
    }
    provider_checks: dict[str, dict[str, Any]] = {}
    for provider, projected in provider_projection.items():
        if provider not in hard_stops:
            raise ValueError(f"{provider}のhard stopが設定されていません。")
        limit = hard_stops[provider]
        allowed = limit * args.budget_fraction
        provider_checks[provider] = {
            "projected_cost_usd": round(projected, 6),
            "hard_stop_usd": limit,
            "pass_threshold_usd": round(allowed, 6),
            "headroom_usd": round(limit - projected, 6),
            "passed": projected <= allowed,
        }

    passed = all(item["passed"] for item in provider_checks.values())
    report = {
        "status": "passed" if passed else "failed",
        "runner_revision": RUNNER_REVISION,
        "method": (
            "role/model別Smoke成功ジョブの平均費用 × 正式呼び出し回数 × "
            "役割別安全係数"
        ),
        "budget_fraction": args.budget_fraction,
        "safety_factors": SAFETY_FACTORS,
        "provider_checks": provider_checks,
        "role_model_projection": rows,
        "limitations": [
            "Smokeは小標本のため、安全係数を掛けた保守的な事前推定である。",
            "実行中は各API応答の実測usageでProvider hard stopを継続適用する。",
            "OpenAI cached inputはusage.input_tokens_details.cached_tokensから割引単価で計上する。",
        ],
    }
    args.run_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.run_dir / "00b_full_budget_projection.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("05k Smoke実測からFull予算を判定")
    for provider, item in provider_checks.items():
        status = "OK" if item["passed"] else "NG"
        print(
            f"  {provider}: projected=${item['projected_cost_usd']:.2f}, "
            f"pass threshold=${item['pass_threshold_usd']:.2f}, "
            f"hard stop=${item['hard_stop_usd']:.2f} -> {status}"
        )
    print(f"  report: {output_path}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
