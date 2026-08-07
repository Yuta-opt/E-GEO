from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from dotenv import load_dotenv


BASE_RUNNER_PATH = Path(__file__).resolve().parents[1] / "日本語版コード" / "05c_TOEICメタ最適化API実験を自動実行.py"
DEFAULT_CONFIG = Path("日本語版設定/TOEIC_Claude_Heldout評価_v1.json")
DEFAULT_INSTANCES = Path("日本語版データ/TOEIC/04_候補商品/08_toeic_experiment_instances.json")
DEFAULT_SOURCE_RESULTS = Path("日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/04_test_results.jsonl")
DEFAULT_SOURCE_SUMMARY = Path("日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行/06_run_summary.json")
DEFAULT_INITIAL_PROMPTS = Path("日本語版設定/E_GEO先行研究_初期プロンプト15種.json")
DEFAULT_COMMON_PROMPTS = Path("日本語版設定/E_GEO先行研究_共通プロンプト設定.json")
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/05_API実験/03_Claude_Heldout評価")

Parser = Callable[[str], Any]


def load_base_module() -> Any:
    spec = importlib.util.spec_from_file_location("toeic_egeo_claude_base", BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"内部ランナーを読み込めません: {BASE_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base_module()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONLが見つかりません: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: JSONを読めません。") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: JSON objectではありません。")
        rows.append(value)
    return rows


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return base.utc_now()


def append_jsonl_with_retry(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, ensure_ascii=False) + "\n"
    last_error: OSError | None = None
    for attempt in range(1, 121):
        try:
            with path.open("a", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
            if attempt > 1:
                print(f"[cache_write_recovered] {attempt}回目で追記を再開しました。")
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            if attempt == 1:
                print("[cache_write_retry] 一時的なファイルロックを検出しました。自動再試行します。")
            time.sleep(2.0)
    raise PermissionError(f"キャッシュへ追記できません: {path}: {last_error}")


def parse_ranking_safe(text: str) -> dict[str, Any]:
    value = base.extract_json_object(text)
    raw_ranking = [int(item) for item in value.get("ranking", [])]
    questionable = [int(item) for item in value.get("questionable_products", [])]

    ranking = raw_ranking
    if len(raw_ranking) != 10 or sorted(raw_ranking) != list(range(1, 11)):
        deduplicated: list[int] = []
        for item in raw_ranking:
            if item not in deduplicated:
                deduplicated.append(item)
        if len(deduplicated) == 10 and sorted(deduplicated) == list(range(1, 11)):
            ranking = deduplicated
        else:
            raise ValueError(f"rankingは1〜10を一度ずつ含む必要があります: {raw_ranking}")

    if len(set(questionable)) != len(questionable):
        raise ValueError("questionable_productsが重複しています。")
    if any(item < 1 or item > 10 for item in questionable):
        raise ValueError("questionable_productsに1〜10以外が含まれています。")
    return {"ranking": ranking, "questionable_products": questionable}


@dataclass(frozen=True)
class ClaudeRole:
    role_name: str
    anonymous_label: str
    provider: str
    api_key_env: str
    model_id: str
    temperature: float
    max_output_tokens: int
    input_usd_per_million: float
    output_usd_per_million: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ClaudeRole":
        model = config["model"]
        return cls(
            role_name="heldout_reranker",
            anonymous_label=str(model["anonymous_label"]),
            provider="anthropic",
            api_key_env=str(model["api_key_env"]),
            model_id=str(model["model_id"]),
            temperature=float(model["temperature"]),
            max_output_tokens=int(model["max_output_tokens"]),
            input_usd_per_million=float(model["input_usd_per_million"]),
            output_usd_per_million=float(model["output_usd_per_million"]),
        )

    def cost(self, usage: dict[str, int]) -> float:
        input_total = (
            int(usage.get("input_tokens", 0))
            + int(usage.get("cache_creation_input_tokens", 0))
            + int(usage.get("cache_read_input_tokens", 0))
        )
        return (
            input_total / 1_000_000 * self.input_usd_per_million
            + int(usage.get("output_tokens", 0))
            / 1_000_000
            * self.output_usd_per_million
        )


class ClaudeCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.success: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        if path.exists():
            for row in read_jsonl(path):
                self.events.append(row)
                if row.get("status") == "success" and row.get("job_id"):
                    self.success[str(row["job_id"])] = row

    @property
    def spent_usd(self) -> float:
        return float(sum(float(row.get("cost_usd", 0) or 0) for row in self.events))

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.success.get(job_id)

    def add(self, row: dict[str, Any]) -> None:
        append_jsonl_with_retry(self.path, row)
        self.events.append(row)
        if row.get("status") == "success":
            self.success[str(row["job_id"])] = row


class ClaudeRunner:
    def __init__(
        self,
        *,
        role: ClaudeRole,
        cache: ClaudeCache,
        hard_stop_usd: float,
        warning_thresholds: list[float],
        max_retries: int,
        retry_max_wait_seconds: float,
    ) -> None:
        self.role = role
        self.cache = cache
        self.hard_stop_usd = hard_stop_usd
        self.warning_thresholds = sorted(warning_thresholds)
        self.max_retries = max_retries
        self.retry_max_wait_seconds = retry_max_wait_seconds
        self.warned: set[float] = set()
        self._client: Any | None = None

    def _check_budget(self) -> None:
        spent = self.cache.spent_usd
        for threshold in self.warning_thresholds:
            if spent >= threshold and threshold not in self.warned:
                print(f"[Claude予算警告] 累計概算 ${spent:.2f}（${threshold:.2f}到達）")
                self.warned.add(threshold)
        if spent >= self.hard_stop_usd:
            raise RuntimeError(
                f"Claude累計概算${spent:.2f}がhard stop ${self.hard_stop_usd:.2f}へ到達しました。"
            )

    def client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self.role.api_key_env, "").strip()
        if not api_key:
            raise EnvironmentError(f"{self.role.api_key_env}が.envに設定されていません。")
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        return self._client

    def generate(
        self,
        *,
        kind: str,
        context_id: str,
        role: ClaudeRole,
        system_prompt: str,
        user_prompt: str,
        parser: Parser,
    ) -> tuple[str, Any, dict[str, Any]]:
        del parser
        identity = {
            "kind": kind,
            "context_id": context_id,
            "provider": "anthropic",
            "model": role.model_id,
            "temperature": role.temperature,
            "system_sha256": stable_hash(system_prompt),
            "user_sha256": stable_hash(user_prompt),
        }
        job_id = f"{kind}__{stable_hash(identity)[:24]}"
        cached = self.cache.get(job_id)
        if cached is not None:
            return str(cached["output_text"]), cached["parsed"], cached

        self._check_budget()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started_at = utc_now()
            usage = {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            cost = 0.0
            response_id: str | None = None
            output_text = ""
            try:
                response = self.client().messages.create(
                    model=role.model_id,
                    max_tokens=role.max_output_tokens,
                    temperature=role.temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                response_id = str(getattr(response, "id", "") or "") or None
                output_text = "".join(
                    str(getattr(block, "text", ""))
                    for block in getattr(response, "content", [])
                    if getattr(block, "type", "") == "text"
                ).strip()
                metadata = getattr(response, "usage", None)
                usage = {
                    "input_tokens": int(getattr(metadata, "input_tokens", 0) or 0),
                    "cache_creation_input_tokens": int(
                        getattr(metadata, "cache_creation_input_tokens", 0) or 0
                    ),
                    "cache_read_input_tokens": int(
                        getattr(metadata, "cache_read_input_tokens", 0) or 0
                    ),
                    "output_tokens": int(getattr(metadata, "output_tokens", 0) or 0),
                }
                usage["total_tokens"] = sum(usage.values())
                cost = role.cost(usage)
                if not output_text:
                    raise ValueError("Claude API応答が空です。")
                parsed = parse_ranking_safe(output_text)
                row = {
                    "job_id": job_id,
                    "status": "success",
                    "kind": kind,
                    "context_id": context_id,
                    "role": role.role_name,
                    "anonymous_label": role.anonymous_label,
                    "provider": "anthropic",
                    "model": role.model_id,
                    "attempt": attempt,
                    "output_text": output_text,
                    "parsed": parsed,
                    "usage": usage,
                    "cost_usd": cost,
                    "response_id": response_id,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "identity": identity,
                }
                self.cache.add(row)
                self._check_budget()
                return output_text, parsed, row
            except Exception as exc:
                last_error = exc
                row = {
                    "job_id": job_id,
                    "status": "failed",
                    "kind": kind,
                    "context_id": context_id,
                    "role": role.role_name,
                    "anonymous_label": role.anonymous_label,
                    "provider": "anthropic",
                    "model": role.model_id,
                    "attempt": attempt,
                    "output_text": output_text,
                    "error": str(exc),
                    "usage": usage,
                    "cost_usd": cost,
                    "response_id": response_id,
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "identity": identity,
                }
                self.cache.add(row)
                self._check_budget()
                if attempt < self.max_retries:
                    wait = min(
                        2 ** (attempt - 1) + random.random(),
                        self.retry_max_wait_seconds,
                    )
                    print(f"[retry] {context_id}: {exc} / {wait:.1f}秒待機")
                    time.sleep(wait)
        raise RuntimeError(f"Claude順位評価に失敗しました: {last_error}") from last_error


def prompt_name_map(path: Path) -> dict[str, str]:
    prompts = base.prompt_catalog(base.read_json(path))
    return {str(item["id"]): str(item.get("name_ja", item["id"])) for item in prompts}


def load_validated_inputs(
    *,
    instances_path: Path,
    source_results_path: Path,
    source_summary_path: Path,
    initial_prompts_path: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[str],
    list[dict[str, Any]],
    dict[str, str],
]:
    source_summary = base.read_json(source_summary_path)
    if str(source_summary.get("status")) != "complete":
        raise ValueError("OpenAI・Gemini Fullのstatusがcompleteではありません。")
    if int(source_summary.get("test_result_rows", 0)) != 2250:
        raise ValueError("OpenAI・Gemini FullのTest結果が2250行ではありません。")

    instances = base.validate_and_index_instances(
        base.read_json(instances_path),
        require_full=True,
    )
    test_ids = base.select_ids(instances, "test")
    if len(test_ids) != 30:
        raise ValueError(f"Test intentが30件ではありません: {len(test_ids)}")

    names = prompt_name_map(initial_prompts_path)
    expected_prompt_ids = set(names)
    source_rows = read_jsonl(source_results_path)
    selected = [
        row
        for row in source_rows
        if str(row.get("condition")) in {"test_initial_long", "test_optimized_long"}
        and str(row.get("query_form")) == "long"
    ]

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in selected:
        key = (
            str(row.get("condition")),
            str(row.get("prompt_id")),
            str(row.get("intent_id")),
        )
        grouped.setdefault(key, []).append(row)

    expected_keys = {
        (condition, prompt_id, intent_id)
        for condition in ("test_initial_long", "test_optimized_long")
        for prompt_id in expected_prompt_ids
        for intent_id in test_ids
    }
    if set(grouped) != expected_keys:
        missing = sorted(expected_keys - set(grouped))[:10]
        extra = sorted(set(grouped) - expected_keys)[:10]
        raise ValueError(
            f"Claude用の共有リライト900件を構成できません。missing={missing}, extra={extra}"
        )

    unique_rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        rows = grouped[key]
        descriptions = {
            base.clean_text(row.get("rewritten_description", "")) for row in rows
        }
        descriptions.discard("")
        if len(descriptions) != 1:
            raise ValueError(f"{key}: Model E/F間でリライト文章が一致しません。")
        condition, prompt_id, intent_id = key
        instance = instances[intent_id]
        source = rows[0]
        if str(source.get("target_product_id")) != str(instance["target_product_id"]):
            raise ValueError(f"{key}: 対象商品IDがinstancesと一致しません。")
        unique_rows.append(
            {
                "condition": condition,
                "prompt_id": prompt_id,
                "prompt_name_ja": names[prompt_id],
                "intent_id": intent_id,
                "target_product_id": instance["target_product_id"],
                "target_candidate_position": int(instance["target_candidate_position"]),
                "rewritten_description": next(iter(descriptions)),
            }
        )

    if len(unique_rows) != 900:
        raise ValueError(f"共有リライトが900件ではありません: {len(unique_rows)}")
    return instances, test_ids, unique_rows, names


def make_plan(
    *,
    mode: str,
    role: ClaudeRole,
    test_ids: list[str],
    source_rows: list[dict[str, Any]],
    hard_stop_usd: float,
    key_present: bool,
) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "mode": mode,
        "status": "validated",
        "api_calls": 0 if mode == "validate" else None,
        "model": role.model_id,
        "anonymous_label": role.anonymous_label,
        "test_intents": len(test_ids),
        "original_rank_calls_full": len(test_ids),
        "rewritten_rank_calls_full": len(source_rows),
        "full_calls_total": len(test_ids) + len(source_rows),
        "conditions": ["test_initial_long", "test_optimized_long"],
        "rewrites_reused_from_openai_gemini_full": True,
        "train_validation_meta_optimization_rerun": False,
        "separate_cache": True,
        "hard_stop_usd": hard_stop_usd,
        "api_key_env": role.api_key_env,
        "api_key_present": key_present,
    }


def select_smoke_pair(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault((row["prompt_id"], row["intent_id"]), []).append(row)
    candidates: list[tuple[int, str, str, list[dict[str, Any]]]] = []
    for (prompt_id, intent_id), pair_rows in by_pair.items():
        if {row["condition"] for row in pair_rows} != {
            "test_initial_long",
            "test_optimized_long",
        }:
            continue
        total_chars = sum(len(row["rewritten_description"]) for row in pair_rows)
        candidates.append((total_chars, prompt_id, intent_id, pair_rows))
    if not candidates:
        raise ValueError("Smoke用の初期・最適化ペアがありません。")
    candidates.sort(key=lambda item: item[0])
    return sorted(candidates[len(candidates) // 2][3], key=lambda row: row["condition"])


def rank_original(
    *,
    api: ClaudeRunner,
    role: ClaudeRole,
    ranking_template: str,
    instance: dict[str, Any],
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    return base.original_rank(
        api,
        role,
        ranking_template,
        instance,
        "long",
    )


def rank_rewrite(
    *,
    api: ClaudeRunner,
    role: ClaudeRole,
    ranking_template: str,
    instance: dict[str, Any],
    source: dict[str, Any],
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    return base.rank_instance(
        api=api,
        role=role,
        ranking_template=ranking_template,
        instance=instance,
        query_form="long",
        rewritten_description=str(source["rewritten_description"]),
        context_id=(
            f"claude_heldout__{source['condition']}__{source['prompt_id']}__"
            f"{source['intent_id']}__long__{role.anonymous_label}"
        ),
    )


def evaluate_sources(
    *,
    api: ClaudeRunner,
    role: ClaudeRole,
    ranking_template: str,
    instances: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    output_label: str,
) -> list[dict[str, Any]]:
    needed_intents = sorted({str(row["intent_id"]) for row in sources})
    original: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
    for index, intent_id in enumerate(needed_intents, start=1):
        original[intent_id] = rank_original(
            api=api,
            role=role,
            ranking_template=ranking_template,
            instance=instances[intent_id],
        )
        print(
            f"  {output_label} original: {index}/{len(needed_intents)} {intent_id} "
            f"(Claude cost=${api.cache.spent_usd:.4f})"
        )

    result_rows: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        intent_id = str(source["intent_id"])
        instance = instances[intent_id]
        original_rank, original_parsed, original_record = original[intent_id]
        rewritten_rank, rewritten_parsed, rewritten_record = rank_rewrite(
            api=api,
            role=role,
            ranking_template=ranking_template,
            instance=instance,
            source=source,
        )
        result_rows.append(
            {
                "condition": source["condition"],
                "split": "test",
                "query_form": "long",
                "prompt_id": source["prompt_id"],
                "prompt_name_ja": source["prompt_name_ja"],
                "intent_id": intent_id,
                "target_product_id": source["target_product_id"],
                "target_candidate_position": int(source["target_candidate_position"]),
                "reranker_label": role.anonymous_label,
                "reranker_model": role.model_id,
                "original_rank": original_rank,
                "rewritten_rank": rewritten_rank,
                "rank_improvement": original_rank - rewritten_rank,
                "original_questionable_products": original_parsed["questionable_products"],
                "rewritten_questionable_products": rewritten_parsed["questionable_products"],
                "rewritten_target_flagged_questionable": int(
                    int(source["target_candidate_position"])
                    in rewritten_parsed["questionable_products"]
                ),
                "rewritten_description": source["rewritten_description"],
                "original_rank_job_id": original_record["job_id"],
                "rewritten_rank_job_id": rewritten_record["job_id"],
            }
        )
        print(
            f"  {output_label} rewritten: {index}/{len(sources)} "
            f"{source['condition']}/{source['prompt_id']}/{intent_id} "
            f"(Claude cost=${api.cache.spent_usd:.4f})"
        )
    return result_rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def write_cost_ledger(cache: ClaudeCache, path: Path) -> None:
    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for event in cache.events:
        usage = event.get("usage", {})
        cost = float(event.get("cost_usd", 0) or 0)
        cumulative += cost
        rows.append(
            {
                "finished_at": event.get("finished_at", ""),
                "status": event.get("status", ""),
                "context_id": event.get("context_id", ""),
                "model": event.get("model", ""),
                "attempt": event.get("attempt", ""),
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cost_usd": cost,
                "cumulative_cost_usd": cumulative,
                "job_id": event.get("job_id", ""),
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def smoke_projection(
    *,
    smoke_rows: list[dict[str, Any]],
    cache: ClaudeCache,
    role: ClaudeRole,
    config: dict[str, Any],
) -> dict[str, Any]:
    successful = [
        row
        for row in cache.events
        if row.get("status") == "success"
        and row.get("model") == role.model_id
        and (
            str(row.get("context_id", "")).startswith("original__")
            or str(row.get("context_id", "")).startswith("claude_heldout__")
        )
    ]
    smoke_job_ids = {
        row["original_rank_job_id"] for row in smoke_rows
    } | {
        row["rewritten_rank_job_id"] for row in smoke_rows
    }
    measured = [row for row in successful if row.get("job_id") in smoke_job_ids]
    original_costs = [
        float(row["cost_usd"])
        for row in measured
        if str(row.get("context_id", "")).startswith("original__")
    ]
    rewritten_costs = [
        float(row["cost_usd"])
        for row in measured
        if str(row.get("context_id", "")).startswith("claude_heldout__")
    ]
    if len(original_costs) != 1 or len(rewritten_costs) != 2:
        raise ValueError(
            f"Smoke実測がoriginal 1件・rewrite 2件ではありません: "
            f"{len(original_costs)}, {len(rewritten_costs)}"
        )
    raw_projection = 30 * original_costs[0] + 900 * (
        sum(rewritten_costs) / len(rewritten_costs)
    )
    safety_factor = float(config["budget"]["smoke_projection_safety_factor"])
    safe_projection = raw_projection * safety_factor
    full_gate = float(config["budget"]["full_projection_gate_usd"])
    return {
        "created_at": utc_now(),
        "status": "pass" if safe_projection <= full_gate else "stop",
        "model": role.model_id,
        "smoke_calls": 3,
        "smoke_cost_usd": sum(original_costs) + sum(rewritten_costs),
        "original_call_cost_usd": original_costs[0],
        "mean_rewritten_call_cost_usd": sum(rewritten_costs) / len(rewritten_costs),
        "full_raw_projection_usd": raw_projection,
        "safety_factor": safety_factor,
        "full_projection_with_margin_usd": safe_projection,
        "full_projection_gate_usd": full_gate,
        "hard_stop_usd": float(config["budget"]["hard_stop_usd"]),
        "full_call_count": 930,
        "note": "Smokeの代表1意図・初期/最適化2条件から推定。Full前ゲートは余裕を含む。",
    }


def analyze_full(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    if len(frame) != 900:
        raise ValueError(f"Claude Full結果が900行ではありません: {len(frame)}")
    expected_conditions = {"test_initial_long", "test_optimized_long"}
    if set(frame["condition"]) != expected_conditions:
        raise ValueError(f"条件が不正です: {set(frame['condition'])}")

    summary = (
        frame.groupby(
            ["condition", "prompt_id", "prompt_name_ja", "reranker_label", "reranker_model"],
            as_index=False,
        )
        .agg(
            n=("rank_improvement", "size"),
            mean_rank_improvement=("rank_improvement", "mean"),
            median_rank_improvement=("rank_improvement", "median"),
            std_rank_improvement=("rank_improvement", "std"),
            sem_rank_improvement=("rank_improvement", "sem"),
            positive_rate=("rank_improvement", lambda s: float((s > 0).mean())),
            unchanged_rate=("rank_improvement", lambda s: float((s == 0).mean())),
            negative_rate=("rank_improvement", lambda s: float((s < 0).mean())),
            questionable_target_rate=(
                "rewritten_target_flagged_questionable",
                "mean",
            ),
        )
    )
    summary.to_csv(
        output_dir / "05_claude_test_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pivot = frame.pivot_table(
        index=["prompt_id", "prompt_name_ja", "intent_id"],
        columns="condition",
        values="rank_improvement",
        aggfunc="first",
    ).reset_index()
    if pivot[["test_initial_long", "test_optimized_long"]].isna().any().any():
        raise ValueError("初期・最適化の対応ペアに欠損があります。")
    pivot["difference_optimized_minus_initial"] = (
        pivot["test_optimized_long"] - pivot["test_initial_long"]
    )
    paired = (
        pivot.groupby(["prompt_id", "prompt_name_ja"], as_index=False)
        .agg(
            n=("intent_id", "size"),
            initial_mean=("test_initial_long", "mean"),
            optimized_mean=("test_optimized_long", "mean"),
            mean_difference=("difference_optimized_minus_initial", "mean"),
            median_difference=("difference_optimized_minus_initial", "median"),
            improved_pair_rate=(
                "difference_optimized_minus_initial",
                lambda s: float((s > 0).mean()),
            ),
        )
    )
    paired.to_csv(
        output_dir / "06_claude_initial_vs_optimized.csv",
        index=False,
        encoding="utf-8-sig",
    )

    initial_overall = float(
        frame.loc[frame["condition"] == "test_initial_long", "rank_improvement"].mean()
    )
    optimized_overall = float(
        frame.loc[frame["condition"] == "test_optimized_long", "rank_improvement"].mean()
    )
    result = {
        "analysis_completed_at": utc_now(),
        "status": "complete",
        "result_rows": len(frame),
        "paired_rows": len(pivot),
        "prompt_count": int(frame["prompt_id"].nunique()),
        "intent_count": int(frame["intent_id"].nunique()),
        "initial_overall_mean": initial_overall,
        "optimized_overall_mean": optimized_overall,
        "optimized_minus_initial_overall": optimized_overall - initial_overall,
        "prompts_improved_by_mean": int((paired["mean_difference"] > 0).sum()),
        "prompts_unchanged_by_mean": int((paired["mean_difference"] == 0).sum()),
        "prompts_regressed_by_mean": int((paired["mean_difference"] < 0).sum()),
    }
    write_json(output_dir / "07_claude_results_summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "成功済みOpenAI・Gemini Fullのリライトを再利用し、"
            "Claude Sonnet 4.5のHeld-out順位評価だけを別キャッシュで実行する。"
        )
    )
    parser.add_argument(
        "--mode",
        choices=["validate", "smoke", "full", "analyze"],
        default="validate",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument(
        "--source-results",
        type=Path,
        default=DEFAULT_SOURCE_RESULTS,
    )
    parser.add_argument(
        "--source-summary",
        type=Path,
        default=DEFAULT_SOURCE_SUMMARY,
    )
    parser.add_argument(
        "--initial-prompts",
        type=Path,
        default=DEFAULT_INITIAL_PROMPTS,
    )
    parser.add_argument(
        "--common-prompts",
        type=Path,
        default=DEFAULT_COMMON_PROMPTS,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hard-stop-usd", type=float)
    args = parser.parse_args()

    load_dotenv()
    config = base.read_json(args.config)
    role = ClaudeRole.from_config(config)
    budget = config["budget"]
    hard_stop = (
        float(args.hard_stop_usd)
        if args.hard_stop_usd is not None
        else float(budget["hard_stop_usd"])
    )
    key_present = bool(os.environ.get(role.api_key_env, "").strip())

    instances, test_ids, source_rows, _ = load_validated_inputs(
        instances_path=args.instances,
        source_results_path=args.source_results,
        source_summary_path=args.source_summary,
        initial_prompts_path=args.initial_prompts,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = make_plan(
        mode=args.mode,
        role=role,
        test_ids=test_ids,
        source_rows=source_rows,
        hard_stop_usd=hard_stop,
        key_present=key_present,
    )
    write_json(args.output_dir / "00_execution_plan.json", plan)

    print("Claude Held-out評価専用ランナー")
    print(f"  Mode: {args.mode}")
    print(f"  Model: {role.model_id}")
    print(f"  Test intents: {len(test_ids)}")
    print(f"  Shared rewrites: {len(source_rows)}")
    print(f"  Full calls: {len(test_ids) + len(source_rows)}")
    print(f"  Hard stop: ${hard_stop:.2f}")
    print(f"  {role.api_key_env}: {'設定済み' if key_present else '未設定'}")
    print("  OpenAI/Gemini API再実行: なし")
    print("  Train/Validation/Meta最適化再実行: なし")

    if args.mode == "validate":
        print("Validate完了：APIは呼び出していません。")
        return
    if not key_present:
        raise EnvironmentError(f"{role.api_key_env}が.envに設定されていません。")

    common = base.read_json(args.common_prompts)
    ranking_template = str(
        common["ranking_user_prompt"]["faithful_translation_ja"]
    )
    execution = config["execution"]
    cache = ClaudeCache(args.output_dir / "01_claude_cache.jsonl")
    api = ClaudeRunner(
        role=role,
        cache=cache,
        hard_stop_usd=hard_stop,
        warning_thresholds=[
            float(value) for value in budget["warning_thresholds_usd"]
        ],
        max_retries=int(execution["max_retries"]),
        retry_max_wait_seconds=float(execution["retry_max_wait_seconds"]),
    )

    if args.mode == "analyze":
        full_path = args.output_dir / "02_claude_test_results.jsonl"
        result = analyze_full(read_jsonl(full_path), args.output_dir)
        write_cost_ledger(cache, args.output_dir / "03_claude_cost_ledger.csv")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mode == "smoke":
        smoke_sources = select_smoke_pair(source_rows)
        smoke_rows = evaluate_sources(
            api=api,
            role=role,
            ranking_template=ranking_template,
            instances=instances,
            sources=smoke_sources,
            output_label="Smoke",
        )
        write_jsonl(args.output_dir / "02_smoke_results.jsonl", smoke_rows)
        projection = smoke_projection(
            smoke_rows=smoke_rows,
            cache=cache,
            role=role,
            config=config,
        )
        write_json(args.output_dir / "04_smoke_projection.json", projection)
        write_cost_ledger(cache, args.output_dir / "03_claude_cost_ledger.csv")
        print(json.dumps(projection, ensure_ascii=False, indent=2))
        if projection["status"] != "pass":
            raise RuntimeError(
                "Smoke費用予測がFullゲートを超えました。Fullは開始しないでください。"
            )
        print("Claude Smoke完了：Full費用予測はゲート内です。")
        return

    projection_path = args.output_dir / "04_smoke_projection.json"
    if not projection_path.exists():
        raise FileNotFoundError("先にSmokeを実行し、費用予測を作成してください。")
    projection = base.read_json(projection_path)
    if str(projection.get("status")) != "pass":
        raise RuntimeError("Smoke費用予測がpassではありません。Fullを開始できません。")
    if str(projection.get("model")) != role.model_id:
        raise RuntimeError("SmokeとFullのClaudeモデルが一致しません。")
    if float(projection.get("full_projection_with_margin_usd", math.inf)) > float(
        budget["full_projection_gate_usd"]
    ):
        raise RuntimeError("安全余裕込みの費用予測がFullゲートを超えています。")

    full_rows = evaluate_sources(
        api=api,
        role=role,
        ranking_template=ranking_template,
        instances=instances,
        sources=source_rows,
        output_label="Full",
    )
    write_jsonl(args.output_dir / "02_claude_test_results.jsonl", full_rows)
    write_cost_ledger(cache, args.output_dir / "03_claude_cost_ledger.csv")
    analysis = analyze_full(full_rows, args.output_dir)
    summary = {
        "completed_at": utc_now(),
        "status": "complete",
        "model": role.model_id,
        "anonymous_label": role.anonymous_label,
        "conditions": ["test_initial_long", "test_optimized_long"],
        "test_result_rows": len(full_rows),
        "api_calls_expected": 930,
        "claude_cost_usd_estimate": round(cache.spent_usd, 6),
        "hard_stop_usd": hard_stop,
        "openai_gemini_api_rerun": False,
        "rewrites_reused": True,
        "analysis": analysis,
    }
    write_json(args.output_dir / "08_run_summary.json", summary)
    print("\nClaude Held-out Full完了")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
