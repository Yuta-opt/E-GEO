from __future__ import annotations

"""GPT-5 mini候補選定へ最小推論と厳格な出力上限を追加する安全ラッパー。"""

import importlib.util
import sys
from pathlib import Path
from typing import Any


BASE_SCRIPT = Path(__file__).with_name("04b_TOEIC候補10商品を選ぶ.py")


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
        job["job_id"] = (
            f"candidate_select__{job['intent_id']}__{model}__"
            f"{base.digest(payload)[:12]}"
        )
    return output


def main() -> None:
    base.build_api_jobs = safe_build_api_jobs
    base.main()


if __name__ == "__main__":
    main()
