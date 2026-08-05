from __future__ import annotations

"""OpenAI＋Geminiだけで先行実行する低予算正式ランナー。

- OpenAIは上限100 USDで正式メタ最適化と全Test条件を担当する。
- GeminiはFlash-Lite系列を使い、上限15 USDで学習と長文Testを担当する。
- Claudeは後日、固定済みプロンプトへ最適化済み長文Testだけ追加する。

APIは --execute を付けない限り呼び出さない。
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


BUDGETED_RUNNER = Path(__file__).with_name(
    "05g_TOEIC費用配分_OpenAI_Gemini_Claude実験.py"
)
MODEL_PROFILE = Path(
    "日本語版設定/TOEIC_OpenAI_Gemini実験設定_v1.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/02_OpenAI_Gemini_Claude実行"
)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


budgeted = load_module(
    BUDGETED_RUNNER,
    "toeic_egeo_budgeted_two_provider",
)


def ensure_default_argument(flag: str, value: str) -> None:
    if flag not in sys.argv:
        sys.argv.extend([flag, value])


def annotate_two_provider_summary() -> None:
    output_dir = DEFAULT_OUTPUT_DIR
    for index, value in enumerate(sys.argv):
        if value == "--output-dir" and index + 1 < len(sys.argv):
            output_dir = Path(sys.argv[index + 1])
            break
    summary_path = output_dir / "06_run_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["provider_configuration"] = "OpenAI + Google Gemini"
    summary["heldout_stage"] = {
        "completed_models": ["GPT-5", "Gemini 3.5 Flash-Lite"],
        "gpt5_conditions": [
            "initial long",
            "optimized long",
            "optimized short",
        ],
        "gemini_conditions": ["initial long", "optimized long"],
        "pending_optional_extension": "Claude Sonnet 5 optimized-long only",
        "prompt_is_frozen_before_heldout_test": True,
        "claude_addition_requires_retraining": False,
        "cache_reuse_expected": True,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    ensure_default_argument("--model-profile", str(MODEL_PROFILE))
    ensure_default_argument("--output-dir", str(DEFAULT_OUTPUT_DIR))
    budgeted.main()
    annotate_two_provider_summary()


if __name__ == "__main__":
    main()
