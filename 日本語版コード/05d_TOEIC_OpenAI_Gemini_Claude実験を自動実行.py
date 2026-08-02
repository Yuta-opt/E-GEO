from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from dotenv import load_dotenv


BASE_RUNNER_PATH = Path(__file__).with_name(
    "05c_TOEICメタ最適化API実験を自動実行.py"
)
DEFAULT_MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini_Claude実験設定_v1.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)

Parser = Callable[[str], Any]


def load_base_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "toeic_egeo_internal_runner",
        BASE_RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"内部ランナーを読み込めません: {BASE_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base_module()


@dataclass(frozen=True)
class MultiProviderRole:
    role_name: str
    anonymous_label: str
    provider: str
    api_key_env: str
    model_id: str
    temperature: float | None
    supports_temperature: bool
    max_output_tokens: int
    input_usd_per_million: float
    output_usd_per_million: float

    @classmethod
    def from_dict(
        cls,
        role_name: str,
        value: dict[str, Any],
        anonymous_label: str = "",
    ) -> "MultiProviderRole":
        provider = str(value.get("provider", "")).strip().lower()
        if provider not in {"openai", "google", "anthropic"}:
            raise ValueError(
                f"未対応providerです: role={role_name}, provider={provider}"
            )
        api_key_env = str(value.get("api_key_env", "")).strip()
        if not api_key_env:
            api_key_env = {
                "openai": "OPENAI_API_KEY",
                "google": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            }[provider]
        model_id = str(value.get("model_id", "")).strip()
        if not model_id:
            raise ValueError(f"モデルIDが空です: {role_name}")
        return cls(
            role_name=role_name,
            anonymous_label=anonymous_label,
            provider=provider,
            api_key_env=api_key_env,
            model_id=model_id,
            temperature=(
                float(value["temperature"])
                if value.get("temperature") is not None
                else None
            ),
            supports_temperature=bool(value.get("supports_temperature", False)),
            max_output_tokens=int(value.get("max_output_tokens", 1000)),
            input_usd_per_million=float(value["input_usd_per_million"]),
            output_usd_per_million=float(value["output_usd_per_million"]),
        )

    def cost(self, usage: dict[str, int]) -> float:
        return (
            int(usage.get("input_tokens", 0))
            / 1_000_000
            * self.input_usd_per_million
            + int(usage.get("output_tokens", 0))
            / 1_000_000
            * self.output_usd_per_million
        )


class MultiProviderRunner:
    def __init__(
        self,
        *,
        cache: Any,
        hard_stop_usd: float,
        warning_thresholds: list[float],
        max_retries: int,
        retry_max_wait_seconds: float,
    ) -> None:
        self.cache = cache
        self.hard_stop_usd = hard_stop_usd
        self.warning_thresholds = sorted(warning_thresholds)
        self.max_retries = max_retries
        self.retry_max_wait_seconds = retry_max_wait_seconds
        self.warned: set[float] = set()
        self.clients: dict[str, Any] = {}

    def _check_budget(self) -> None:
        spent = float(self.cache.spent_usd)
        for threshold in self.warning_thresholds:
            if spent >= threshold and threshold not in self.warned:
                print(
                    f"[予算警告] 3社合計の累計概算 ${spent:.2f} "
                    f"（${threshold:.0f}到達）"
                )
                self.warned.add(threshold)
        if spent >= self.hard_stop_usd:
            raise RuntimeError(
                f"3社合計の累計概算${spent:.2f}が"
                f"hard stop ${self.hard_stop_usd:.2f}へ到達しました。"
            )

    def _client(self, role: MultiProviderRole) -> Any:
        if role.provider in self.clients:
            return self.clients[role.provider]
        api_key = os.environ.get(role.api_key_env, "").strip()
        if not api_key:
            raise EnvironmentError(
                f"{role.api_key_env}が.envに設定されていません。"
            )
        if role.provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
        elif role.provider == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
        else:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
        self.clients[role.provider] = client
        return client

    @staticmethod
    def _openai_call(
        client: Any,
        role: MultiProviderRole,
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
        if role.supports_temperature and role.temperature is not None:
            kwargs["temperature"] = role.temperature
        response = client.responses.create(**kwargs)
        text = base.response_text(response).strip()
        usage = base.usage_dict(response)
        return text, usage, getattr(response, "id", None)

    @staticmethod
    def _google_call(
        client: Any,
        role: MultiProviderRole,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, int], str | None]:
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "max_output_tokens": role.max_output_tokens,
        }
        if role.supports_temperature and role.temperature is not None:
            config_kwargs["temperature"] = role.temperature
        response = client.models.generate_content(
            model=role.model_id,
            contents=user_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = str(getattr(response, "text", "") or "").strip()
        metadata = getattr(response, "usage_metadata", None)
        input_tokens = int(
            getattr(metadata, "prompt_token_count", 0) or 0
        )
        visible_output = int(
            getattr(metadata, "candidates_token_count", 0) or 0
        )
        thinking_output = int(
            getattr(metadata, "thoughts_token_count", 0) or 0
        )
        output_tokens = visible_output + thinking_output
        total_tokens = int(
            getattr(metadata, "total_token_count", 0)
            or input_tokens + output_tokens
        )
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "visible_output_tokens": visible_output,
            "thinking_output_tokens": thinking_output,
            "total_tokens": total_tokens,
        }
        response_id = getattr(response, "response_id", None)
        return text, usage, str(response_id) if response_id else None

    @staticmethod
    def _anthropic_call(
        client: Any,
        role: MultiProviderRole,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, int], str | None]:
        kwargs: dict[str, Any] = {
            "model": role.model_id,
            "max_tokens": role.max_output_tokens,
            "system": system_prompt,
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
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        return text, usage, getattr(response, "id", None)

    def _provider_call(
        self,
        role: MultiProviderRole,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, int], str | None]:
        client = self._client(role)
        if role.provider == "openai":
            return self._openai_call(client, role, system_prompt, user_prompt)
        if role.provider == "google":
            return self._google_call(client, role, system_prompt, user_prompt)
        return self._anthropic_call(client, role, system_prompt, user_prompt)

    def generate(
        self,
        *,
        kind: str,
        context_id: str,
        role: MultiProviderRole,
        system_prompt: str,
        user_prompt: str,
        parser: Parser,
    ) -> tuple[str, Any, dict[str, Any]]:
        identity = {
            "kind": kind,
            "context_id": context_id,
            "provider": role.provider,
            "model": role.model_id,
            "temperature": (
                role.temperature if role.supports_temperature else None
            ),
            "system_sha256": base.stable_hash(system_prompt),
            "user_sha256": base.stable_hash(user_prompt),
        }
        job_id = f"{kind}__{base.stable_hash(identity)[:24]}"
        cached = self.cache.get(job_id)
        if cached is not None:
            return str(cached["output_text"]), cached.get("parsed"), cached

        self._check_budget()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started = base.utc_now()
            usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            cost = 0.0
            try:
                text, usage, response_id = self._provider_call(
                    role,
                    system_prompt,
                    user_prompt,
                )
                if not text:
                    raise ValueError("API応答が空です。")
                parsed = parser(text)
                cost = role.cost(usage)
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
                    "error": str(exc),
                    "usage": usage,
                    "cost_usd": cost,
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


def load_model_roles(
    profile: dict[str, Any],
) -> tuple[
    MultiProviderRole,
    MultiProviderRole,
    list[MultiProviderRole],
    list[MultiProviderRole],
]:
    roles = profile["roles"]
    rewriter = MultiProviderRole.from_dict("rewriter", roles["rewriter"])
    meta = MultiProviderRole.from_dict(
        "meta_optimizer",
        roles["meta_optimizer"],
    )
    training = [
        MultiProviderRole.from_dict(
            "training_reranker",
            item,
            anonymous_label=str(item["anonymous_label"]),
        )
        for item in roles["training_rerankers"]
    ]
    heldout = [
        MultiProviderRole.from_dict(
            "heldout_reranker",
            item,
            anonymous_label=str(item["anonymous_label"]),
        )
        for item in roles["heldout_rerankers"]
    ]
    return rewriter, meta, training, heldout


def required_key_envs(roles: list[MultiProviderRole]) -> list[str]:
    return sorted({role.api_key_env for role in roles})


def write_cost_ledger(cache: Any, path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for event in cache.events:
        usage = event.get("usage", {})
        rows.append(
            {
                "finished_at": event.get("finished_at", ""),
                "status": event.get("status", ""),
                "kind": event.get("kind", ""),
                "role": event.get("role", ""),
                "anonymous_label": event.get("anonymous_label", ""),
                "provider": event.get("provider", ""),
                "model": event.get("model", ""),
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
                "cost_usd": float(event.get("cost_usd", 0) or 0),
                "job_id": event.get("job_id", ""),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["cumulative_cost_usd"] = frame["cost_usd"].cumsum()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "OPENAI_API_KEY・GEMINI_API_KEY・ANTHROPIC_API_KEYを使い、"
            "OpenAI、Gemini、Claudeを分離したE-GEOメタ最適化実験を実行する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=base.DEFAULT_INSTANCES)
    parser.add_argument(
        "--initial-prompts",
        type=Path,
        default=base.DEFAULT_INITIAL_PROMPTS,
    )
    parser.add_argument(
        "--common-prompts",
        type=Path,
        default=base.DEFAULT_COMMON_PROMPTS,
    )
    parser.add_argument("--meta-prompt", type=Path, default=base.DEFAULT_META_PROMPT)
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=base.DEFAULT_EXPERIMENT_CONFIG,
    )
    parser.add_argument("--model-profile", type=Path, default=DEFAULT_MODEL_PROFILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--prompt-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--require-keys", action="store_true")
    parser.add_argument("--skip-test", action="store_true")
    parser.add_argument("--hard-stop-usd", type=float)
    args = parser.parse_args()

    load_dotenv()
    model_profile = base.read_json(args.model_profile)
    experiment_config = base.read_json(args.experiment_config)
    common = base.read_json(args.common_prompts)
    meta_config = base.read_json(args.meta_prompt)
    prompts = base.prompt_catalog(base.read_json(args.initial_prompts))
    rewriter, meta, training_rerankers, heldout_rerankers = load_model_roles(
        model_profile
    )
    all_roles = [rewriter, meta, *training_rerankers, *heldout_rerankers]
    key_envs = required_key_envs(all_roles)
    key_status = {
        name: bool(os.environ.get(name, "").strip()) for name in key_envs
    }

    print("05d OpenAI・Gemini・Claude 3社モデル実験ランナー")
    print(f"  Rewriter: {rewriter.provider}/{rewriter.model_id}")
    print(f"  Meta-optimizer: {meta.provider}/{meta.model_id}")
    print(
        "  Training Re-rankers: "
        + ", ".join(
            f"{role.anonymous_label}={role.provider}/{role.model_id}"
            for role in training_rerankers
        )
    )
    print(
        "  Held-out Re-rankers: "
        + ", ".join(
            f"{role.anonymous_label}={role.provider}/{role.model_id}"
            for role in heldout_rerankers
        )
    )
    for name, present in key_status.items():
        print(f"  {name}: {'設定済み' if present else '未設定'}")

    if (args.require_keys or args.execute) and not all(key_status.values()):
        missing = [name for name, present in key_status.items() if not present]
        raise EnvironmentError(
            "必要なAPIキーが不足しています: " + ", ".join(missing)
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.instances.exists():
        plan = {
            "created_at": base.utc_now(),
            "status": "waiting_for_candidate_selection",
            "api_calls": 0,
            "model_profile": str(args.model_profile),
            "required_api_key_envs": key_envs,
            "key_status": key_status,
            "next_required_file": str(args.instances),
        }
        (args.output_dir / "00_execution_plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if args.execute:
            raise FileNotFoundError(
                "候補10件と対象商品が未確定です。先に04bを全80件で実行してください。"
            )
        print("  候補10件の確定前なので、モデル設定とキーだけ検査しました。")
        print("  API呼び出し: 0回")
        return

    require_full = args.mode == "full"
    instances = base.validate_and_index_instances(
        base.read_json(args.instances),
        require_full=require_full,
    )
    if args.prompt_id:
        prompts = [
            prompt
            for prompt in prompts
            if str(prompt["id"]) == args.prompt_id
        ]
        if not prompts:
            raise ValueError(f"prompt-idが見つかりません: {args.prompt_id}")
    elif args.mode == "smoke":
        prompts = prompts[:1]

    train_ids_all = base.select_ids(instances, "train")
    validation_ids_all = base.select_ids(instances, "validation")
    test_ids_all = base.select_ids(instances, "test")
    if args.mode == "full":
        optimization = experiment_config["optimization"]
        train_ids = train_ids_all
        validation_ids = validation_ids_all
        test_ids = test_ids_all
        schedule = base.deterministic_batches(
            train_ids,
            epochs=int(optimization["epochs"]),
            batches_per_epoch=int(optimization["batches_per_epoch"]),
            batch_size=int(optimization["batch_size"]),
            seed=int(optimization["numpy_seed"]),
        )
    else:
        if (
            len(train_ids_all) < 2
            or len(validation_ids_all) < 1
            or len(test_ids_all) < 1
        ):
            raise ValueError(
                "smokeにはTrain 2件、Validation 1件、Test 1件が必要です。"
            )
        train_ids = train_ids_all[:2]
        validation_ids = validation_ids_all[:1]
        test_ids = test_ids_all[:1]
        schedule = [
            {
                "epoch": 1,
                "batch": 1,
                "intent_ids": [train_ids[0]],
                "meta_update_after": True,
            },
            {
                "epoch": 1,
                "batch": 2,
                "intent_ids": [train_ids[1]],
                "meta_update_after": False,
            },
        ]

    plan = base.plan_summary(
        args.mode,
        len(prompts),
        len(train_ids),
        len(validation_ids),
        len(test_ids),
        len(schedule),
        len(training_rerankers),
        len(heldout_rerankers),
    )
    (args.output_dir / "00_execution_plan.json").write_text(
        json.dumps(
            {
                **plan,
                "created_at": base.utc_now(),
                "execute": bool(args.execute),
                "test_locked": True,
                "model_profile": str(args.model_profile),
                "required_api_key_envs": key_envs,
                "key_status": key_status,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.execute:
        print("API呼び出し: 0回。--executeを付けると3社APIを実行します。")
        return

    budget = model_profile["budget"]
    hard_stop = (
        float(args.hard_stop_usd)
        if args.hard_stop_usd is not None
        else float(budget["default_hard_stop_usd"])
    )
    execution = model_profile["execution"]
    cache = base.LLMCache(args.output_dir / "01_llm_cache.jsonl")
    api = MultiProviderRunner(
        cache=cache,
        hard_stop_usd=hard_stop,
        warning_thresholds=[
            float(item) for item in budget["warning_thresholds_usd"]
        ],
        max_retries=int(execution["max_retries"]),
        retry_max_wait_seconds=float(execution["retry_max_wait_seconds"]),
    )

    rewriter_system_prompt = str(
        common["rewriter_system_prompt"]["faithful_translation_ja"]
    )
    ranking_template = str(
        common["ranking_user_prompt"]["faithful_translation_ja"]
    )
    meta_system_prompt = str(
        meta_config["system_prompt"]["faithful_translation_ja"]
    )
    meta_user_template = str(
        meta_config["user_prompt"]["faithful_translation_ja"]
    )

    all_versions: list[dict[str, Any]] = []
    final_prompts: dict[str, dict[str, Any]] = {}
    for prompt in prompts:
        versions, final = base.run_trajectory(
            api=api,
            prompt=prompt,
            instances=instances,
            train_ids=train_ids,
            validation_ids=validation_ids,
            schedule=schedule,
            rewriter=rewriter,
            meta=meta,
            training_rerankers=training_rerankers,
            rewriter_system_prompt=rewriter_system_prompt,
            ranking_template=ranking_template,
            meta_system_prompt=meta_system_prompt,
            meta_user_template=meta_user_template,
        )
        all_versions.extend(versions)
        final_prompts[str(prompt["id"])] = final

    base.write_jsonl(
        args.output_dir / "02_optimization_versions.jsonl",
        all_versions,
    )
    (args.output_dir / "03_final_prompts.json").write_text(
        json.dumps(list(final_prompts.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    test_rows: list[dict[str, Any]] = []
    if not args.skip_test:
        test_rows = base.run_test(
            api=api,
            prompts=prompts,
            final_prompts=final_prompts,
            instances=instances,
            test_ids=test_ids,
            rewriter=rewriter,
            heldout_rerankers=heldout_rerankers,
            rewriter_system_prompt=rewriter_system_prompt,
            ranking_template=ranking_template,
        )
        base.write_jsonl(
            args.output_dir / "04_test_results.jsonl",
            test_rows,
        )

    write_cost_ledger(cache, args.output_dir / "05_cost_ledger.csv")
    summary = {
        "completed_at": base.utc_now(),
        "mode": args.mode,
        "status": (
            "complete"
            if not args.skip_test
            else "optimization_complete_test_skipped"
        ),
        "provider_configuration": "OpenAI + Google Gemini + Anthropic Claude",
        "prompt_count": len(prompts),
        "optimization_version_count": len(all_versions),
        "test_result_rows": len(test_rows),
        "total_api_cost_usd_estimate": round(cache.spent_usd, 6),
        "hard_stop_usd": hard_stop,
        "test_locked_until_prompt_freeze": True,
        "short_test_used_only_after_prompt_freeze": True,
        "model_profile": str(args.model_profile),
        "limitations": model_profile["formal_use_policy"]["limitation"],
    }
    (args.output_dir / "06_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n05d完了")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
