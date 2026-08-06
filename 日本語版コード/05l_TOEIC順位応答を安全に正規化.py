from __future__ import annotations

"""順位JSONの重複だけを安全に正規化し、支払済み失敗応答を再利用する。

05iのモデル呼び出し・費用制御・Test共有リライトは変更しない。
ランキングが1〜10をすべて含み、余分な値が同じ番号の重複だけの場合に限り、
最初に現れた順を保って重複を除去する。欠番・範囲外は従来どおり失敗する。
また、実行中のProvider表示と実行サマリーはモデル設定から自動生成する。
"""

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


FINAL_RUNNER = Path(__file__).with_name("05i_TOEIC最終安全実行.py")
RANKING_PARSER_REVISION = "ranking-duplicate-only-normalization-v1"
PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "google": "Google Gemini",
    "anthropic": "Anthropic Claude",
}


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


final = load_module(FINAL_RUNNER, "toeic_egeo_final_runner_with_rank_recovery")
base = final.base
ORIGINAL_FINAL_GENERATE = final.final_generate


def unique_in_first_occurrence_order(values: list[int]) -> list[int]:
    seen: set[int] = set()
    output: list[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def safe_parse_ranking(text: str) -> dict[str, Any]:
    value = base.extract_json_object(text)
    raw_ranking = [int(item) for item in value.get("ranking", [])]
    raw_questionable = [
        int(item) for item in value.get("questionable_products", [])
    ]

    if not raw_ranking:
        raise ValueError("rankingが空です。")
    if any(item < 1 or item > 10 for item in raw_ranking):
        raise ValueError(
            f"rankingに1〜10以外が含まれています: {raw_ranking}"
        )

    ranking = unique_in_first_occurrence_order(raw_ranking)
    expected = list(range(1, 11))
    if len(ranking) != 10 or sorted(ranking) != expected:
        raise ValueError(
            "rankingは1〜10をすべて含み、余分な値は重複だけである必要が"
            f"あります: {raw_ranking}"
        )

    if any(item < 1 or item > 10 for item in raw_questionable):
        raise ValueError(
            "questionable_productsに1〜10以外が含まれています。"
        )
    questionable = unique_in_first_occurrence_order(raw_questionable)

    return {
        "ranking": ranking,
        "questionable_products": questionable,
        "ranking_normalized": ranking != raw_ranking,
        "raw_ranking": raw_ranking,
        "questionable_products_normalized": questionable != raw_questionable,
        "raw_questionable_products": raw_questionable,
        "ranking_parser_revision": RANKING_PARSER_REVISION,
    }


def generation_identity(
    *,
    kind: str,
    context_id: str,
    role: Any,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    return {
        "runner_revision": final.RUNNER_REVISION,
        "kind": kind,
        "context_id": context_id,
        "provider": role.provider,
        "model": role.model_id,
        "temperature": (
            role.temperature if role.supports_temperature else None
        ),
        "reasoning_effort": (
            "minimal" if str(role.model_id).startswith("gpt-5") else None
        ),
        "system_sha256": base.stable_hash(system_prompt),
        "user_sha256": base.stable_hash(user_prompt),
    }


def recover_parseable_failed_event(
    self: Any,
    *,
    job_id: str,
    kind: str,
    parser: Any,
    identity: dict[str, Any],
) -> tuple[str, Any, dict[str, Any]] | None:
    if kind != "rerank":
        return None

    events = getattr(self.cache, "events", [])
    for prior in reversed(events):
        if str(prior.get("job_id", "")) != job_id:
            continue
        if prior.get("status") != "failed":
            continue
        text = str(prior.get("output_text", "") or "").strip()
        if not text:
            continue
        try:
            parsed = parser(text)
        except Exception:
            continue

        timestamp = base.utc_now()
        observed_cost = float(prior.get("cost_usd", 0) or 0)
        recovered = {
            "job_id": job_id,
            "status": "success",
            "kind": kind,
            "context_id": prior.get("context_id", ""),
            "role": prior.get("role", ""),
            "anonymous_label": prior.get("anonymous_label", ""),
            "provider": prior.get("provider", ""),
            "model": prior.get("model", ""),
            "attempt": 0,
            "output_text": text,
            "parsed": parsed,
            "usage": prior.get("usage", final.empty_usage()),
            "cost_usd": 0.0,
            "response_id": prior.get("response_id"),
            "started_at": timestamp,
            "finished_at": timestamp,
            "identity": identity,
            "recovered_without_api_call": True,
            "recovered_from_failed_attempt": prior.get("attempt"),
            "recovered_from_response_id": prior.get("response_id"),
            "recovered_call_cost_usd": observed_cost,
            "prior_cost_already_recorded_usd": observed_cost,
            "ranking_parser_revision": RANKING_PARSER_REVISION,
        }
        self.cache.add(recovered)
        print(
            f"[rerank_recover] {job_id} "
            "追加APIなしで支払済み応答を正規化して再利用"
        )
        return text, parsed, recovered
    return None


def recovery_generate(
    self: Any,
    *,
    kind: str,
    context_id: str,
    role: Any,
    system_prompt: str,
    user_prompt: str,
    parser: Any,
) -> tuple[str, Any, dict[str, Any]]:
    identity = generation_identity(
        kind=kind,
        context_id=context_id,
        role=role,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    job_id = f"{kind}__{base.stable_hash(identity)[:24]}"

    cached = self.cache.get(job_id)
    if cached is not None:
        return str(cached["output_text"]), cached.get("parsed"), cached

    recovered = recover_parseable_failed_event(
        self,
        job_id=job_id,
        kind=kind,
        parser=parser,
        identity=identity,
    )
    if recovered is not None:
        return recovered

    return ORIGINAL_FINAL_GENERATE(
        self,
        kind=kind,
        context_id=context_id,
        role=role,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        parser=parser,
    )


def argument_value(flag: str) -> str | None:
    for index, value in enumerate(sys.argv):
        if value == flag and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def active_provider_metadata() -> tuple[list[str], str]:
    profile_path = Path(
        argument_value("--model-profile")
        or str(final.budgeted.DEFAULT_MODEL_PROFILE)
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    roles = profile["roles"]
    role_values = [
        roles["rewriter"],
        roles["meta_optimizer"],
        *roles["training_rerankers"],
        *roles["heldout_rerankers"],
    ]
    providers: list[str] = []
    for role in role_values:
        provider = str(role["provider"]).strip().lower()
        if provider not in providers:
            providers.append(provider)
    display = " + ".join(
        PROVIDER_DISPLAY_NAMES.get(provider, provider)
        for provider in providers
    )
    return providers, display


def annotate_parser_summary(
    providers: list[str],
    provider_configuration: str,
) -> None:
    output_dir = final.budgeted.output_dir_from_argv()
    summary_path = output_dir / "06_run_summary.json"
    if not summary_path.exists():
        return

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["provider_configuration"] = provider_configuration
    summary["active_providers"] = providers
    patches = summary.setdefault("final_safety_patches", {})
    patches["ranking_parser_revision"] = RANKING_PARSER_REVISION
    patches["duplicate_only_ranking_normalization"] = True
    patches["failed_rerank_response_recovery_without_api_call"] = True
    patches["provider_configuration_derived_from_profile"] = True
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_with_provider_aware_output(provider_configuration: str) -> None:
    original_print = builtins.print

    def provider_aware_print(*args: Any, **kwargs: Any) -> None:
        values = list(args)
        if len(values) == 1 and isinstance(values[0], str):
            text = values[0]
            text = text.replace(
                "05d OpenAI・Gemini・Claude 3社モデル実験ランナー",
                f"05d {provider_configuration} モデル実験ランナー",
            )
            text = text.replace("3社合計", "全Provider合計")
            text = text.replace(
                "--executeを付けると3社APIを実行します。",
                f"--executeを付けると{provider_configuration} APIを実行します。",
            )
            values[0] = text
        original_print(*values, **kwargs)

    builtins.print = provider_aware_print
    try:
        final.main()
    finally:
        builtins.print = original_print


def main() -> None:
    providers, provider_configuration = active_provider_metadata()
    base.parse_ranking = safe_parse_ranking
    final.final_generate = recovery_generate
    run_with_provider_aware_output(provider_configuration)
    annotate_parser_summary(providers, provider_configuration)


if __name__ == "__main__":
    main()
