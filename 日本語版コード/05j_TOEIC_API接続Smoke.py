from __future__ import annotations

"""実データを使わず、正式モデル・Parser・費用記録だけを少額確認する。"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


FINAL_RUNNER = Path(__file__).with_name("05i_TOEIC最終安全実行.py")
DEFAULT_EXPERIMENT_CONFIG = Path(
    "日本語版設定/TOEIC_EGEO実験設定_v3_先行研究準拠.json"
)
DEFAULT_MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini実験設定_v1.json"
)
DEFAULT_COMMON_PROMPTS = Path(
    "日本語版設定/E_GEO先行研究_共通プロンプト設定.json"
)
DEFAULT_META_PROMPT = Path(
    "日本語版設定/E_GEO先行研究_メタ最適化設定.json"
)
DEFAULT_INITIAL_PROMPTS = Path(
    "日本語版設定/E_GEO先行研究_初期プロンプト15種.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/00_API接続Smoke"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


final = load_module(FINAL_RUNNER, "toeic_egeo_final_connectivity")
budgeted = final.budgeted
legacy = final.legacy
base = final.base
prior = final.prior


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def dummy_products() -> str:
    rows = []
    for index in range(1, 11):
        rows.append(
            f"{index}. 商品名: TOEIC教材{index}\n"
            f"商品説明: TOEIC学習用の確認商品{index}です。"
        )
    return "\n\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "正式実験の前に、Rewriter・Meta-optimizer・全Re-rankerの"
            "接続、Parser、usage、費用記録をダミーデータで確認する。"
        )
    )
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
        "--common-prompts",
        type=Path,
        default=DEFAULT_COMMON_PROMPTS,
    )
    parser.add_argument(
        "--meta-prompt",
        type=Path,
        default=DEFAULT_META_PROMPT,
    )
    parser.add_argument(
        "--initial-prompts",
        type=Path,
        default=DEFAULT_INITIAL_PROMPTS,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hard-stop-usd", type=float, default=3.0)
    parser.add_argument("--require-keys", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    profile = read_json(args.model_profile)
    experiment = read_json(args.experiment_config)
    common = read_json(args.common_prompts)
    meta_config = read_json(args.meta_prompt)
    prompt_catalog = read_json(args.initial_prompts)
    prompts = base.prompt_catalog(prompt_catalog)

    rewriter, meta, training, heldout = legacy.load_model_roles(profile)
    roles = [rewriter, meta, *training, *heldout]
    key_envs = legacy.required_key_envs(roles)
    key_status = {
        name: bool(os.environ.get(name, "").strip()) for name in key_envs
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "status": "dry_run" if not args.execute else "running",
        "api_calls_planned": 2 + len(training) + len(heldout),
        "model_profile": str(args.model_profile),
        "experiment_schema": experiment.get("schema_version"),
        "required_api_key_envs": key_envs,
        "key_status": key_status,
        "uses_real_research_data": False,
        "tests": [
            "rewriter parser",
            "meta-optimizer parser",
            "all configured training rerankers",
            "all configured held-out rerankers",
            "usage and cost ledger",
        ],
    }
    (args.output_dir / "00_connectivity_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if (args.require_keys or args.execute) and not all(key_status.values()):
        missing = [name for name, present in key_status.items() if not present]
        raise EnvironmentError(
            "接続Smokeに必要なAPIキーが不足しています: "
            + ", ".join(missing)
        )

    print("05j API接続Smoke")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.execute:
        print("API呼び出し: 0回")
        return

    final.final_install_cost_controls(profile)
    execution = profile["execution"]
    cache = base.LLMCache(args.output_dir / "01_llm_cache.jsonl")
    api = legacy.MultiProviderRunner(
        cache=cache,
        hard_stop_usd=float(args.hard_stop_usd),
        warning_thresholds=[1.0, 2.0],
        max_retries=int(execution["max_retries"]),
        retry_max_wait_seconds=float(
            execution["retry_max_wait_seconds"]
        ),
    )

    rewriter_system = str(
        common["rewriter_system_prompt"]["faithful_translation_ja"]
    )
    rewrite_prompt = str(prompts[0]["faithful_translation_ja"])
    rewrite_user = base.replace_description(
        rewrite_prompt,
        "商品名: TOEIC確認教材\n商品説明: 基礎から学べる確認用教材です。",
    )
    api.generate(
        kind="connectivity_rewrite",
        context_id="dummy_rewrite",
        role=rewriter,
        system_prompt=rewriter_system,
        user_prompt=rewrite_user,
        parser=base.parse_rewrite,
    )

    meta_system = str(
        meta_config["system_prompt"]["faithful_translation_ja"]
    )
    meta_template = str(
        meta_config["user_prompt"]["faithful_translation_ja"]
    )
    meta_user = meta_template.format(
        current_prompt=rewrite_prompt,
        batch_size=1,
        per_engine_stats_text=(
            "• Model A: mean rank improvement = 1.0000\n"
            "• Model B: mean rank improvement = 0.5000"
        ),
        worst_engine_mean="0.5000",
        best_engine_mean="1.0000",
        cross_engine_std="0.2500",
        engines_positive=2,
        engines_total=2,
        history_section="",
    )
    api.generate(
        kind="connectivity_meta_optimizer",
        context_id="dummy_meta",
        role=meta,
        system_prompt=meta_system,
        user_prompt=meta_user,
        parser=base.parse_meta_output,
    )

    ranking_template = str(
        common["ranking_user_prompt"]["faithful_translation_ja"]
    )
    ranking_user = ranking_template.format(
        query="TOEIC初心者向けの教材を探しています",
        formatted_products=dummy_products(),
    )
    reranker_results = []
    for role in [*training, *heldout]:
        _, parsed, record = api.generate(
            kind="connectivity_rerank",
            context_id=(
                f"dummy_rerank__{role.provider}__"
                f"{role.anonymous_label}"
            ),
            role=role,
            system_prompt=prior.family_system_prompt(role),
            user_prompt=ranking_user,
            parser=base.parse_ranking,
        )
        reranker_results.append(
            {
                "anonymous_label": role.anonymous_label,
                "provider": role.provider,
                "model": role.model_id,
                "ranking_count": len(parsed["ranking"]),
                "job_id": record["job_id"],
            }
        )

    provider_costs = budgeted.provider_spend(cache)
    summary = {
        "status": "passed",
        "api_calls_completed": len(
            [event for event in cache.events if event.get("status") == "success"]
        ),
        "failed_attempts": len(
            [event for event in cache.events if event.get("status") == "failed"]
        ),
        "provider_cost_usd": provider_costs,
        "total_cost_usd": round(float(cache.spent_usd), 6),
        "rerankers": reranker_results,
        "safety_checks": {
            "all_configured_providers_called": (
                set(provider_costs)
                == {str(role.provider) for role in roles}
            ),
            "all_ranking_parsers_returned_10_items": all(
                item["ranking_count"] == 10 for item in reranker_results
            ),
            "cost_recorded": float(cache.spent_usd) > 0,
        },
    }
    if not all(summary["safety_checks"].values()):
        summary["status"] = "failed"
    (args.output_dir / "02_connectivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
