from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


DEFAULT_VERIFICATION = Path(
    "日本語版データ/TOEIC/04_候補商品/00_dense_retrieval_input_verification.json"
)
DEFAULT_JOBS = Path(
    "日本語版データ/TOEIC/04_候補商品/02_candidate_selection_jobs.jsonl"
)
DEFAULT_PLAN = Path(
    "日本語版データ/TOEIC/04_候補商品/05_candidate_selection_plan.json"
)
DEFAULT_RESULTS = Path(
    "日本語版データ/TOEIC/04_候補商品/06_candidate_selection_results.jsonl"
)
DEFAULT_MODELS = Path(
    "日本語版設定/TOEIC_APIモデル設定_v1.json"
)
DEFAULT_REPORT = Path(
    "日本語版データ/TOEIC/07_本番前チェック/01_candidate_selection_api_preflight.json"
)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONLが見つかりません: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONLを読めません: {path}:{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONLの各行はobjectである必要があります: {line_number}")
        rows.append(value)
    return rows


def successful_result_count(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    rows = read_jsonl(path)
    success = sum(1 for row in rows if row.get("status") == "success")
    return success, len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "最初の有料API工程である候補30件→10件選定について、"
            "入力・固定モデル・APIキーの有無を確認する。APIは呼び出さない。"
        )
    )
    parser.add_argument("--verification", type=Path, default=DEFAULT_VERIFICATION)
    parser.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--require-key",
        action="store_true",
        help="OPENAI_API_KEYがない場合も終了コード1にする。",
    )
    args = parser.parse_args()

    load_dotenv()

    verification = read_json(args.verification)
    jobs = read_jsonl(args.jobs)
    plan = read_json(args.plan)
    models = read_json(args.models)

    candidate_model = models["candidate_selection"]
    model_id = str(candidate_model.get("model_id", "")).strip()
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    success_count, result_row_count = successful_result_count(args.results)

    job_ids = [str(job.get("intent_id", "")) for job in jobs]
    unique_job_ids = len(set(job_ids))

    checks = {
        "dense_input_verification_passed": bool(
            verification.get("verification_passed")
        ),
        "dense_query_mismatch_zero": int(
            verification.get("query_mismatch_rows", -1)
        ) == 0,
        "dense_title_mismatch_zero": int(
            verification.get("title_mismatch_rows", -1)
        ) == 0,
        "dense_description_mismatch_zero": int(
            verification.get("description_mismatch_rows", -1)
        ) == 0,
        "candidate_jobs_80": len(jobs) == 80,
        "candidate_job_intent_ids_unique": unique_job_ids == len(jobs),
        "candidate_plan_calls_80": int(plan.get("api_calls_planned", -1)) == 80,
        "candidate_model_locked": bool(candidate_model.get("locked")),
        "candidate_model_snapshot_fixed": model_id.count("-") >= 4,
        "candidate_model_is_gpt5_mini_snapshot": (
            model_id == "gpt-5-mini-2025-08-07"
        ),
        "openai_api_key_present": key_present,
    }

    structural_keys = [key for key in checks if key != "openai_api_key_present"]
    structural_ready = all(checks[key] for key in structural_keys)
    ready_to_execute = structural_ready and key_present

    report = {
        "stage": "candidate_selection_api_preflight",
        "api_calls_executed_by_this_script": 0,
        "candidate_model": model_id,
        "candidate_jobs": len(jobs),
        "existing_success_results": success_count,
        "existing_result_rows": result_row_count,
        "checks": checks,
        "structural_ready": structural_ready,
        "api_key_present": key_present,
        "ready_to_execute_one_job": ready_to_execute,
        "pilot_command": (
            'uv run python ".\\日本語版コード\\04b_TOEIC候補10商品を選ぶ.py" '
            '--splits train --limit 1 '
            f'--model {model_id} --execute'
        ),
        "full_candidate_selection_command": (
            'uv run python ".\\日本語版コード\\04b_TOEIC候補10商品を選ぶ.py" '
            f'--model {model_id} --execute'
        ),
        "note": (
            "パイロット成功後に全80件を実行する。"
            "候補10件と対象商品は全80件成功時に自動生成される。"
        ),
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("05b 候補選定API直前チェック")
    print(f"  Dense入力検証: {'合格' if checks['dense_input_verification_passed'] else '不合格'}")
    print(f"  候補選定ジョブ: {len(jobs)}件（重複なし={checks['candidate_job_intent_ids_unique']}）")
    print(f"  固定モデル: {model_id}")
    print(f"  既存成功結果: {success_count}/80件")
    print(f"  OPENAI_API_KEY: {'設定済み' if key_present else '未設定'}")
    print(f"  API呼び出し: 0回")
    print(f"  構造上の準備: {'完了' if structural_ready else '要確認'}")
    print(f"  1件パイロット実行可能: {'はい' if ready_to_execute else 'いいえ'}")
    print(f"  レポート: {args.report}")

    if structural_ready and not key_present:
        print("  残りはローカルの.envへOPENAI_API_KEYを設定することだけです。")
    if ready_to_execute:
        print("  次のコマンド:")
        print(f"    {report['pilot_command']}")

    if not structural_ready or (args.require_key and not key_present):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
