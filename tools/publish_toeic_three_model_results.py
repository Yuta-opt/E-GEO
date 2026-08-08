from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REPO_ROOT / "日本語版データ" / "TOEIC" / "06_分析結果" / "03_3モデル統合"
LEGACY_DIR = REPO_ROOT / "日本語版ドキュメント" / "実験ログ" / "2026-08-07_OpenAI_Gemini_Full結果"
PUBLISH_DIR = REPO_ROOT / "日本語版ドキュメント" / "実験ログ" / "2026-08-08_3モデル統合_最終結果"
POSTER_DIR = PUBLISH_DIR / "ポスター用図表"

REQUIRED = [
    "00_validation_report.json",
    "01_three_model_integrated_table.csv",
    "02_model_level_statistical_tests.csv",
    "03_prompt_level_statistical_tests.csv",
    "04_prompt_by_model_recovery.csv",
    "05_three_model_paired_rows.csv",
    "06_three_model_results_summary.json",
    "07_three_model_initial_vs_optimized.png",
    "08_three_model_recovery.png",
    "09_prompt_recovery_heatmap.png",
    "10_three_model_results.xlsx",
    "11_three_model_report.md",
]

SUPPLEMENTAL = {
    "03_final_prompts.json": "12_final_prompts.json",
    "03_prompt_convergence_trajectory.csv": "13_prompt_convergence_trajectory.csv",
    "03b_prompt_trajectory.csv": "14_prompt_trajectory.csv",
}

POSTER_COPIES = [
    ("analysis", "07_three_model_initial_vs_optimized.png", "01_3モデル_初期vs最適化.png"),
    ("analysis", "08_three_model_recovery.png", "02_3モデル_回復量.png"),
    ("analysis", "09_prompt_recovery_heatmap.png", "03_3モデル_プロンプト別回復ヒートマップ.png"),
    ("legacy", "08_long_vs_short.png", "04_GPT5_長文vs短文.png"),
    ("legacy", "09_prompt_convergence.png", "05_プロンプト収束.png"),
]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_summary() -> tuple[dict, dict]:
    validation = load_json(ANALYSIS_DIR / "00_validation_report.json")
    summary = load_json(ANALYSIS_DIR / "06_three_model_results_summary.json")

    if validation.get("status") != "pass":
        raise RuntimeError("validation status is not pass")
    if int(validation.get("integrated_long_rows", -1)) != 2700:
        raise RuntimeError(f"expected 2700 integrated rows, got {validation.get('integrated_long_rows')}")
    if int(summary.get("model_count", -1)) != 3:
        raise RuntimeError(f"expected 3 models, got {summary.get('model_count')}")
    if int(summary.get("prompt_count", -1)) != 15:
        raise RuntimeError(f"expected 15 prompts, got {summary.get('prompt_count')}")
    if int(summary.get("intent_count", -1)) != 30:
        raise RuntimeError(f"expected 30 intents, got {summary.get('intent_count')}")
    if int(summary.get("paired_rows", -1)) != 1350:
        raise RuntimeError(f"expected 1350 paired rows, got {summary.get('paired_rows')}")
    return validation, summary


def copy_results(validation: dict, summary: dict) -> None:
    for name in REQUIRED:
        source = ANALYSIS_DIR / name
        if not source.exists():
            raise FileNotFoundError(f"required artifact missing: {source}")

    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    POSTER_DIR.mkdir(parents=True, exist_ok=True)

    for name in REQUIRED:
        shutil.copy2(ANALYSIS_DIR / name, PUBLISH_DIR / name)

    for source_name, dest_name in SUPPLEMENTAL.items():
        source = LEGACY_DIR / source_name
        if source.exists():
            shutil.copy2(source, PUBLISH_DIR / dest_name)
        else:
            print(f"WARNING: supplemental artifact not found: {source}")

    for source_type, source_name, dest_name in POSTER_COPIES:
        base = ANALYSIS_DIR if source_type == "analysis" else LEGACY_DIR
        source = base / source_name
        if source.exists():
            shutil.copy2(source, POSTER_DIR / dest_name)
        else:
            print(f"WARNING: poster figure not found: {source}")

    manifest_files = [
        p for p in PUBLISH_DIR.rglob("*")
        if p.is_file() and p.name != "PUBLISH_MANIFEST.json"
    ]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_analysis_dir": "日本語版データ/TOEIC/06_分析結果/03_3モデル統合",
        "canonical_result_dir": "日本語版ドキュメント/実験ログ/2026-08-08_3モデル統合_最終結果",
        "validation_status": validation["status"],
        "integrated_long_rows": int(validation["integrated_long_rows"]),
        "model_count": int(summary["model_count"]),
        "prompt_count": int(summary["prompt_count"]),
        "intent_count": int(summary["intent_count"]),
        "paired_rows": int(summary["paired_rows"]),
        "primary_inference_unit": summary.get("primary_inference_unit"),
        "files": [
            {
                "path": p.relative_to(PUBLISH_DIR).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in sorted(manifest_files)
        ],
    }
    (PUBLISH_DIR / "PUBLISH_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def git_publish(push: bool) -> None:
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    if branch != "ja-toeic-prototype":
        raise RuntimeError(f"refusing to commit from branch {branch!r}; switch to ja-toeic-prototype")

    rel = "日本語版ドキュメント/実験ログ/2026-08-08_3モデル統合_最終結果"
    run(["git", "add", "--", rel])
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO_ROOT,
    ).returncode
    if staged != 0:
        run(["git", "commit", "-m", "Publish final three-model TOEIC E-GEO results"])
    else:
        print("No new published-result changes to commit.")

    if push:
        run(["git", "push", "origin", "ja-toeic-prototype"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["validate", "publish"], default="validate")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    print("TOEIC E-GEO three-model result publisher")
    print(f"  Mode: {args.mode}")
    print(f"  Repo: {REPO_ROOT}")
    print("  API calls: 0")

    run(["uv", "run", "python", "tools/analyze_toeic_three_model.py", "--mode", "validate"])
    if args.mode == "validate":
        print("Validation complete. No files copied.")
        return

    run(["uv", "run", "python", "tools/analyze_toeic_three_model.py", "--mode", "analyze"])
    validation, summary = validate_summary()
    copy_results(validation, summary)

    print("Published canonical three-model artifacts.")
    print(f"  Model count: {summary['model_count']}")
    print(f"  Integrated rows: {validation['integrated_long_rows']}")
    print(f"  Paired rows: {summary['paired_rows']}")
    print(f"  Overall initial mean: {summary['overall_initial_mean']}")
    print(f"  Overall optimized mean: {summary['overall_optimized_mean']}")
    print(f"  Overall recovery mean: {summary['overall_recovery_mean']}")
    print(f"  Poster figures: {POSTER_DIR}")

    if args.commit or args.push:
        git_publish(push=args.push)


if __name__ == "__main__":
    main()
