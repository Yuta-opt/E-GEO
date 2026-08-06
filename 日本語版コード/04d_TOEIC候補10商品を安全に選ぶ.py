from __future__ import annotations

"""GPT-5 mini候補選定の本番安全ラッパー。

- minimal reasoningと出力上限200を固定する。
- JSON解析失敗もAPI試行として再試行する。
- 成功・失敗の全試行についてusageと概算費用を記録する。
- 有効な10件が順不同で返った場合は、集合を変えず昇順へ正規化する。
- 旧実行で順不同だけを理由に失敗した応答は、追加APIなしで回収する。
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
RUNNER_REVISION = "04d-candidate-safety-v3"


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


def parse_candidate_selection(
    text: str,
) -> tuple[list[int], list[int], bool]:
    """候補集合を検証し、順不同だけなら昇順へ正規化する。

    LLMの出力順は研究上の順位ではなく、選択された10件の集合だけが意味を持つ。
    そのため、件数・重複・範囲が正しい場合は、集合を変えずDense Retrieval順
    （index昇順）へ決定論的に並べ替える。
    """

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    value = json.loads(cleaned)
    if not isinstance(value, list):
        raise ValueError("候補選定結果はJSON配列である必要があります。")

    raw_selected = [int(number) for number in value]
    if len(raw_selected) != 10:
        raise ValueError(f"選定件数が10件ではありません: {raw_selected}")
    if len(set(raw_selected)) != 10:
        raise ValueError(f"選定indexが重複しています: {raw_selected}")
    if any(number < 0 or number > 29 for number in raw_selected):
        raise ValueError(
            f"選定indexが0〜29の範囲外です: {raw_selected}"
        )

    selected = sorted(raw_selected)
    base.parse_selection(json.dumps(selected))
    return selected, raw_selected, selected != raw_selected


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


def reusable_prior_output(
    result_path: Path,
    job: dict[str, Any],
) -> tuple[dict[str, Any], list[int], list[int], bool] | None:
    """旧失敗ログに意味的に有効な候補集合があれば回収する。"""

    if not result_path.exists():
        return None
    rows = base.read_jsonl_rows(result_path)
    for row in reversed(rows):
        if row.get("status") != "failed":
            continue
        if str(row.get("intent_id", "")) != str(job["intent_id"]):
            continue
        if str(row.get("model", "")) != str(job["model"]):
            continue
        text = str(row.get("raw_output", "") or "").strip()
        if not text:
            continue
        try:
            selected, raw_selected, normalized = parse_candidate_selection(text)
        except Exception:
            continue
        return row, selected, raw_selected, normalized
    return None


def recovered_success_row(
    job: dict[str, Any],
    prior: dict[str, Any],
    selected: list[int],
    raw_selected: list[int],
    order_normalized: bool,
) -> dict[str, Any]:
    row = {
        key: value
        for key, value in job.items()
        if key != "payload"
    }
    timestamp = base.now()
    row.update(
        {
            "status": "success",
            "attempt": 0,
            "selected_indices": selected,
            "raw_selected_indices": raw_selected,
            "selection_order_normalized": order_normalized,
            "selection_order_policy": (
                "valid distinct index set is sorted ascending; "
                "selected product set is unchanged"
            ),
            "raw_output": str(prior.get("raw_output", "")),
            "usage": prior.get("usage", openai_usage(None)),
            "cost_usd": 0.0,
            "response_id": prior.get("response_id"),
            "recovered_without_api_call": True,
            "recovered_from_job_id": prior.get("job_id"),
            "recovered_from_attempt": prior.get("attempt"),
            "prior_cost_already_recorded_usd": float(
                prior.get("cost_usd", 0) or 0
            ),
            "started_at": timestamp,
            "finished_at": timestamp,
        }
    )
    return row


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

        recovered = reusable_prior_output(result_path, job)
        if recovered is not None:
            prior, selected, raw_selected, order_normalized = recovered
            row = recovered_success_row(
                job,
                prior,
                selected,
                raw_selected,
                order_normalized,
            )
            base.append_jsonl(result_path, row)
            cache[job["job_id"]] = row
            print(
                f"[candidate_recover {number}/{len(api_jobs)}] "
                f"{job['intent_id']} 追加APIなしで旧応答を回収"
            )
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
                (
                    selected,
                    raw_selected,
                    order_normalized,
                ) = parse_candidate_selection(text)
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
                        "raw_selected_indices": raw_selected,
                        "selection_order_normalized": order_normalized,
                        "selection_order_policy": (
                            "valid distinct index set is sorted ascending; "
                            "selected product set is unchanged"
                        ),
                        "raw_output": text,
                        "usage": usage,
                        "cost_usd": cost,
                        "response_id": getattr(response, "id", None),
                        "recovered_without_api_call": False,
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
    normalized_jobs = sum(
        int(bool(row.get("selection_order_normalized")))
        for row in latest.values()
        if row.get("status") == "success"
    )
    recovered_jobs = sum(
        int(bool(row.get("recovered_without_api_call")))
        for row in latest.values()
        if row.get("status") == "success"
    )
    summary = {
        "runner_revision": RUNNER_REVISION,
        "successful_jobs": len(latest),
        "failed_jobs": 0,
        "order_normalized_jobs": normalized_jobs,
        "recovered_without_api_call_jobs": recovered_jobs,
        "normalization_changes_selected_set": False,
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
