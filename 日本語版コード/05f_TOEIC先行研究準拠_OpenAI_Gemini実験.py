from __future__ import annotations

"""OpenAI＋Geminiだけで先行実行する正式ランナー。

学習・プロンプト固定はGPT-4.1とGeminiで完了させ、Held-out Testは
GPT-5とGemini 3.5 Flashまで実行する。Claudeは後日、同じ出力フォルダと
キャッシュを使って追加できる。

APIは --execute を付けない限り呼び出さない。
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


PRIOR_ALIGNED_RUNNER = Path(__file__).with_name(
    "05e_TOEIC先行研究準拠_OpenAI_Gemini_Claude実験.py"
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


prior = load_module(
    PRIOR_ALIGNED_RUNNER,
    "toeic_egeo_prior_aligned_two_provider",
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
        "completed_models": ["GPT-5", "Gemini 3.5 Flash"],
        "pending_optional_extension": "Claude Sonnet 4.5",
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
    prior.main()
    annotate_two_provider_summary()


if __name__ == "__main__":
    main()
