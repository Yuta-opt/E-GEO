from __future__ import annotations

"""Finish TOEIC analysis and completion checks without rerunning the Full API jobs.

This recovery runner is for a Full run whose API stage completed but whose
analysis stage stopped because 06b passed create_test_charts arguments in the
wrong order. It temporarily patches that single call, runs 06c and 07d, then
restores the tracked source file exactly as it was.
"""

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "日本語版コード"
RUN_DIR = REPO_ROOT / "日本語版データ" / "TOEIC" / "05_API実験" / "02_OpenAI_Gemini_Claude実行"
ANALYSIS_DIR = REPO_ROOT / "日本語版データ" / "TOEIC" / "06_分析結果" / "02_OpenAI_Gemini_Claude"
CONNECTIVITY_DIR = REPO_ROOT / "日本語版データ" / "TOEIC" / "05_API実験" / "00_API接続Smoke"
REPORT_PATH = REPO_ROOT / "日本語版データ" / "TOEIC" / "07_本番前チェック" / "05_OpenAI_Gemini費用配分完了チェック.json"

ANALYSIS_BASE = CODE_DIR / "06b_TOEIC先行研究準拠結果分析.py"
ANALYSIS_RUNNER = CODE_DIR / "06c_TOEIC最終統計分析.py"
COMPLETION_CHECKER = CODE_DIR / "07d_TOEIC最終完了チェック.py"

BAD_CALL = "chart_paths = create_test_charts(test_summary, paired, args.output_dir)"
FIXED_CALL = "chart_paths = create_test_charts(paired, test_summary, args.output_dir)"
EXPECTED_TEST_ROWS = 2250


def run(command: list[str]) -> None:
    print("\n$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def validate_completed_full() -> None:
    summary_path = RUN_DIR / "06_run_summary.json"
    test_path = RUN_DIR / "04_test_results.jsonl"
    if not summary_path.exists() or not test_path.exists():
        raise FileNotFoundError("Full完了データが見つかりません。API本体を再実行しないでください。")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "complete" or summary.get("mode") != "full":
        raise RuntimeError(f"Full完了状態ではありません: {summary.get('status')!r}")

    test_rows = sum(1 for line in test_path.open("r", encoding="utf-8") if line.strip())
    if test_rows != EXPECTED_TEST_ROWS:
        raise RuntimeError(
            f"Test行数が想定と異なります: {test_rows} / {EXPECTED_TEST_ROWS}"
        )

    print("Full API本体の完了を確認しました。")
    print(f"  Test結果: {test_rows}行")
    print(f"  API費用記録: ${float(summary.get('total_api_cost_usd_estimate', 0)):.6f}")
    print("  API本体は再実行しません。")


def main() -> None:
    validate_completed_full()

    original_bytes = ANALYSIS_BASE.read_bytes()
    original_text = original_bytes.decode("utf-8")
    count = original_text.count(BAD_CALL)
    if count != 1:
        raise RuntimeError(
            "06bの既知の引数順ミスを一意に検出できません。"
            f" 検出数={count}"
        )

    patched_text = original_text.replace(BAD_CALL, FIXED_CALL, 1)
    ANALYSIS_BASE.write_text(patched_text, encoding="utf-8")
    try:
        run([
            sys.executable,
            "-m",
            "py_compile",
            str(ANALYSIS_BASE),
            str(ANALYSIS_RUNNER),
            str(COMPLETION_CHECKER),
        ])
        run([
            sys.executable,
            str(ANALYSIS_RUNNER),
            "--run-dir",
            str(RUN_DIR),
            "--output-dir",
            str(ANALYSIS_DIR),
            "--execute-embeddings",
        ])
    finally:
        ANALYSIS_BASE.write_bytes(original_bytes)

    run([
        sys.executable,
        str(COMPLETION_CHECKER),
        "--run-dir",
        str(RUN_DIR),
        "--analysis-dir",
        str(ANALYSIS_DIR),
        "--report",
        str(REPORT_PATH),
        "--connectivity-dir",
        str(CONNECTIVITY_DIR),
        "--expected-heldout-count",
        "2",
    ])

    print("\n============================================================")
    print("TOEIC Full後処理が完了しました。")
    print("API本体の再実行: なし")
    print(f"分析結果: {ANALYSIS_DIR}")
    print(f"完了チェック: {REPORT_PATH}")
    print("============================================================")


if __name__ == "__main__":
    main()
