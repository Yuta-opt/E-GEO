from __future__ import annotations

"""GPT-5 mini候補選定の本番安全ラッパー。

- minimal reasoningと出力上限200を固定する。
- JSON解析失敗もAPI試行として再試行する。
- 成功・失敗の全試行についてusageと概算費用を記録する。
- 出力フォルダごとに1 USDで停止する。
- 1件でも未成功なら終了コードを非0にし、後続工程へ進ませない。
"""

import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any


BASE_SCRIPT = Path(__file__).with_name("04b_TOEIC候補10商品を選ぶ.py")
DEFAULT_HARD_STOP_USD = 1.0
RUNNER_REVISION = "04d-candidate-safety-v2"


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = load_module(BASE_SCRIPT, "toeic_candidate_selector_base")
ORIGINAL_BUILD_API_JOBS = base.build_api_jobs


def safe_build_api_jobs(
    jobs: list[dict[str, Any]],
    config: dict[str, Any],
    model: str,
) -> list[dict[str, Any]]:
    output = ORIGINAL_BUILD_API_JOBS(jobs, config, model)
    for job in output:
        payload = dict(job["payload"])
        if str(model).startswith("gpt-5"):
            payload["reasoning"] = {"effort": "minimal"}
        payload["max_output_tokens"] = 200
        job["payload"] = payload
        job["runner_revision"] = RUNNER_REVISION
        job["job_id"] = (
            f"candidate_select__{job['intent_id']}__{model}__"
            f"{base.digest({'revision': RUNNER_REVISION, 'payload': payload})[:12]}"
        )
    return output


def openai_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 0,
        }
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(
        getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
    )
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    cached = int(getattr(input_details, "cached_tokens", 0) or 0)
    reasoning = int(getattr(output_details, "reasoning_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(input_tokens - cached, 0),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def candidate_cost(model: str, usage: dict[str, int]) -> float:
    pricing = {
        "gpt-5-mini-2025-08-07": (0.25, 0.025, 2.0),
        "gpt-5-mini": (0.25, 0.025, 2.0),
    }
    if model not in pricing:
        raise ValueError(
            f"候補選定モデルの料金が未登録です: {model}"
        )
    input_rate, cached_rate, output_rate = pricing[model]
    cached = int(usage.get("cached_input_tokens", 0) or 0)
    total_input = int(usage.get("input_tokens", 0) or 0)
    uncached = max(total_input - cached, 0)
    output = int(usage.get("output_tokens", 0) or 0)
    return (
        uncached / 1_000_000 * input_rate
        + cached / 1_000_000 * cached_rate
        + output / 1_000_000 * output_rate
    )


def event_spend(path: Path) -> float:
    if not path.exists():
        return 0.0
    return float(
        sum(
            float(row.get("cost_usd", 0) or 0)
            for row in base.read_jsonl_rows(path)
        )
    )


def safe_execute_jobs(
    api_jobs: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    result_path: Path,
    retries: int,
) -> None:
    from openai import OpenAI

    client = OpenAI()
    hard_stop = float(
        os.environ.get(
            "TOEIC_CANDIDATE_HARD_STOP_USD",
            DEFAULT_HARD_STOP_USD,
        )
    )
    if hard_stop <= 0:
        raise ValueError("候補選定hard stopは正数である必要があります。")

    for number, job in enumerate(api_jobs, start=1):
        existing = cache.get(job["job_id"])
        if existing and existing.get("status") == "success":
            continue

        print(
            f"[candidate_select {number}/{len(api_jobs)}] "
            f"{job['intent_id']} {job['model']}"
        )
        last_error: Exception | None = None
        succeeded = False

        for attempt in range(1, retries + 1):
            spent = event_spend(result_path)
            if spent >= hard_stop:
                raise RuntimeError(
                    f"候補選定累計${spent:.4f}がhard stop "
                    f"${hard_stop:.2f}へ到達しました。"
                )

            started = base.now()
            response = None
            text = ""
            usage = openai_usage(None)
            cost = 0.0
            try:
                response = client.responses.create(**job["payload"])
                text = base.output_text(response).strip()
                usage = openai_usage(response)
                cost = candidate_cost(str(job["model"]), usage)
                if not text:
                    raise ValueError("API応答が空です。")
                selected = base.parse_selection(text)
                row = {
                    key: value
                    for key, value in job.items()
                    if key != "payload"
                }
                row.update(
                    {
                        "status": "success",
                        "attempt": attempt,
                        "selected_indices": selected,
                        "raw_output": text,
                        "usage": usage,
                        "cost_usd": cost,
                        "response_id": getattr(response, "id", None),
                        "started_at": started,
                        "finished_at": base.now(),
                    }
                )
                base.append_jsonl(result_path, row)
                cache[job["job_id"]] = row
                succeeded = True
                break
            except Exception as exc:
                last_error = exc
                if response is not None and not usage["total_tokens"]:
                    usage = openai_usage(response)
                    cost = candidate_cost(str(job["model"]), usage)
                row = {
                    key: value
                    for key, value in job.items()
                    if key != "payload"
                }
                row.update(
                    {
                        "status": "failed",
                        "attempt": attempt,
                        "raw_output": text,
                        "usage": usage,
                        "cost_usd": cost,
                        "response_id": (
                            getattr(response, "id", None)
                            if response is not None
                            else None
                        ),
                        "error": str(exc),
                        "started_at": started,
                        "finished_at": base.now(),
                    }
                )
                base.append_jsonl(result_path, row)
                cache[job["job_id"]] = row
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1) + random.random(), 8))

        if not succeeded:
            raise RuntimeError(
                f"{job['intent_id']}の候補選定が{retries}回とも失敗しました: "
                f"{last_error}"
            ) from last_error


def argument_value(flag: str) -> str | None:
    for index, value in enumerate(sys.argv):
        if value == flag and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def ensure_requested_jobs_succeeded() -> None:
    if "--execute" not in sys.argv:
        return
    output_dir = Path(
        argument_value("--output-dir") or str(base.DEFAULT_OUTPUT_DIR)
    )
    result_path = output_dir / "06_candidate_selection_results.jsonl"
    if not result_path.exists():
        raise RuntimeError("候補選定結果JSONLが生成されていません。")
    rows = base.read_jsonl_rows(result_path)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("runner_revision") == RUNNER_REVISION:
            latest[str(row.get("job_id", ""))] = row
    failures = [
        row for row in latest.values() if row.get("status") != "success"
    ]
    if failures:
        raise RuntimeError(
            f"候補選定に未成功ジョブが{len(failures)}件あります。"
        )
    summary = {
        "runner_revision": RUNNER_REVISION,
        "successful_jobs": len(latest),
        "failed_jobs": 0,
        "total_cost_usd": round(event_spend(result_path), 6),
        "hard_stop_usd": float(
            os.environ.get(
                "TOEIC_CANDIDATE_HARD_STOP_USD",
                DEFAULT_HARD_STOP_USD,
            )
        ),
    }
    (output_dir / "06b_candidate_cost_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    base.build_api_jobs = safe_build_api_jobs
    base.execute_jobs = safe_execute_jobs
    base.main()
    ensure_requested_jobs_succeeded()


if __name__ == "__main__":
    main()
