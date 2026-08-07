from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

import toeic_claude_batch as batch
import toeic_claude_heldout as sync


OUT = Path("日本語版データ/TOEIC/05_API実験/03_Claude_Heldout評価")
ORIGINAL_MANIFEST = OUT / batch.MANIFEST_FILE
ORIGINAL_RAW = OUT / batch.RAW_RESULTS_FILE
ORIGINAL_FAILURES = OUT / "13_batch_failures.json"
RETRY_MANIFEST = OUT / "14_retry_manifest.jsonl"
RETRY_STATE = OUT / "15_retry_batch_state.json"
RETRY_RAW = OUT / "16_retry_batch_raw_results.jsonl"
REPAIR_FAILURES = OUT / "17_retry_failures.json"
REPAIR_LEDGER = OUT / "18_combined_batch_cost_ledger.csv"


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def validate_ranking_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("JSON objectではありません。")
    ranking = [int(item) for item in value.get("ranking", [])]
    questionable = [int(item) for item in value.get("questionable_products", [])]
    if len(ranking) != 10 or sorted(ranking) != list(range(1, 11)):
        raise ValueError(
            f"rankingは1〜10を一度ずつ含む必要があります: {ranking}"
        )
    if len(set(questionable)) != len(questionable):
        raise ValueError("questionable_productsが重複しています。")
    if any(item < 1 or item > 10 for item in questionable):
        raise ValueError(
            "questionable_productsに1〜10以外が含まれています。"
        )
    return {
        "ranking": ranking,
        "questionable_products": questionable,
    }


def parse_ranking_tolerant(text: str) -> dict[str, Any]:
    """Find the first valid ranking JSON object and ignore trailing extra output."""
    value = sync.base.strip_code_fence(text)
    decoder = json.JSONDecoder()
    cursor = 0
    errors: list[str] = []

    while cursor < len(value):
        start = value.find("{", cursor)
        if start < 0:
            break
        try:
            parsed, consumed = decoder.raw_decode(value[start:])
            try:
                return validate_ranking_object(parsed)
            except Exception as exc:
                errors.append(str(exc))
            cursor = start + max(consumed, 1)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            cursor = start + 1

    tail = "; ".join(errors[-3:])
    raise ValueError(
        "有効なranking JSON objectを抽出できません。"
        + (f" details={tail}" if tail else "")
    )


def extract_response(
    raw: dict[str, Any],
    role: sync.ClaudeRole,
) -> tuple[dict[str, Any], float]:
    text, usage = batch.extract_message(raw)
    parsed = parse_ranking_tolerant(text)
    cost = batch.batch_cost(
        usage,
        role.input_usd_per_million * 0.5,
        role.output_usd_per_million * 0.5,
    )
    return {
        "custom_id": str(raw["custom_id"]),
        "model": role.model_id,
        "output_text": text,
        "parsed": parsed,
        "usage": usage,
        "cost_usd": cost,
    }, cost


def build_repair_plan(
    role: sync.ClaudeRole,
) -> tuple[list[str], Counter[str], int]:
    failures = read_json(ORIGINAL_FAILURES)
    retry_ids: list[str] = []
    retry_reasons: Counter[str] = Counter()
    locally_recovered = 0

    for row in failures:
        custom_id = str(row["custom_id"])
        raw = row.get("raw")
        if not isinstance(raw, dict):
            retry_ids.append(custom_id)
            retry_reasons["failure recordにraw結果がありません"] += 1
            continue
        try:
            extract_response(raw, role)
            locally_recovered += 1
        except Exception as exc:
            retry_ids.append(custom_id)
            retry_reasons[str(exc)] += 1

    if len(retry_ids) != len(set(retry_ids)):
        raise ValueError("再送custom_idが重複しています。")
    return retry_ids, retry_reasons, locally_recovered


def retry_manifest(role: sync.ClaudeRole) -> list[dict[str, Any]]:
    retry_ids, _, _ = build_repair_plan(role)
    original = {
        row["custom_id"]: row for row in read_jsonl(ORIGINAL_MANIFEST)
    }
    missing = sorted(set(retry_ids) - set(original))
    if missing:
        raise ValueError(
            f"元manifestにないcustom_idがあります: {missing[:5]}"
        )
    rows = [original[item] for item in retry_ids]
    write_jsonl(RETRY_MANIFEST, rows)
    return rows


def collect_all(
    role: sync.ClaudeRole,
    retry_raw: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], float]:
    responses: dict[str, dict[str, Any]] = {}
    ledger: list[dict[str, Any]] = []
    total = 0.0

    attempts = [
        ("original_batch", read_jsonl(ORIGINAL_RAW)),
        ("retry_batch", retry_raw),
    ]
    for attempt_name, rows in attempts:
        for raw in rows:
            custom_id = str(raw.get("custom_id", ""))
            usage_cost = 0.0
            result = raw.get("result", {})
            if result.get("type") == "succeeded":
                message = result.get("message", {})
                usage_raw = message.get("usage", {})
                usage = {
                    "input_tokens": int(
                        usage_raw.get("input_tokens", 0) or 0
                    ),
                    "cache_creation_input_tokens": int(
                        usage_raw.get("cache_creation_input_tokens", 0) or 0
                    ),
                    "cache_read_input_tokens": int(
                        usage_raw.get("cache_read_input_tokens", 0) or 0
                    ),
                    "output_tokens": int(
                        usage_raw.get("output_tokens", 0) or 0
                    ),
                }
                usage_cost = batch.batch_cost(
                    usage,
                    role.input_usd_per_million * 0.5,
                    role.output_usd_per_million * 0.5,
                )
                total += usage_cost
            try:
                response, _ = extract_response(raw, role)
                responses[custom_id] = response
                status = "success"
                error = ""
            except Exception as exc:
                status = "failed"
                error = str(exc)
            ledger.append(
                {
                    "attempt": attempt_name,
                    "custom_id": custom_id,
                    "status": status,
                    "cost_usd": usage_cost,
                    "error": error,
                }
            )
    return responses, ledger, total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["validate", "submit", "status", "collect"],
        required=True,
    )
    args = parser.parse_args()

    load_dotenv()
    config = sync.base.read_json(sync.DEFAULT_CONFIG)
    role = sync.ClaudeRole.from_config(config)
    rows = retry_manifest(role)
    retry_ids, reasons, locally_recovered = build_repair_plan(role)

    print("Claude Batch 失敗分修復 v2")
    print(f"  Mode: {args.mode}")
    print(f"  Original failures: {locally_recovered + len(retry_ids)}")
    print(f"  Locally recovered without API: {locally_recovered}")
    print(f"  Retry requests: {len(rows)}")
    print("  GPT/Gemini再実行: なし")
    print("  成功済みClaude結果の再実行: なし")
    for reason, count in reasons.most_common():
        print(f"  retry reason x{count}: {reason[:180]}")

    if args.mode == "validate":
        print("修復Validate完了：APIは呼び出していません。")
        return

    key = os.environ.get(role.api_key_env, "").strip()
    if not key:
        raise EnvironmentError(
            f"{role.api_key_env}が.envに設定されていません。"
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=key)
    batches = batch.batch_resource(client)

    if args.mode == "submit":
        if not rows:
            raise RuntimeError(
                "API再送対象が0件です。Collect用ローカル回収のみで完了できます。"
            )
        if RETRY_STATE.exists() and read_json(RETRY_STATE).get("batch_id"):
            raise RuntimeError(
                "既存の修復Batchがあります。Statusを実行してください。"
            )
        created = batches.create(requests=[row["request"] for row in rows])
        data = batch.dump_obj(created)
        state = {
            "created_at": sync.utc_now(),
            "batch_id": data["id"],
            "processing_status": data.get("processing_status"),
            "request_count": len(rows),
            "locally_recovered_count": locally_recovered,
            "model": role.model_id,
            "batch": data,
        }
        write_json(RETRY_STATE, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print("真の失敗分だけを修復Batchへ送信しました。")
        return

    if not RETRY_STATE.exists():
        raise FileNotFoundError(
            "修復Batch stateがありません。先にSubmitしてください。"
        )
    state = read_json(RETRY_STATE)
    batch_id = str(state["batch_id"])
    current = batch.dump_obj(batches.retrieve(batch_id))
    state["last_checked_at"] = sync.utc_now()
    state["processing_status"] = current.get("processing_status")
    state["batch"] = current
    write_json(RETRY_STATE, state)

    if args.mode == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2))
        if state["processing_status"] == "ended":
            print("修復Batch終了。Collectへ進めます。")
        else:
            print("修復Batch処理中です。")
        return

    if state["processing_status"] != "ended":
        raise RuntimeError("修復Batchはまだ終了していません。")

    retry_raw = [
        batch.dump_obj(item) for item in batches.results(batch_id)
    ]
    write_jsonl(RETRY_RAW, retry_raw)
    if len(retry_raw) != len(rows):
        raise ValueError(
            f"修復Batch結果件数が一致しません: "
            f"{len(retry_raw)} != {len(rows)}"
        )

    responses, ledger, total_batch_cost = collect_all(role, retry_raw)
    manifest = read_jsonl(ORIGINAL_MANIFEST)
    expected_ids = {row["custom_id"] for row in manifest}
    missing = sorted(expected_ids - set(responses))
    if missing:
        failures = [{"custom_id": item} for item in missing]
        write_json(REPAIR_FAILURES, failures)
        raise RuntimeError(f"修復後も{len(missing)}件不足しています。")

    final_rows = batch.build_final_rows(
        manifest=manifest,
        responses=responses,
    )
    write_jsonl(OUT / batch.FINAL_RESULTS_FILE, final_rows)
    pd.DataFrame(ledger).to_csv(
        REPAIR_LEDGER,
        index=False,
        encoding="utf-8-sig",
    )
    analysis = sync.analyze_full(final_rows, OUT)
    smoke = sync.base.read_json(OUT / "04_smoke_projection.json")
    summary = {
        "completed_at": sync.utc_now(),
        "status": "complete",
        "execution_mode": (
            "anthropic_message_batch_with_local_json_recovery_and_retry"
        ),
        "model": role.model_id,
        "original_batch_request_count": 930,
        "locally_recovered_count": locally_recovered,
        "retry_batch_request_count": len(rows),
        "test_result_rows": len(final_rows),
        "batch_cost_usd_estimate_including_retry": round(
            total_batch_cost,
            6,
        ),
        "prior_sync_smoke_cost_usd": round(
            float(smoke["smoke_cost_usd"]),
            6,
        ),
        "total_claude_cost_including_smoke_usd": round(
            total_batch_cost + float(smoke["smoke_cost_usd"]),
            6,
        ),
        "openai_gemini_api_rerun": False,
        "rewrites_reused": True,
        "analysis": analysis,
    }
    write_json(OUT / "08_run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Claude修復・結合・分析完了")


if __name__ == "__main__":
    main()
