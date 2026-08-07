from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

import toeic_claude_batch as batch
import toeic_claude_batch_repair_v2 as repair
import toeic_claude_heldout as sync


OUT = repair.OUT
MANIFEST = repair.ORIGINAL_MANIFEST
RETRY_RAW = repair.RETRY_RAW
ATTEMPTS = OUT / "19_final_sync_attempts.jsonl"
FINAL_LEDGER = OUT / "20_final_combined_cost_ledger.csv"
FINAL_SUMMARY = OUT / "08_run_summary.json"
MAX_SYNC_RECOVERY_USD = 0.25


def read_jsonl_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return repair.read_jsonl(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def response_text(response: Any) -> str:
    return "".join(
        str(getattr(block, "text", ""))
        for block in getattr(response, "content", [])
        if getattr(block, "type", "") == "text"
    ).strip()


def response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        "cache_read_input_tokens": int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        ),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def standard_cost(role: sync.ClaudeRole, usage: dict[str, int]) -> float:
    return role.cost(usage)


def successful_saved_response(
    custom_id: str,
) -> tuple[dict[str, Any] | None, float]:
    total_cost = 0.0
    success: dict[str, Any] | None = None
    for row in read_jsonl_optional(ATTEMPTS):
        total_cost += float(row.get("cost_usd", 0) or 0)
        if (
            str(row.get("custom_id")) == custom_id
            and row.get("status") == "success"
        ):
            success = {
                "custom_id": custom_id,
                "model": str(row["model"]),
                "output_text": str(row["output_text"]),
                "parsed": row["parsed"],
                "usage": row["usage"],
                "cost_usd": float(row["cost_usd"]),
            }
    return success, total_cost


def sync_recover(
    *,
    role: sync.ClaudeRole,
    manifest_row: dict[str, Any],
    max_attempts: int = 3,
) -> tuple[dict[str, Any], float]:
    custom_id = str(manifest_row["custom_id"])
    saved, prior_cost = successful_saved_response(custom_id)
    if saved is not None:
        print("  既存の同期回収成功結果を再利用します。")
        return saved, prior_cost

    key = os.environ.get(role.api_key_env, "").strip()
    if not key:
        raise EnvironmentError(f"{role.api_key_env}が.envに設定されていません。")

    from anthropic import Anthropic

    client = Anthropic(api_key=key)
    params = dict(manifest_row["request"]["params"])
    spent = prior_cost
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        started_at = sync.utc_now()
        usage = {
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
        }
        cost = 0.0
        text = ""
        try:
            response = client.messages.create(**params)
            text = response_text(response)
            usage = response_usage(response)
            cost = standard_cost(role, usage)
            spent += cost
            if spent > MAX_SYNC_RECOVERY_USD:
                raise RuntimeError(
                    f"最終1件の同期回収費用が上限${MAX_SYNC_RECOVERY_USD:.2f}を超えました。"
                )
            if not text:
                raise ValueError("Claude同期応答が空です。")
            parsed = repair.parse_ranking_tolerant(text)
            row = {
                "created_at": started_at,
                "finished_at": sync.utc_now(),
                "custom_id": custom_id,
                "context_id": manifest_row["context_id"],
                "status": "success",
                "attempt": attempt,
                "model": role.model_id,
                "output_text": text,
                "parsed": parsed,
                "usage": usage,
                "cost_usd": cost,
            }
            append_jsonl(ATTEMPTS, row)
            print(f"  最終1件を同期回収しました（attempt={attempt}, cost=${cost:.4f}）。")
            return {
                "custom_id": custom_id,
                "model": role.model_id,
                "output_text": text,
                "parsed": parsed,
                "usage": usage,
                "cost_usd": cost,
            }, spent
        except Exception as exc:
            last_error = exc
            row = {
                "created_at": started_at,
                "finished_at": sync.utc_now(),
                "custom_id": custom_id,
                "context_id": manifest_row["context_id"],
                "status": "failed",
                "attempt": attempt,
                "model": role.model_id,
                "output_text": text,
                "usage": usage,
                "cost_usd": cost,
                "error": str(exc),
            }
            append_jsonl(ATTEMPTS, row)
            print(f"  同期回収 attempt={attempt} 失敗: {exc}")
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1) + random.random(), 6.0))

    raise RuntimeError(f"最終1件の同期回収に失敗しました: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Batch修復後に残った1件だけを同条件の同期APIで回収し、最終集計する。"
    )
    parser.add_argument(
        "--mode",
        choices=["validate", "execute"],
        default="validate",
    )
    args = parser.parse_args()

    load_dotenv()
    config = sync.base.read_json(sync.DEFAULT_CONFIG)
    role = sync.ClaudeRole.from_config(config)

    if not RETRY_RAW.exists():
        raise FileNotFoundError("修復Batchの結果がありません。先に修復Collectを一度実行してください。")

    retry_raw = repair.read_jsonl(RETRY_RAW)
    responses, ledger, batch_total_cost = repair.collect_all(role, retry_raw)
    manifest = repair.read_jsonl(MANIFEST)
    manifest_by_id = {str(row["custom_id"]): row for row in manifest}
    expected_ids = set(manifest_by_id)
    missing = sorted(expected_ids - set(responses))

    print("Claude 最終1件回収・集計")
    print(f"  Mode: {args.mode}")
    print(f"  Existing valid responses: {len(responses)}")
    print(f"  Missing responses: {len(missing)}")
    print(f"  Batch cost recorded so far: ${batch_total_cost:.4f}")
    print("  GPT/Gemini再実行: なし")
    print("  Claude成功済み929件の再実行: なし")

    if len(missing) != 1:
        raise RuntimeError(
            f"最終同期回収は不足1件専用です。現在の不足件数={len(missing)}"
        )

    missing_row = manifest_by_id[missing[0]]
    print(f"  Missing custom_id: {missing[0]}")
    print(f"  Missing context: {missing_row['context_id']}")

    if args.mode == "validate":
        print("最終回収Validate完了：APIは呼び出していません。")
        return

    recovered, sync_total_cost = sync_recover(
        role=role,
        manifest_row=missing_row,
    )
    responses[missing[0]] = recovered

    still_missing = sorted(expected_ids - set(responses))
    if still_missing:
        raise RuntimeError(f"最終回収後も不足があります: {still_missing}")

    final_rows = batch.build_final_rows(
        manifest=manifest,
        responses=responses,
    )
    repair.write_jsonl(OUT / batch.FINAL_RESULTS_FILE, final_rows)

    sync_ledger = read_jsonl_optional(ATTEMPTS)
    combined_ledger = list(ledger)
    for row in sync_ledger:
        combined_ledger.append(
            {
                "attempt": "final_sync_recovery",
                "custom_id": row.get("custom_id", ""),
                "status": row.get("status", ""),
                "cost_usd": float(row.get("cost_usd", 0) or 0),
                "error": row.get("error", ""),
            }
        )
    pd.DataFrame(combined_ledger).to_csv(
        FINAL_LEDGER,
        index=False,
        encoding="utf-8-sig",
    )

    analysis = sync.analyze_full(final_rows, OUT)
    smoke = sync.base.read_json(OUT / "04_smoke_projection.json")
    total_claude_cost = (
        batch_total_cost
        + sync_total_cost
        + float(smoke["smoke_cost_usd"])
    )
    summary = {
        "completed_at": sync.utc_now(),
        "status": "complete",
        "execution_mode": (
            "anthropic_message_batch_with_local_json_recovery_batch_retry_and_one_sync_recovery"
        ),
        "model": role.model_id,
        "original_batch_request_count": 930,
        "locally_recovered_count": 27,
        "retry_batch_request_count": 2,
        "final_sync_recovery_count": 1,
        "test_result_rows": len(final_rows),
        "batch_cost_usd_estimate_including_retry": round(batch_total_cost, 6),
        "final_sync_recovery_cost_usd": round(sync_total_cost, 6),
        "prior_sync_smoke_cost_usd": round(float(smoke["smoke_cost_usd"]), 6),
        "total_claude_cost_including_smoke_usd": round(total_claude_cost, 6),
        "openai_gemini_api_rerun": False,
        "rewrites_reused": True,
        "analysis": analysis,
    }
    repair.write_json(FINAL_SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Claude最終1件回収・900行結合・分析完了")


if __name__ == "__main__":
    main()
