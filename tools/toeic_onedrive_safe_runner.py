from __future__ import annotations

"""Run the final TOEIC experiment with retry-safe JSONL appends.

OneDrive and antivirus software can transiently lock the JSONL cache on
Windows. This wrapper retries only PermissionError while preserving all
existing ranking recovery, provider budget, and cache behavior from 05l.
"""

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "日本語版コード"
RETRY_ATTEMPTS = 120
MAX_RETRY_DELAY_SECONDS = 2.0


def find_final_runner() -> Path:
    matches = sorted(CODE_DIR.glob("05l_*.py"))
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one 05l runner, found: "
            + ", ".join(str(path) for path in matches)
        )
    return matches[0]


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module(
    find_final_runner(),
    "toeic_egeo_rank_recovery_with_onedrive_retry",
)
base = runner.base
ORIGINAL_APPEND_JSONL = base.append_jsonl


def retry_safe_append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Retry transient Windows file locks without altering the JSONL row."""

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            ORIGINAL_APPEND_JSONL(path, row)
            if attempt > 1:
                print(
                    "[cache_write_recovered] JSONL追記を再開しました "
                    f"(attempt={attempt}, path={path})"
                )
            return
        except PermissionError:
            if attempt >= RETRY_ATTEMPTS:
                raise
            delay = min(0.25 * attempt, MAX_RETRY_DELAY_SECONDS)
            if attempt == 1 or attempt % 10 == 0:
                print(
                    "[cache_write_retry] OneDrive等による一時ロックを検出。"
                    f" {delay:.2f}秒後に再試行します "
                    f"(attempt={attempt}/{RETRY_ATTEMPTS}, path={path})"
                )
            time.sleep(delay)


def main() -> None:
    base.append_jsonl = retry_safe_append_jsonl
    runner.main()


if __name__ == "__main__":
    main()
