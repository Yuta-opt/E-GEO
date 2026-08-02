from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from dotenv import load_dotenv


DEFAULT_INSTANCES = Path(
    "日本語版データ/TOEIC/04_候補商品/08_toeic_experiment_instances.json"
)
DEFAULT_INITIAL_PROMPTS = Path(
    "日本語版設定/E_GEO先行研究_初期プロンプト15種.json"
)
DEFAULT_COMMON_PROMPTS = Path(
    "日本語版設定/E_GEO先行研究_共通プロンプト設定.json"
)
DEFAULT_META_PROMPT = Path(
    "日本語版設定/E_GEO先行研究_メタ最適化設定.json"
)
DEFAULT_EXPERIMENT_CONFIG = Path(
    "日本語版設定/TOEIC_EGEO実験設定_v2.json"
)
DEFAULT_MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI単一キー実験設定_v1.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行"
)

RERANKER_SYSTEM_PROMPT_JA = (
    "あなたは商品検索の厳格な再ランキング評価器です。"
    "利用者のクエリと商品情報だけに基づき、全商品を関連性順に並べてください。"
    "出力は指定されたJSONだけにしてください。"
)


Parser = Callable[[str], Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(value: Any) -> str:
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    value = strip_code_fence(text)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("JSON objectを抽出できません。")
        parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("出力がJSON objectではありません。")
    return parsed


def parse_ranking(text: str) -> dict[str, Any]:
    value = extract_json_object(text)
    ranking = [int(item) for item in value.get("ranking", [])]
    questionable = [int(item) for item in value.get("questionable_products", [])]
    if len(ranking) != 10 or sorted(ranking) != list(range(1, 11)):
        raise ValueError(f"rankingは1〜10を一度ずつ含む必要があります: {ranking}")
    if len(set(questionable)) != len(questionable):
        raise ValueError("questionable_productsが重複しています。")
    if any(item < 1 or item > 10 for item in questionable):
        raise ValueError("questionable_productsに1〜10以外が含まれています。")
    return {"ranking": ranking, "questionable_products": questionable}


def parse_rewrite(text: str) -> str:
    value = strip_code_fence(text)
    if not value:
        raise ValueError("リライト結果が空です。")
    return value


def parse_meta_output(text: str) -> dict[str, str]:
    value = strip_code_fence(text)
    marker = "--NEW_REWRITING_PROMPT--"
    if marker not in value:
        raise ValueError("Meta-optimizer出力にNEW_REWRITING_PROMPT節がありません。")
    new_prompt = value.split(marker, 1)[1].strip()
    if "{description}" not in new_prompt:
        raise ValueError("新プロンプトに{description}プレースホルダーがありません。")
    sections: dict[str, str] = {"raw": value, "new_prompt": new_prompt}
    for name in ["ANALYSIS", "META-REASONING", "IMPROVEMENTS"]:
        start_marker = f"--{name}--"
        if start_marker not in value:
            sections[name.lower()] = ""
            continue
        tail = value.split(start_marker, 1)[1]
        next_match = re.search(r"\n--[A-Z-]+--", tail)
        sections[name.lower()] = (
            tail[: next_match.start()] if next_match else tail
        ).strip()
    return sections


def usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def response_text(response: Any) -> str:
    value = getattr(response, "output_text", None)
    if value:
        return str(value)
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return "".join(
        str(content.get("text", ""))
        for item in raw.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )


@dataclass(frozen=True)
class ModelRole:
    role_name: str
    anonymous_label: str
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
    ) -> "ModelRole":
        if value.get("provider") != "openai":
            raise ValueError(f"単一キーランナーはOpenAI providerだけを扱います: {role_name}")
        return cls(
            role_name=role_name,
            anonymous_label=anonymous_label,
            model_id=str(value["model_id"]),
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
            usage["input_tokens"] / 1_000_000 * self.input_usd_per_million
            + usage["output_tokens"] / 1_000_000 * self.output_usd_per_million
        )


class LLMCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.success: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        if path.exists():
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"キャッシュJSONLを読めません: {path}:{line_number}") from exc
                self.events.append(row)
                if row.get("status") == "success":
                    self.success[str(row["job_id"])] = row

    @property
    def spent_usd(self) -> float:
        return float(sum(float(row.get("cost_usd", 0) or 0) for row in self.events))

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.success.get(job_id)

    def add(self, row: dict[str, Any]) -> None:
        append_jsonl(self.path, row)
        self.events.append(row)
        if row.get("status") == "success":
            self.success[str(row["job_id"])] = row


class OpenAIRunner:
    def __init__(
        self,
        cache: LLMCache,
        hard_stop_usd: float,
        warning_thresholds: list[float],
        max_retries: int,
        retry_max_wait_seconds: float,
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI()
        self.cache = cache
        self.hard_stop_usd = hard_stop_usd
        self.warning_thresholds = sorted(warning_thresholds)
        self.warned: set[float] = set()
        self.max_retries = max_retries
        self.retry_max_wait_seconds = retry_max_wait_seconds

    def _check_budget(self) -> None:
        spent = self.cache.spent_usd
        for threshold in self.warning_thresholds:
            if spent >= threshold and threshold not in self.warned:
                print(f"[予算警告] 累計概算 ${spent:.2f}（${threshold:.0f}到達）")
                self.warned.add(threshold)
        if spent >= self.hard_stop_usd:
            raise RuntimeError(
                f"累計概算${spent:.2f}がhard stop ${self.hard_stop_usd:.2f}へ到達しました。"
            )

    def generate(
        self,
        *,
        kind: str,
        context_id: str,
        role: ModelRole,
        system_prompt: str,
        user_prompt: str,
        parser: Parser,
    ) -> tuple[str, Any, dict[str, Any]]:
        identity = {
            "kind": kind,
            "context_id": context_id,
            "model": role.model_id,
            "temperature": role.temperature if role.supports_temperature else None,
            "system_sha256": stable_hash(system_prompt),
            "user_sha256": stable_hash(user_prompt),
        }
        job_id = f"{kind}__{stable_hash(identity)[:24]}"
        cached = self.cache.get(job_id)
        if cached is not None:
            return str(cached["output_text"]), cached.get("parsed"), cached

        self._check_budget()
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started = utc_now()
            response = None
            usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            cost = 0.0
            try:
                kwargs: dict[str, Any] = {
                    "model": role.model_id,
                    "instructions": system_prompt,
                    "input": user_prompt,
                    "store": False,
                    "max_output_tokens": role.max_output_tokens,
                }
                if role.supports_temperature and role.temperature is not None:
                    kwargs["temperature"] = role.temperature
                response = self.client.responses.create(**kwargs)
                text = response_text(response).strip()
                usage = usage_dict(response)
                cost = role.cost(usage)
                parsed = parser(text)
                row = {
                    "job_id": job_id,
                    "status": "success",
                    "kind": kind,
                    "context_id": context_id,
                    "role": role.role_name,
                    "anonymous_label": role.anonymous_label,
                    "model": role.model_id,
                    "attempt": attempt,
                    "output_text": text,
                    "parsed": parsed,
                    "usage": usage,
                    "cost_usd": cost,
                    "response_id": getattr(response, "id", None),
                    "started_at": started,
                    "finished_at": utc_now(),
                    "identity": identity,
                }
                self.cache.add(row)
                self._check_budget()
                return text, parsed, row
            except Exception as exc:
                last_error = exc
                if response is not None:
                    usage = usage_dict(response)
                    cost = role.cost(usage)
                row = {
                    "job_id": job_id,
                    "status": "failed",
                    "kind": kind,
                    "context_id": context_id,
                    "role": role.role_name,
                    "anonymous_label": role.anonymous_label,
                    "model": role.model_id,
                    "attempt": attempt,
                    "error": str(exc),
                    "usage": usage,
                    "cost_usd": cost,
                    "started_at": started,
                    "finished_at": utc_now(),
                    "identity": identity,
                }
                self.cache.add(row)
                self._check_budget()
                if attempt < self.max_retries:
                    wait = min(2 ** (attempt - 1) + random.random(), self.retry_max_wait_seconds)
                    time.sleep(wait)
        raise RuntimeError(f"API処理に失敗しました: {last_error}") from last_error


def load_model_roles(profile: dict[str, Any]) -> tuple[
    ModelRole,
    ModelRole,
    list[ModelRole],
    list[ModelRole],
]:
    roles = profile["roles"]
    rewriter = ModelRole.from_dict("rewriter", roles["rewriter"])
    meta = ModelRole.from_dict("meta_optimizer", roles["meta_optimizer"])
    training = [
        ModelRole.from_dict(
            "training_reranker",
            item,
            anonymous_label=str(item["anonymous_label"]),
        )
        for item in roles["training_rerankers"]
    ]
    heldout = [
        ModelRole.from_dict(
            "heldout_reranker",
            item,
            anonymous_label=str(item["anonymous_label"]),
        )
        for item in roles["heldout_rerankers"]
    ]
    return rewriter, meta, training, heldout


def validate_and_index_instances(
    value: Any,
    require_full: bool,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("実験instance JSONは空でない配列である必要があります。")
    output: dict[str, dict[str, Any]] = {}
    for instance in value:
        intent_id = str(instance.get("intent_id", ""))
        if not intent_id or intent_id in output:
            raise ValueError(f"intent_idが空または重複しています: {intent_id}")
        products = instance.get("products")
        if not isinstance(products, list) or len(products) != 10:
            raise ValueError(f"{intent_id}: productsが10件ではありません。")
        positions = sorted(int(product["candidate_position"]) for product in products)
        if positions != list(range(1, 11)):
            raise ValueError(f"{intent_id}: candidate_positionが1〜10ではありません。")
        targets = [product for product in products if bool(product.get("is_target"))]
        if len(targets) != 1:
            raise ValueError(f"{intent_id}: 対象商品が1件ではありません。")
        queries = instance.get("queries", {})
        if not clean_text(queries.get("long")) or not clean_text(queries.get("short")):
            raise ValueError(f"{intent_id}: shortまたはlongクエリが空です。")
        output[intent_id] = instance

    split_counts = pd.Series(
        [str(item.get("split", "")) for item in output.values()]
    ).value_counts().to_dict()
    if require_full:
        expected = {"train": 40, "validation": 10, "test": 30}
        if len(output) != 80 or split_counts != expected:
            raise ValueError(
                f"正式実験instanceが80件・40/10/30ではありません: {len(output)}, {split_counts}"
            )
    return output


def prompt_catalog(value: Any) -> list[dict[str, Any]]:
    prompts = value.get("prompts") if isinstance(value, dict) else None
    if not isinstance(prompts, list) or len(prompts) != 15:
        raise ValueError("初期プロンプトは15件必要です。")
    for prompt in prompts:
        if "{description}" not in str(prompt.get("faithful_translation_ja", "")):
            raise ValueError(f"{prompt.get('id')}: 日本語プロンプトにdescriptionがありません。")
    return prompts


def target_product(instance: dict[str, Any]) -> dict[str, Any]:
    return next(product for product in instance["products"] if bool(product["is_target"]))


def format_products(
    instance: dict[str, Any],
    rewritten_description: str | None,
) -> str:
    lines: list[str] = []
    target_position = int(instance["target_candidate_position"])
    for product in sorted(instance["products"], key=lambda item: int(item["candidate_position"])):
        position = int(product["candidate_position"])
        description = clean_text(product.get("description", ""))
        if position == target_position and rewritten_description is not None:
            description = clean_text(rewritten_description)
        lines.append(
            f"{position}. 商品名: {clean_text(product.get('title', ''))}\n"
            f"説明: {description}"
        )
    return "\n\n".join(lines)


def replace_description(prompt: str, description: str) -> str:
    if "{description}" not in prompt:
        raise ValueError("リライトプロンプトに{description}がありません。")
    return prompt.replace("{description}", description)


def deterministic_batches(
    train_ids: list[str],
    epochs: int,
    batches_per_epoch: int,
    batch_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    source = np.asarray(sorted(train_ids), dtype=object)
    rows: list[dict[str, Any]] = []
    for epoch in range(1, epochs + 1):
        rng = np.random.default_rng(seed + epoch - 1)
        shuffled = source[rng.permutation(len(source))]
        for batch in range(1, batches_per_epoch + 1):
            start = (batch - 1) * batch_size
            ids = [str(item) for item in shuffled[start : start + batch_size]]
            if len(ids) != batch_size:
                raise ValueError("Train batchの件数が不足しています。")
            rows.append(
                {
                    "epoch": epoch,
                    "batch": batch,
                    "intent_ids": ids,
                    "meta_update_after": batch < batches_per_epoch,
                }
            )
    return rows


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    engine_means = {
        str(label): float(group["rank_improvement"].mean())
        for label, group in frame.groupby("reranker_label")
    }
    values = list(engine_means.values())
    return {
        "n": int(len(frame)),
        "overall_mean": float(frame["rank_improvement"].mean()),
        "overall_median": float(frame["rank_improvement"].median()),
        "positive_rate": float((frame["rank_improvement"] > 0).mean()),
        "engine_means": engine_means,
        "worst_engine_mean": float(min(values)),
        "best_engine_mean": float(max(values)),
        "cross_engine_std": float(np.std(values, ddof=0)),
        "engines_positive": int(sum(value > 0 for value in values)),
        "engines_total": int(len(values)),
    }


def per_engine_stats_text(summary: dict[str, Any]) -> str:
    lines = []
    for label, mean in summary["engine_means"].items():
        lines.append(f"• {label}: mean rank improvement = {mean:.4f}")
    return "\n".join(lines)


def history_text(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    lines = ["\nPREVIOUS OPTIMIZATION HISTORY:"]
    for item in history:
        lines.append(
            f"• version {item['version_number']} ({item['version_label']}): "
            f"train mean={item['train_summary']['overall_mean']:.4f}, "
            f"validation mean={item['validation_summary']['overall_mean']:.4f}"
        )
    return "\n".join(lines)


def rewrite_description(
    api: OpenAIRunner,
    role: ModelRole,
    system_prompt: str,
    instance: dict[str, Any],
    rewriting_prompt: str,
    context_id: str,
) -> tuple[str, dict[str, Any]]:
    description = clean_text(target_product(instance).get("description", ""))
    user_prompt = replace_description(rewriting_prompt, description)
    _, parsed, record = api.generate(
        kind="rewrite",
        context_id=context_id,
        role=role,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        parser=parse_rewrite,
    )
    return str(parsed), record


def rank_instance(
    api: OpenAIRunner,
    role: ModelRole,
    ranking_template: str,
    instance: dict[str, Any],
    query_form: str,
    rewritten_description: str | None,
    context_id: str,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    query = clean_text(instance["queries"][query_form])
    user_prompt = ranking_template.format(
        query=query,
        formatted_products=format_products(instance, rewritten_description),
    )
    _, parsed, record = api.generate(
        kind="rerank",
        context_id=context_id,
        role=role,
        system_prompt=RERANKER_SYSTEM_PROMPT_JA,
        user_prompt=user_prompt,
        parser=parse_ranking,
    )
    target_position = int(instance["target_candidate_position"])
    rank = list(parsed["ranking"]).index(target_position) + 1
    return rank, parsed, record


def original_rank(
    api: OpenAIRunner,
    role: ModelRole,
    ranking_template: str,
    instance: dict[str, Any],
    query_form: str,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    return rank_instance(
        api=api,
        role=role,
        ranking_template=ranking_template,
        instance=instance,
        query_form=query_form,
        rewritten_description=None,
        context_id=(
            f"original__{instance['intent_id']}__{query_form}__{role.anonymous_label}"
        ),
    )


def evaluate_prompt(
    *,
    api: OpenAIRunner,
    rewriter: ModelRole,
    rerankers: list[ModelRole],
    rewriter_system_prompt: str,
    ranking_template: str,
    instances: dict[str, dict[str, Any]],
    intent_ids: list[str],
    rewriting_prompt: str,
    prompt_id: str,
    version_label: str,
    split: str,
    query_form: str,
    condition: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset, intent_id in enumerate(intent_ids, start=1):
        instance = instances[intent_id]
        rewrite_context = (
            f"{condition}__{prompt_id}__{version_label}__{intent_id}"
        )
        rewritten, rewrite_record = rewrite_description(
            api,
            rewriter,
            rewriter_system_prompt,
            instance,
            rewriting_prompt,
            rewrite_context,
        )
        for reranker in rerankers:
            base_rank, base_parsed, base_record = original_rank(
                api, reranker, ranking_template, instance, query_form
            )
            rewritten_rank, rerank_parsed, rerank_record = rank_instance(
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
            rows.append(
                {
                    "condition": condition,
                    "split": split,
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
                    "rewritten_questionable_products": rerank_parsed["questionable_products"],
                    "rewritten_target_flagged_questionable": int(
                        instance["target_candidate_position"]
                        in rerank_parsed["questionable_products"]
                    ),
                    "rewritten_description": rewritten,
                    "rewrite_job_id": rewrite_record["job_id"],
                    "original_rank_job_id": base_record["job_id"],
                    "rewritten_rank_job_id": rerank_record["job_id"],
                }
            )
        print(
            f"    {condition}: {offset}/{len(intent_ids)} {intent_id} "
            f"(cost=${api.cache.spent_usd:.2f})"
        )
    return rows


def update_prompt(
    *,
    api: OpenAIRunner,
    role: ModelRole,
    meta_system_prompt: str,
    meta_user_template: str,
    current_prompt: str,
    train_summary: dict[str, Any],
    history: list[dict[str, Any]],
    context_id: str,
) -> tuple[str, dict[str, Any]]:
    user_prompt = meta_user_template.format(
        current_prompt=current_prompt,
        batch_size=int(train_summary["n"] / train_summary["engines_total"]),
        per_engine_stats_text=per_engine_stats_text(train_summary),
        worst_engine_mean=f"{train_summary['worst_engine_mean']:.4f}",
        best_engine_mean=f"{train_summary['best_engine_mean']:.4f}",
        cross_engine_std=f"{train_summary['cross_engine_std']:.4f}",
        engines_positive=train_summary["engines_positive"],
        engines_total=train_summary["engines_total"],
        history_section=history_text(history),
    )
    _, parsed, record = api.generate(
        kind="meta_optimizer",
        context_id=context_id,
        role=role,
        system_prompt=meta_system_prompt,
        user_prompt=user_prompt,
        parser=parse_meta_output,
    )
    return str(parsed["new_prompt"]), {
        "job_id": record["job_id"],
        "raw": parsed["raw"],
        "analysis": parsed.get("analysis", ""),
        "meta_reasoning": parsed.get("meta-reasoning", ""),
        "improvements": parsed.get("improvements", ""),
    }


def select_ids(
    instances: dict[str, dict[str, Any]],
    split: str,
) -> list[str]:
    return sorted(
        intent_id
        for intent_id, instance in instances.items()
        if str(instance["split"]) == split
    )


def run_trajectory(
    *,
    api: OpenAIRunner,
    prompt: dict[str, Any],
    instances: dict[str, dict[str, Any]],
    train_ids: list[str],
    validation_ids: list[str],
    schedule: list[dict[str, Any]],
    rewriter: ModelRole,
    meta: ModelRole,
    training_rerankers: list[ModelRole],
    rewriter_system_prompt: str,
    ranking_template: str,
    meta_system_prompt: str,
    meta_user_template: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prompt_id = str(prompt["id"])
    current_prompt = str(prompt["faithful_translation_ja"])
    history: list[dict[str, Any]] = []
    version_rows: list[dict[str, Any]] = []

    print(f"\n[trajectory] {prompt_id}")
    for version_number, step in enumerate(schedule, start=1):
        version_label = f"{prompt_id}__e{step['epoch']}_b{step['batch']}"
        print(
            f"  version {version_number}/{len(schedule)} "
            f"epoch={step['epoch']} batch={step['batch']}"
        )
        train_rows = evaluate_prompt(
            api=api,
            rewriter=rewriter,
            rerankers=training_rerankers,
            rewriter_system_prompt=rewriter_system_prompt,
            ranking_template=ranking_template,
            instances=instances,
            intent_ids=step["intent_ids"],
            rewriting_prompt=current_prompt,
            prompt_id=prompt_id,
            version_label=version_label,
            split="train",
            query_form="long",
            condition="optimization_train",
        )
        validation_rows = evaluate_prompt(
            api=api,
            rewriter=rewriter,
            rerankers=training_rerankers,
            rewriter_system_prompt=rewriter_system_prompt,
            ranking_template=ranking_template,
            instances=instances,
            intent_ids=validation_ids,
            rewriting_prompt=current_prompt,
            prompt_id=prompt_id,
            version_label=version_label,
            split="validation",
            query_form="long",
            condition="optimization_validation",
        )
        train_summary = summarize_rows(train_rows)
        validation_summary = summarize_rows(validation_rows)
        version_record: dict[str, Any] = {
            "prompt_id": prompt_id,
            "prompt_name_ja": prompt.get("name_ja", ""),
            "version_number": version_number,
            "version_label": version_label,
            "epoch": step["epoch"],
            "batch": step["batch"],
            "prompt_text": current_prompt,
            "train_intent_ids": step["intent_ids"],
            "train_summary": train_summary,
            "validation_summary": validation_summary,
            "train_results": train_rows,
            "validation_results": validation_rows,
            "meta_update_after": bool(step["meta_update_after"]),
            "meta_update": None,
        }
        history.append(version_record)
        if step["meta_update_after"]:
            next_prompt, meta_record = update_prompt(
                api=api,
                role=meta,
                meta_system_prompt=meta_system_prompt,
                meta_user_template=meta_user_template,
                current_prompt=current_prompt,
                train_summary=train_summary,
                history=history,
                context_id=f"meta__{prompt_id}__{version_label}",
            )
            version_record["meta_update"] = meta_record
            current_prompt = next_prompt
        version_rows.append(version_record)

    best = max(
        version_rows,
        key=lambda row: (
            float(row["validation_summary"]["overall_mean"]),
            -int(row["version_number"]),
        ),
    )
    final = {
        "prompt_id": prompt_id,
        "prompt_name_ja": prompt.get("name_ja", ""),
        "initial_prompt": str(prompt["faithful_translation_ja"]),
        "best_version_number": int(best["version_number"]),
        "best_version_label": str(best["version_label"]),
        "best_validation_mean": float(best["validation_summary"]["overall_mean"]),
        "optimized_prompt": str(best["prompt_text"]),
        "selection_rule": "highest mean validation rank improvement across training rerankers; earliest version on tie",
    }
    return version_rows, final


def run_test(
    *,
    api: OpenAIRunner,
    prompts: list[dict[str, Any]],
    final_prompts: dict[str, dict[str, Any]],
    instances: dict[str, dict[str, Any]],
    test_ids: list[str],
    rewriter: ModelRole,
    heldout_rerankers: list[ModelRole],
    rewriter_system_prompt: str,
    ranking_template: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prompt in prompts:
        prompt_id = str(prompt["id"])
        final = final_prompts[prompt_id]
        print(f"\n[test] {prompt_id}: initial long")
        rows.extend(
            evaluate_prompt(
                api=api,
                rewriter=rewriter,
                rerankers=heldout_rerankers,
                rewriter_system_prompt=rewriter_system_prompt,
                ranking_template=ranking_template,
                instances=instances,
                intent_ids=test_ids,
                rewriting_prompt=str(prompt["faithful_translation_ja"]),
                prompt_id=prompt_id,
                version_label="initial",
                split="test",
                query_form="long",
                condition="test_initial_long",
            )
        )
        print(f"\n[test] {prompt_id}: optimized long")
        optimized_long = evaluate_prompt(
            api=api,
            rewriter=rewriter,
            rerankers=heldout_rerankers,
            rewriter_system_prompt=rewriter_system_prompt,
            ranking_template=ranking_template,
            instances=instances,
            intent_ids=test_ids,
            rewriting_prompt=str(final["optimized_prompt"]),
            prompt_id=prompt_id,
            version_label=str(final["best_version_label"]),
            split="test",
            query_form="long",
            condition="test_optimized_long",
        )
        rows.extend(optimized_long)
        print(f"\n[test] {prompt_id}: optimized short")
        rows.extend(
            evaluate_prompt(
                api=api,
                rewriter=rewriter,
                rerankers=heldout_rerankers,
                rewriter_system_prompt=rewriter_system_prompt,
                ranking_template=ranking_template,
                instances=instances,
                intent_ids=test_ids,
                rewriting_prompt=str(final["optimized_prompt"]),
                prompt_id=prompt_id,
                version_label=str(final["best_version_label"]),
                split="test",
                query_form="short",
                condition="test_optimized_short",
            )
        )
    return rows


def write_cost_ledger(cache: LLMCache, path: Path) -> None:
    rows = []
    for event in cache.events:
        rows.append(
            {
                "finished_at": event.get("finished_at", ""),
                "status": event.get("status", ""),
                "kind": event.get("kind", ""),
                "role": event.get("role", ""),
                "anonymous_label": event.get("anonymous_label", ""),
                "model": event.get("model", ""),
                "input_tokens": int(event.get("usage", {}).get("input_tokens", 0) or 0),
                "output_tokens": int(event.get("usage", {}).get("output_tokens", 0) or 0),
                "total_tokens": int(event.get("usage", {}).get("total_tokens", 0) or 0),
                "cost_usd": float(event.get("cost_usd", 0) or 0),
                "job_id": event.get("job_id", ""),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["cumulative_cost_usd"] = frame["cost_usd"].cumsum()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def plan_summary(
    mode: str,
    prompt_count: int,
    train_count: int,
    validation_count: int,
    test_count: int,
    schedule_count: int,
    training_rerankers: int,
    heldout_rerankers: int,
) -> dict[str, Any]:
    rewrites_optimization = prompt_count * schedule_count * (
        train_count // max(schedule_count // (2 if mode == "full" else 1), 1)
        + validation_count
    )
    return {
        "mode": mode,
        "prompt_count": prompt_count,
        "train_count": train_count,
        "validation_count": validation_count,
        "test_count": test_count,
        "evaluated_versions_per_prompt": schedule_count,
        "training_reranker_count": training_rerankers,
        "heldout_reranker_count": heldout_rerankers,
        "note": "実API回数はキャッシュ再利用と失敗再試行で変動する。",
        "rough_optimization_rewrite_count": rewrites_optimization,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "OPENAI_API_KEYを1つ使い、複数OpenAIモデルでE-GEOのメタ最適化、"
            "Validation選択、Test長文・短文評価まで自動実行する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--initial-prompts", type=Path, default=DEFAULT_INITIAL_PROMPTS)
    parser.add_argument("--common-prompts", type=Path, default=DEFAULT_COMMON_PROMPTS)
    parser.add_argument("--meta-prompt", type=Path, default=DEFAULT_META_PROMPT)
    parser.add_argument("--experiment-config", type=Path, default=DEFAULT_EXPERIMENT_CONFIG)
    parser.add_argument("--model-profile", type=Path, default=DEFAULT_MODEL_PROFILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--prompt-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-test", action="store_true")
    parser.add_argument("--hard-stop-usd", type=float)
    args = parser.parse_args()

    load_dotenv()
    model_profile = read_json(args.model_profile)
    experiment_config = read_json(args.experiment_config)
    common = read_json(args.common_prompts)
    meta_config = read_json(args.meta_prompt)
    prompts = prompt_catalog(read_json(args.initial_prompts))
    require_full = args.mode == "full"
    instances = validate_and_index_instances(read_json(args.instances), require_full=require_full)

    if args.prompt_id:
        prompts = [prompt for prompt in prompts if str(prompt["id"]) == args.prompt_id]
        if not prompts:
            raise ValueError(f"prompt-idが見つかりません: {args.prompt_id}")
    elif args.mode == "smoke":
        prompts = prompts[:1]

    rewriter, meta, training_rerankers, heldout_rerankers = load_model_roles(model_profile)
    if args.mode == "smoke":
        training_rerankers = training_rerankers[:1]
        heldout_rerankers = heldout_rerankers[:1]

    train_ids_all = select_ids(instances, "train")
    validation_ids_all = select_ids(instances, "validation")
    test_ids_all = select_ids(instances, "test")

    if args.mode == "full":
        optimization = experiment_config["optimization"]
        train_ids = train_ids_all
        validation_ids = validation_ids_all
        test_ids = test_ids_all
        schedule = deterministic_batches(
            train_ids,
            epochs=int(optimization["epochs"]),
            batches_per_epoch=int(optimization["batches_per_epoch"]),
            batch_size=int(optimization["batch_size"]),
            seed=int(optimization["numpy_seed"]),
        )
    else:
        if len(train_ids_all) < 2 or len(validation_ids_all) < 1 or len(test_ids_all) < 1:
            raise ValueError(
                "smokeにもTrain 2件、Validation 1件、Test 1件が必要です。"
                "候補10件を80購入意図で確定してから実行してください。"
            )
        train_ids = train_ids_all[:2]
        validation_ids = validation_ids_all[:1]
        test_ids = test_ids_all[:1]
        schedule = [
            {"epoch": 1, "batch": 1, "intent_ids": [train_ids[0]], "meta_update_after": True},
            {"epoch": 1, "batch": 2, "intent_ids": [train_ids[1]], "meta_update_after": False},
        ]

    plan = plan_summary(
        args.mode,
        len(prompts),
        len(train_ids),
        len(validation_ids),
        len(test_ids),
        len(schedule),
        len(training_rerankers),
        len(heldout_rerankers),
    )
    print("05c OpenAI単一キー・メタ最適化ランナー")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"  Rewriter: {rewriter.model_id}")
    print(f"  Meta-optimizer: {meta.model_id}")
    print(
        "  Training Re-rankers: "
        + ", ".join(f"{role.anonymous_label}={role.model_id}" for role in training_rerankers)
    )
    print(
        "  Held-out Re-rankers: "
        + ", ".join(f"{role.anonymous_label}={role.model_id}" for role in heldout_rerankers)
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "00_execution_plan.json").write_text(
        json.dumps(
            {
                **plan,
                "created_at": utc_now(),
                "execute": bool(args.execute),
                "test_locked": True,
                "model_profile": str(args.model_profile),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not args.execute:
        print("API呼び出し: 0回。--executeを付けると実行します。")
        return
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise EnvironmentError("OPENAI_API_KEYが.envに設定されていません。")

    budget = model_profile["budget"]
    hard_stop = (
        float(args.hard_stop_usd)
        if args.hard_stop_usd is not None
        else float(budget["default_hard_stop_usd"])
    )
    execution = model_profile["execution"]
    cache = LLMCache(args.output_dir / "01_llm_cache.jsonl")
    api = OpenAIRunner(
        cache=cache,
        hard_stop_usd=hard_stop,
        warning_thresholds=[float(item) for item in budget["warning_thresholds_usd"]],
        max_retries=int(execution["max_retries"]),
        retry_max_wait_seconds=float(execution["retry_max_wait_seconds"]),
    )

    rewriter_system_prompt = str(
        common["rewriter_system_prompt"]["faithful_translation_ja"]
    )
    ranking_template = str(
        common["ranking_user_prompt"]["faithful_translation_ja"]
    )
    meta_system_prompt = str(meta_config["system_prompt"]["faithful_translation_ja"])
    meta_user_template = str(meta_config["user_prompt"]["faithful_translation_ja"])

    all_versions: list[dict[str, Any]] = []
    final_prompts: dict[str, dict[str, Any]] = {}
    for prompt in prompts:
        versions, final = run_trajectory(
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

    write_jsonl(args.output_dir / "02_optimization_versions.jsonl", all_versions)
    (args.output_dir / "03_final_prompts.json").write_text(
        json.dumps(list(final_prompts.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    test_rows: list[dict[str, Any]] = []
    if not args.skip_test:
        test_rows = run_test(
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
        write_jsonl(args.output_dir / "04_test_results.jsonl", test_rows)

    write_cost_ledger(cache, args.output_dir / "05_cost_ledger.csv")
    summary = {
        "completed_at": utc_now(),
        "mode": args.mode,
        "status": "complete" if not args.skip_test else "optimization_complete_test_skipped",
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
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n05c完了")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
