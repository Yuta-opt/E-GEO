from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

DEFAULT_INPUT = Path("日本語版データ/TOEIC/04_候補商品/toeic_experiment_instances.json")
DEFAULT_PROMPTS = Path("日本語版設定/TOEIC_EGEOプロンプト設定.json")
DEFAULT_OUTPUT = Path("日本語版データ/TOEIC/05_API実験")
CONDITIONS = ("original", "en_zero", "ja_zero", "ja_adapted")
QUERY_FORMS = ("short", "long")
SPLITS = ("train", "validation", "test")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONLを読めません: {path}:{number}") from exc
        rows[str(row["job_id"])] = row
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def validate_instances(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("04の実験JSONが空です。")
    seen: set[str] = set()
    for row in value:
        intent_id = str(row.get("intent_id", ""))
        if not intent_id or intent_id in seen:
            raise ValueError(f"intent_idが空または重複しています: {intent_id}")
        seen.add(intent_id)
        if row.get("split") not in SPLITS:
            raise ValueError(f"{intent_id}: splitが不正です。")
        if set(row.get("queries", {})) < {"short", "long"}:
            raise ValueError(f"{intent_id}: short/longクエリがありません。")
        products = row.get("products", [])
        if len(products) != 10:
            raise ValueError(f"{intent_id}: 候補商品は10件必要です。")
        positions = sorted(int(p["candidate_position"]) for p in products)
        if positions != list(range(1, 11)):
            raise ValueError(f"{intent_id}: 候補番号が1〜10ではありません。")
        if len({str(p["product_id"]) for p in products}) != 10:
            raise ValueError(f"{intent_id}: 商品が重複しています。")
        targets = [p for p in products if p.get("is_target")]
        if len(targets) != 1 or str(targets[0]["product_id"]) != str(row["target_product_id"]):
            raise ValueError(f"{intent_id}: 対象商品が不正です。")
    return value


def target_product(instance: dict[str, Any]) -> dict[str, Any]:
    return next(product for product in instance["products"] if product.get("is_target"))


def job_id(stage: str, intent: str, condition: str, form: str, model: str, payload: Any) -> str:
    return f"{stage}__{intent}__{condition}__{form}__{model}__{digest(payload)[:12]}"


def rewrite_jobs(
    instances: list[dict[str, Any]], conditions: list[str], config: dict[str, Any], model: str
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for instance in instances:
        product = target_product(instance)
        for condition in conditions:
            if condition == "original":
                continue
            setting = config["conditions"][condition]
            if not setting.get("enabled", True):
                continue
            prompt = setting["user_prompt"].format(
                title=product.get("title", ""),
                description=product.get("description", ""),
                author=product.get("author", ""),
                price_yen=product.get("price_yen", ""),
            )
            payload = {
                "model": model,
                "instructions": config["rewriter_system_prompt"],
                "input": prompt,
                "store": False,
            }
            jobs.append(
                {
                    "job_id": job_id(
                        "rewrite", instance["intent_id"], condition, "none", model, payload
                    ),
                    "stage": "rewrite",
                    "intent_id": instance["intent_id"],
                    "split": instance["split"],
                    "condition": condition,
                    "target_product_id": instance["target_product_id"],
                    "model": model,
                    "payload": payload,
                }
            )
    return jobs


def formatted_products(instance: dict[str, Any], rewritten: str | None) -> str:
    target_id = str(instance["target_product_id"])
    blocks: list[str] = []
    for product in sorted(instance["products"], key=lambda p: int(p["candidate_position"])):
        description = product.get("description", "")
        if rewritten is not None and str(product["product_id"]) == target_id:
            description = rewritten
        blocks.append(
            f"{product['candidate_position']}. 商品名: {product.get('title', '')}\n"
            f"著者: {product.get('author', '')}\n"
            f"価格: {product.get('price_yen', '')}円\n"
            f"説明: {description}"
        )
    return "\n\n".join(blocks)


def rank_jobs(
    instances: list[dict[str, Any]],
    conditions: list[str],
    forms: list[str],
    config: dict[str, Any],
    model: str,
    rewrites: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_key = {
        (str(row.get("intent_id")), str(row.get("condition"))): row
        for row in rewrites.values()
        if row.get("status") == "success"
    }
    jobs: list[dict[str, Any]] = []
    waiting: list[str] = []
    for instance in instances:
        for condition in conditions:
            setting = config["conditions"][condition]
            if condition != "original" and not setting.get("enabled", True):
                continue
            rewritten = None
            if condition != "original":
                result = by_key.get((str(instance["intent_id"]), condition))
                if result is None:
                    waiting.append(f"{instance['intent_id']}:{condition}")
                    continue
                rewritten = result["rewritten_description"]
            for form in forms:
                prompt = config["ranker"]["user_prompt"].format(
                    query=instance["queries"][form],
                    products_text=formatted_products(instance, rewritten),
                )
                payload = {
                    "model": model,
                    "instructions": config["ranker"]["system_prompt"],
                    "input": prompt,
                    "store": False,
                }
                jobs.append(
                    {
                        "job_id": job_id(
                            "rank", instance["intent_id"], condition, form, model, payload
                        ),
                        "stage": "rank",
                        "intent_id": instance["intent_id"],
                        "split": instance["split"],
                        "condition": condition,
                        "query_form": form,
                        "target_product_id": instance["target_product_id"],
                        "model": model,
                        "payload": payload,
                    }
                )
    return jobs, sorted(set(waiting))


def output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text)
    raw = response.model_dump() if hasattr(response, "model_dump") else response
    return "".join(
        content.get("text", "")
        for item in raw.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )


def usage(response: Any) -> dict[str, int]:
    item = getattr(response, "usage", None)
    if item is not None:
        return {
            "input_tokens": int(getattr(item, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(item, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(item, "total_tokens", 0) or 0),
        }
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def api_call(client: Any, payload: dict[str, Any], retries: int) -> tuple[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.responses.create(**payload)
            text = output_text(response).strip()
            if not text:
                raise ValueError("API応答が空です。")
            return text, response
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt + random.random(), 8))
    raise RuntimeError(f"API呼び出しに失敗しました: {last}") from last


def parse_ranking(text: str) -> dict[str, list[int]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    value = json.loads(cleaned)
    ranking = [int(number) for number in value.get("ranking", [])]
    questionable = [int(number) for number in value.get("questionable_products", [])]
    if sorted(ranking) != list(range(1, 11)):
        raise ValueError(f"rankingが不正です: {ranking}")
    if any(number not in range(1, 11) for number in questionable):
        raise ValueError("questionable_productsが不正です。")
    return {"ranking": ranking, "questionable_products": sorted(set(questionable))}


def run_jobs(
    client: Any,
    jobs: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    output: Path,
    retries: int,
) -> None:
    for number, job in enumerate(jobs, 1):
        if cache.get(job["job_id"], {}).get("status") == "success":
            continue
        print(
            f"[{job['stage']} {number}/{len(jobs)}] "
            f"{job['intent_id']} {job['condition']} {job.get('query_form', '')}"
        )
        started = now()
        try:
            text, response = api_call(client, job["payload"], retries)
            row = {key: value for key, value in job.items() if key != "payload"}
            row.update(
                {
                    "status": "success",
                    "usage": usage(response),
                    "response_id": getattr(response, "id", None),
                    "started_at": started,
                    "finished_at": now(),
                }
            )
            if job["stage"] == "rewrite":
                row["rewritten_description"] = text
            else:
                row.update(parse_ranking(text))
                row["raw_output"] = text
        except Exception as exc:
            row = {key: value for key, value in job.items() if key != "payload"}
            row.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "started_at": started,
                    "finished_at": now(),
                }
            )
        append_jsonl(output, row)
        cache[job["job_id"]] = row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TOEIC版E-GEOのAPI実験。既定では計画だけ作り、APIは呼ばない。"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rewriter-model", default="gpt-5-mini")
    parser.add_argument("--reranker-model", default="gpt-5-mini")
    parser.add_argument(
        "--conditions", nargs="+", choices=CONDITIONS,
        default=["original", "en_zero", "ja_zero"]
    )
    parser.add_argument(
        "--query-forms", nargs="+", choices=QUERY_FORMS, default=["short", "long"]
    )
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stage", choices=("plan", "rewrite", "rank", "all"), default="plan")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    load_dotenv()
    instances = validate_instances(read_json(args.input))
    config = read_json(args.prompts)
    selected = sorted(
        [row for row in instances if row["split"] in set(args.splits)],
        key=lambda row: str(row["intent_id"]),
    )
    if args.limit is not None:
        selected = selected[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rewrite_path = args.output_dir / "rewrite_results.jsonl"
    rank_path = args.output_dir / "ranking_results.jsonl"
    rewrite_cache = read_jsonl(rewrite_path)
    rank_cache = read_jsonl(rank_path)

    rewrites = rewrite_jobs(selected, args.conditions, config, args.rewriter_model)
    ranks, waiting = rank_jobs(
        selected, args.conditions, args.query_forms, config,
        args.reranker_model, rewrite_cache
    )
    enabled = [
        condition for condition in args.conditions
        if condition == "original" or config["conditions"][condition].get("enabled", True)
    ]
    expected_ranks = len(selected) * len(args.query_forms) * len(enabled)
    plan = {
        "created_at": now(),
        "input": str(args.input),
        "input_sha256": digest(instances),
        "prompts": str(args.prompts),
        "prompt_sha256": digest(config),
        "intent_count": len(selected),
        "query_source_counts": dict(Counter(row["queries"].get("source", "") for row in selected)),
        "splits": args.splits,
        "conditions_enabled": enabled,
        "query_forms": args.query_forms,
        "rewriter_model": args.rewriter_model,
        "reranker_model": args.reranker_model,
        "expected_rewrite_calls": len(rewrites),
        "expected_rank_calls": expected_ranks,
        "expected_total_calls": len(rewrites) + expected_ranks,
        "rewrite_success_cache": sum(
            rewrite_cache.get(job["job_id"], {}).get("status") == "success" for job in rewrites
        ),
        "rank_success_cache": sum(
            rank_cache.get(job["job_id"], {}).get("status") == "success" for job in ranks
        ),
        "rank_jobs_waiting_for_rewrite": len(waiting),
    }
    plan_path = args.output_dir / "experiment_plan.json"
    write_json(plan_path, plan)

    print("05 API実験プラン")
    print(f"  購入意図: {len(selected)}件")
    print(f"  条件: {', '.join(enabled)}")
    print(f"  クエリ形式: {', '.join(args.query_forms)}")
    print(f"  書き換えAPI予定: {len(rewrites)}回")
    print(f"  順位付けAPI予定: {expected_ranks}回")
    print(f"  合計API予定: {len(rewrites) + expected_ranks}回")
    print(f"  プラン出力: {plan_path}")

    if not args.execute:
        print("Dry-runです。APIは呼んでおらず、料金は発生していません。")
        return
    if args.stage == "plan":
        raise ValueError("--execute時は--stage rewrite/rank/allを指定してください。")
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEYが設定されていません。")

    from openai import OpenAI
    client = OpenAI()

    if args.stage in {"rewrite", "all"}:
        run_jobs(client, rewrites, rewrite_cache, rewrite_path, args.max_retries)

    if args.stage in {"rank", "all"}:
        rewrite_cache = read_jsonl(rewrite_path)
        ranks, waiting = rank_jobs(
            selected, args.conditions, args.query_forms, config,
            args.reranker_model, rewrite_cache
        )
        if waiting:
            raise RuntimeError(
                "書き換え結果が不足しています。先にrewriteを実行してください: "
                + ", ".join(waiting[:10])
            )
        run_jobs(client, ranks, rank_cache, rank_path, args.max_retries)


if __name__ == "__main__":
    main()
