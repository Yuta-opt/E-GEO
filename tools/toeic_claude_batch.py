from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

import toeic_claude_heldout as sync


DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/05_API実験/03_Claude_Heldout評価")
STATE_FILE = "09_batch_state.json"
MANIFEST_FILE = "10_batch_manifest.jsonl"
RAW_RESULTS_FILE = "11_batch_raw_results.jsonl"
FINAL_RESULTS_FILE = "02_claude_test_results.jsonl"


def dump_obj(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise TypeError(f"APIオブジェクトをJSON化できません: {type(value)}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def stable_id(value: str) -> str:
    return "eg-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:36]


def batch_resource(client: Any) -> Any:
    messages = getattr(client, "messages", None)
    if messages is not None and hasattr(messages, "batches"):
        return messages.batches
    beta = getattr(client, "beta", None)
    if beta is not None and hasattr(beta.messages, "batches"):
        return beta.messages.batches
    raise RuntimeError(
        "インストール済みanthropic SDKがMessage Batches APIに対応していません。"
    )


def build_manifest(
    *,
    instances: dict[str, dict[str, Any]],
    test_ids: list[str],
    source_rows: list[dict[str, Any]],
    ranking_template: str,
    model_id: str,
    temperature: float,
    max_tokens: int,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []

    for intent_id in test_ids:
        instance = instances[intent_id]
        context_id = f"original__{intent_id}__long__Model G"
        user_prompt = ranking_template.format(
            query=sync.base.clean_text(instance["queries"]["long"]),
            formatted_products=sync.base.format_products(instance, None),
        )
        manifest.append(
            {
                "custom_id": stable_id(context_id),
                "kind": "original",
                "context_id": context_id,
                "intent_id": intent_id,
                "request": {
                    "custom_id": stable_id(context_id),
                    "params": {
                        "model": model_id,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": sync.base.RERANKER_SYSTEM_PROMPT_JA,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                },
            }
        )

    for source in source_rows:
        intent_id = str(source["intent_id"])
        instance = instances[intent_id]
        context_id = (
            f"claude_heldout__{source['condition']}__{source['prompt_id']}__"
            f"{intent_id}__long__Model G"
        )
        user_prompt = ranking_template.format(
            query=sync.base.clean_text(instance["queries"]["long"]),
            formatted_products=sync.base.format_products(
                instance,
                str(source["rewritten_description"]),
            ),
        )
        manifest.append(
            {
                "custom_id": stable_id(context_id),
                "kind": "rewritten",
                "context_id": context_id,
                "condition": source["condition"],
                "prompt_id": source["prompt_id"],
                "prompt_name_ja": source["prompt_name_ja"],
                "intent_id": intent_id,
                "target_product_id": source["target_product_id"],
                "target_candidate_position": int(source["target_candidate_position"]),
                "rewritten_description": source["rewritten_description"],
                "request": {
                    "custom_id": stable_id(context_id),
                    "params": {
                        "model": model_id,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": sync.base.RERANKER_SYSTEM_PROMPT_JA,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                },
            }
        )

    if len(manifest) != 930:
        raise ValueError(f"Batch requestが930件ではありません: {len(manifest)}")
    ids = [row["custom_id"] for row in manifest]
    if len(ids) != len(set(ids)):
        raise ValueError("Batch custom_idが重複しています。")
    return manifest


def extract_message(result_row: dict[str, Any]) -> tuple[str, dict[str, int]]:
    result = result_row.get("result", {})
    if result.get("type") != "succeeded":
        raise ValueError(f"Batch itemが成功していません: {result.get('type')}")
    message = result.get("message", {})
    text = "".join(
        str(block.get("text", ""))
        for block in message.get("content", [])
        if block.get("type") == "text"
    ).strip()
    if not text:
        raise ValueError("Batch itemのテキストが空です。")
    usage_raw = message.get("usage", {})
    usage = {
        "input_tokens": int(usage_raw.get("input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(
            usage_raw.get("cache_creation_input_tokens", 0) or 0
        ),
        "cache_read_input_tokens": int(
            usage_raw.get("cache_read_input_tokens", 0) or 0
        ),
        "output_tokens": int(usage_raw.get("output_tokens", 0) or 0),
    }
    return text, usage


def batch_cost(usage: dict[str, int], input_rate: float, output_rate: float) -> float:
    total_input = (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    return (
        total_input / 1_000_000 * input_rate
        + usage["output_tokens"] / 1_000_000 * output_rate
    )


def build_final_rows(
    *,
    manifest: list[dict[str, Any]],
    responses: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    originals: dict[str, dict[str, Any]] = {}
    rewrites: list[dict[str, Any]] = []
    for item in manifest:
        response = responses[item["custom_id"]]
        if item["kind"] == "original":
            originals[item["intent_id"]] = response
        else:
            rewrites.append({**item, "response": response})

    if len(originals) != 30 or len(rewrites) != 900:
        raise ValueError(
            f"収集件数が不正です: original={len(originals)}, rewritten={len(rewrites)}"
        )

    rows: list[dict[str, Any]] = []
    for item in rewrites:
        original = originals[item["intent_id"]]
        rewritten = item["response"]
        target_position = int(item["target_candidate_position"])
        original_rank = list(original["parsed"]["ranking"]).index(target_position) + 1
        rewritten_rank = list(rewritten["parsed"]["ranking"]).index(target_position) + 1
        rows.append(
            {
                "condition": item["condition"],
                "split": "test",
                "query_form": "long",
                "prompt_id": item["prompt_id"],
                "prompt_name_ja": item["prompt_name_ja"],
                "intent_id": item["intent_id"],
                "target_product_id": item["target_product_id"],
                "target_candidate_position": target_position,
                "reranker_label": "Model G",
                "reranker_model": rewritten["model"],
                "original_rank": original_rank,
                "rewritten_rank": rewritten_rank,
                "rank_improvement": original_rank - rewritten_rank,
                "original_questionable_products": original["parsed"]["questionable_products"],
                "rewritten_questionable_products": rewritten["parsed"]["questionable_products"],
                "rewritten_target_flagged_questionable": int(
                    target_position in rewritten["parsed"]["questionable_products"]
                ),
                "rewritten_description": item["rewritten_description"],
                "original_rank_job_id": original["custom_id"],
                "rewritten_rank_job_id": rewritten["custom_id"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["validate", "submit", "status", "collect"],
        default="validate",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    load_dotenv()
    config = sync.base.read_json(sync.DEFAULT_CONFIG)
    role = sync.ClaudeRole.from_config(config)
    instances, test_ids, source_rows, _ = sync.load_validated_inputs(
        instances_path=sync.DEFAULT_INSTANCES,
        source_results_path=sync.DEFAULT_SOURCE_RESULTS,
        source_summary_path=sync.DEFAULT_SOURCE_SUMMARY,
        initial_prompts_path=sync.DEFAULT_INITIAL_PROMPTS,
    )
    common = sync.base.read_json(sync.DEFAULT_COMMON_PROMPTS)
    ranking_template = str(common["ranking_user_prompt"]["faithful_translation_ja"])
    manifest = build_manifest(
        instances=instances,
        test_ids=test_ids,
        source_rows=source_rows,
        ranking_template=ranking_template,
        model_id=role.model_id,
        temperature=role.temperature,
        max_tokens=role.max_output_tokens,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / MANIFEST_FILE
    state_path = args.output_dir / STATE_FILE

    smoke_projection_path = args.output_dir / "04_smoke_projection.json"
    if not smoke_projection_path.exists():
        raise FileNotFoundError("先に通常Smokeを実行してください。")
    smoke = sync.base.read_json(smoke_projection_path)
    standard_projection = float(smoke["full_raw_projection_usd"])
    batch_projection = standard_projection * 0.5
    batch_projection_margin = batch_projection * 1.25

    print("Claude Sonnet 4.5 Batch Held-out評価")
    print(f"  Mode: {args.mode}")
    print(f"  Requests: {len(manifest)}")
    print(f"  Standard projection: ${standard_projection:.4f}")
    print(f"  Batch projection: ${batch_projection:.4f}")
    print(f"  Batch projection with 25% margin: ${batch_projection_margin:.4f}")
    print("  OpenAI/Gemini API再実行: なし")

    if batch_projection_margin > 16.5:
        raise RuntimeError("Batchでも安全余裕込み予測が$16.50を超えています。")

    if args.mode == "validate":
        write_jsonl(manifest_path, manifest)
        print("Batch Validate完了：APIは呼び出していません。")
        return

    api_key = os.environ.get(role.api_key_env, "").strip()
    if not api_key:
        raise EnvironmentError(f"{role.api_key_env}が.envに設定されていません。")
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    batches = batch_resource(client)

    if args.mode == "submit":
        if state_path.exists():
            existing = sync.base.read_json(state_path)
            if existing.get("batch_id"):
                raise RuntimeError(
                    f"既存Batchがあります: {existing['batch_id']}。Statusを確認してください。"
                )
        write_jsonl(manifest_path, manifest)
        batch = batches.create(requests=[row["request"] for row in manifest])
        batch_data = dump_obj(batch)
        state = {
            "created_at": sync.utc_now(),
            "batch_id": batch_data["id"],
            "processing_status": batch_data.get("processing_status"),
            "request_count": len(manifest),
            "model": role.model_id,
            "projected_batch_cost_usd": batch_projection,
            "projected_with_margin_usd": batch_projection_margin,
            "batch": batch_data,
        }
        write_json(state_path, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print("Batchを送信しました。処理は非同期です。次はStatusで確認してください。")
        return

    if not state_path.exists():
        raise FileNotFoundError("Batch stateがありません。先にSubmitしてください。")
    state = sync.base.read_json(state_path)
    batch_id = str(state["batch_id"])
    batch = batches.retrieve(batch_id)
    batch_data = dump_obj(batch)
    state["last_checked_at"] = sync.utc_now()
    state["processing_status"] = batch_data.get("processing_status")
    state["batch"] = batch_data
    write_json(state_path, state)

    if args.mode == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2))
        if state["processing_status"] == "ended":
            print("Batch処理は終了しています。次はCollectを実行してください。")
        else:
            print("Batch処理中です。後でもう一度Statusを実行してください。")
        return

    if state["processing_status"] != "ended":
        raise RuntimeError("Batchはまだ終了していません。先にStatusを確認してください。")

    raw_rows = [dump_obj(item) for item in batches.results(batch_id)]
    write_jsonl(args.output_dir / RAW_RESULTS_FILE, raw_rows)
    if len(raw_rows) != 930:
        raise ValueError(f"Batch結果が930件ではありません: {len(raw_rows)}")

    manifest_by_id = {row["custom_id"]: row for row in manifest}
    responses: dict[str, dict[str, Any]] = {}
    failed: list[dict[str, Any]] = []
    total_batch_cost = 0.0
    ledger_rows: list[dict[str, Any]] = []
    input_rate = role.input_usd_per_million * 0.5
    output_rate = role.output_usd_per_million * 0.5

    for raw in raw_rows:
        custom_id = str(raw.get("custom_id", ""))
        if custom_id not in manifest_by_id:
            raise ValueError(f"未知のcustom_idです: {custom_id}")
        try:
            text, usage = extract_message(raw)
            parsed = sync.parse_ranking_safe(text)
            cost = batch_cost(usage, input_rate, output_rate)
            total_batch_cost += cost
            responses[custom_id] = {
                "custom_id": custom_id,
                "model": role.model_id,
                "output_text": text,
                "parsed": parsed,
                "usage": usage,
                "cost_usd": cost,
            }
            ledger_rows.append(
                {
                    "custom_id": custom_id,
                    "status": "success",
                    **usage,
                    "cost_usd": cost,
                }
            )
        except Exception as exc:
            failed.append({"custom_id": custom_id, "error": str(exc), "raw": raw})
            ledger_rows.append(
                {"custom_id": custom_id, "status": "failed", "cost_usd": 0.0}
            )

    pd.DataFrame(ledger_rows).to_csv(
        args.output_dir / "12_batch_cost_ledger.csv",
        index=False,
        encoding="utf-8-sig",
    )
    if failed:
        write_json(args.output_dir / "13_batch_failures.json", failed)
        raise RuntimeError(f"Batchに{len(failed)}件の失敗があります。結果へ混ぜません。")

    final_rows = build_final_rows(manifest=manifest, responses=responses)
    write_jsonl(args.output_dir / FINAL_RESULTS_FILE, final_rows)
    analysis = sync.analyze_full(final_rows, args.output_dir)
    summary = {
        "completed_at": sync.utc_now(),
        "status": "complete",
        "execution_mode": "anthropic_message_batch",
        "batch_id": batch_id,
        "model": role.model_id,
        "batch_request_count": 930,
        "test_result_rows": len(final_rows),
        "batch_cost_usd_estimate": round(total_batch_cost, 6),
        "prior_sync_smoke_cost_usd": round(float(smoke["smoke_cost_usd"]), 6),
        "total_claude_cost_including_smoke_usd": round(
            total_batch_cost + float(smoke["smoke_cost_usd"]), 6
        ),
        "openai_gemini_api_rerun": False,
        "rewrites_reused": True,
        "analysis": analysis,
    }
    write_json(args.output_dir / "08_run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Claude Batch Collect・分析完了")


if __name__ == "__main__":
    main()
