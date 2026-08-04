from __future__ import annotations

"""E-GEO先行研究に合わせた3社版ランナー。

既存05dのAPI接続・キャッシュ・費用上限処理を再利用しつつ、次を修正する。

1. Meta-optimizerへ渡す履歴はTrain結果だけとし、Validationを漏らさない。
2. Train履歴には各版のプロンプト本文とエンジン別スコアを保持する。
3. Re-rankerには原著コードのモデルファミリー別System Promptを使う。
4. Rewriterへは、原著実装に合わせて商品名＋商品説明を渡す。
5. 15プロンプト、2 epochs、4 batches、各8評価版、40/10/30を維持する。

APIは --execute を付けない限り呼び出さない。
"""

import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_MULTI_PROVIDER_RUNNER = Path(__file__).with_name(
    "05d_TOEIC_OpenAI_Gemini_Claude実験を自動実行.py"
)
ORIGINAL_PROMPTS_PATH = REPO_ROOT / "src/multi_model_optimization/prompts.py"
COMPLIANT_EXPERIMENT_CONFIG = Path(
    "日本語版設定/TOEIC_EGEO実験設定_v3_先行研究準拠.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)


def load_module(path: Path, module_name: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"必要なコードが見つかりません: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


legacy = load_module(
    LEGACY_MULTI_PROVIDER_RUNNER,
    "toeic_egeo_multi_provider_legacy",
)
base = legacy.base


@lru_cache(maxsize=1)
def original_family_prompts() -> dict[str, str]:
    prompts = load_module(
        ORIGINAL_PROMPTS_PATH,
        "toeic_egeo_original_reranker_prompts",
    )
    return {
        "gpt41": str(prompts.get_gpt41_prompt()),
        "gpt5": str(prompts.get_gpt5_prompt()),
        "gemini": str(prompts.get_gemini_prompt()),
        "claude": str(prompts.get_claude_prompt()),
    }


def family_system_prompt(role: Any) -> str:
    prompts = original_family_prompts()
    provider = str(getattr(role, "provider", "")).lower()
    model_id = str(getattr(role, "model_id", "")).lower()

    if provider == "openai":
        return prompts["gpt5"] if "gpt-5" in model_id else prompts["gpt41"]
    if provider == "google":
        return prompts["gemini"]
    if provider == "anthropic":
        return prompts["claude"]
    raise ValueError(
        f"モデルファミリー別System Promptを選べません: "
        f"provider={provider}, model={model_id}"
    )


def train_only_history_text(history: list[dict[str, Any]]) -> str:
    """原著と同様に、Trainのプロンプト本文とエンジン別結果だけを渡す。

    Validationは版選択専用であり、次のプロンプト生成には一切渡さない。
    """
    if not history:
        return ""

    lines = ["\nPREVIOUS OPTIMIZATION HISTORY (TRAIN RESULTS ONLY):"]
    for item in history:
        lines.append(
            f"\nVersion {item['version_number']} "
            f"({item['version_label']}):"
        )
        prompt_text = str(item.get("prompt_text", ""))
        prompt_preview = (
            prompt_text[:1200] + "..."
            if len(prompt_text) > 1200
            else prompt_text
        )
        lines.append(f"Prompt:\n{prompt_preview}")

        train_summary = item["train_summary"]
        for label, mean in train_summary.get("engine_means", {}).items():
            lines.append(
                f"  {label}: mean rank improvement = {float(mean):+.4f}"
            )
        lines.append(
            "  Aggregate: "
            f"overall mean={float(train_summary['overall_mean']):+.4f}, "
            f"worst engine={float(train_summary['worst_engine_mean']):+.4f}, "
            f"best engine={float(train_summary['best_engine_mean']):+.4f}, "
            f"cross-engine std={float(train_summary['cross_engine_std']):.4f}"
        )

        meta_update = item.get("meta_update") or {}
        reasoning = str(meta_update.get("meta_reasoning", "")).strip()
        if reasoning:
            reasoning_preview = (
                reasoning[:800] + "..." if len(reasoning) > 800 else reasoning
            )
            lines.append(f"Previous meta-reasoning:\n{reasoning_preview}")

    return "\n".join(lines)


def full_product_text(instance: dict[str, Any]) -> str:
    product = base.target_product(instance)
    title = base.clean_text(product.get("title", ""))
    description = base.clean_text(product.get("description", ""))
    if not title and not description:
        raise ValueError(f"{instance.get('intent_id')}: 対象商品の文章が空です。")
    return f"商品名: {title}\n商品説明: {description}".strip()


def compliant_rewrite_description(
    api: Any,
    role: Any,
    system_prompt: str,
    instance: dict[str, Any],
    rewriting_prompt: str,
    context_id: str,
) -> tuple[str, dict[str, Any]]:
    """原著実装と同様に、対象listing全体をRewriterへ渡す。"""
    user_prompt = base.replace_description(
        rewriting_prompt,
        full_product_text(instance),
    )
    _, parsed, record = api.generate(
        kind="rewrite",
        context_id=context_id,
        role=role,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        parser=base.parse_rewrite,
    )
    return str(parsed), record


def compliant_format_products(
    instance: dict[str, Any],
    rewritten_description: str | None,
) -> str:
    """対象商品はリライト後listing全体で置換する。"""
    lines: list[str] = []
    target_position = int(instance["target_candidate_position"])
    products = sorted(
        instance["products"],
        key=lambda item: int(item["candidate_position"]),
    )
    for product in products:
        position = int(product["candidate_position"])
        if position == target_position and rewritten_description is not None:
            lines.append(
                f"{position}. {base.clean_text(rewritten_description)}"
            )
            continue
        lines.append(
            f"{position}. 商品名: {base.clean_text(product.get('title', ''))}\n"
            f"商品説明: {base.clean_text(product.get('description', ''))}"
        )
    return "\n\n".join(lines)


def compliant_rank_instance(
    api: Any,
    role: Any,
    ranking_template: str,
    instance: dict[str, Any],
    query_form: str,
    rewritten_description: str | None,
    context_id: str,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    query = base.clean_text(instance["queries"][query_form])
    user_prompt = ranking_template.format(
        query=query,
        formatted_products=compliant_format_products(
            instance,
            rewritten_description,
        ),
    )
    _, parsed, record = api.generate(
        kind="rerank",
        context_id=context_id,
        role=role,
        system_prompt=family_system_prompt(role),
        user_prompt=user_prompt,
        parser=base.parse_ranking,
    )
    target_position = int(instance["target_candidate_position"])
    rank = list(parsed["ranking"]).index(target_position) + 1
    return rank, parsed, record


def install_prior_study_patches() -> None:
    base.history_text = train_only_history_text
    base.rewrite_description = compliant_rewrite_description
    base.format_products = compliant_format_products
    base.rank_instance = compliant_rank_instance

    base.DEFAULT_EXPERIMENT_CONFIG = COMPLIANT_EXPERIMENT_CONFIG
    legacy.DEFAULT_OUTPUT_DIR = DEFAULT_OUTPUT_DIR


def output_dir_from_argv() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--output-dir" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_OUTPUT_DIR


def annotate_run_summary() -> None:
    summary_path = output_dir_from_argv() / "06_run_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["prior_study_compliance"] = {
        "validation_visible_to_meta_optimizer": False,
        "meta_optimizer_history": (
            "training prompt text and per-engine training results only"
        ),
        "reranker_system_prompts": (
            "model-family-specific prompts from "
            "src/multi_model_optimization/prompts.py"
        ),
        "rewriter_input": "target listing title + description; query blind",
        "prompt_count": 15,
        "epochs": 2,
        "batches_per_epoch": 4,
        "evaluated_versions_per_prompt": 8,
        "scaled_replication_note": (
            "The prior study used 4 training rerankers and 10 batches per epoch; "
            "this budget-scaled Japanese replication uses GPT-4.1 and Gemini "
            "with 4 batches per epoch."
        ),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    install_prior_study_patches()
    legacy.main()
    annotate_run_summary()


if __name__ == "__main__":
    main()
