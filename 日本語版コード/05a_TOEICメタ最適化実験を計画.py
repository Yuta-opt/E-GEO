from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_INTENTS = Path(
    "日本語版データ/TOEIC/03_購入意図/toeic_query_intents_review.xlsx"
)
DEFAULT_PROMPTS = Path(
    "日本語版設定/E_GEO先行研究_初期プロンプト15種.json"
)
DEFAULT_CONFIG = Path(
    "日本語版設定/TOEIC_EGEO実験設定_v2.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/00_実行計画"
)


REQUIRED_SPLITS = ("train", "validation", "test")


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSONが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def load_intents(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"購入意図ファイルが見つかりません: {path}")

    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        frame = pd.read_excel(
            path,
            sheet_name="query_intents",
            dtype=str,
        ).fillna("")
    else:
        frame = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        ).fillna("")

    required = [
        "intent_id",
        "split",
        "short_query_draft",
        "long_query_draft",
        "short_query_final",
        "long_query_final",
        "review_status",
    ]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(
            "購入意図に必要な列がありません: " + ", ".join(missing)
        )

    if frame["intent_id"].duplicated().any():
        duplicates = frame.loc[
            frame["intent_id"].duplicated(),
            "intent_id",
        ].astype(str).tolist()
        raise ValueError(f"intent_idが重複しています: {duplicates[:10]}")

    frame["short_query"] = frame.apply(
        lambda row: clean_text(row["short_query_final"])
        or clean_text(row["short_query_draft"]),
        axis=1,
    )
    frame["long_query"] = frame.apply(
        lambda row: clean_text(row["long_query_final"])
        or clean_text(row["long_query_draft"]),
        axis=1,
    )

    empty = frame.loc[
        frame["short_query"].eq("") | frame["long_query"].eq(""),
        "intent_id",
    ].astype(str).tolist()
    if empty:
        raise ValueError(f"短文または長文クエリが空です: {empty[:10]}")

    not_approved = frame.loc[
        frame["review_status"].ne("承認"),
        "intent_id",
    ].astype(str).tolist()
    if not_approved:
        raise ValueError(f"未承認の購入意図があります: {not_approved[:10]}")

    unknown_splits = sorted(
        set(frame["split"].astype(str)) - set(REQUIRED_SPLITS)
    )
    if unknown_splits:
        raise ValueError(f"未知のsplitがあります: {unknown_splits}")

    return frame.sort_values("intent_id", kind="stable").reset_index(drop=True)


def validate_prompt_catalog(value: Any, expected_count: int) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("初期プロンプト設定はJSON objectである必要があります。")
    prompts = value.get("prompts")
    if not isinstance(prompts, list):
        raise ValueError("初期プロンプト設定にprompts配列がありません。")
    if len(prompts) != expected_count:
        raise ValueError(
            f"初期プロンプト数が{expected_count}件ではありません: {len(prompts)}"
        )

    seen: set[str] = set()
    for prompt in prompts:
        prompt_id = clean_text(prompt.get("id", ""))
        if not prompt_id or prompt_id in seen:
            raise ValueError(f"初期プロンプトIDが空または重複しています: {prompt_id}")
        seen.add(prompt_id)

        source_prompt = str(prompt.get("source_prompt_en", ""))
        japanese_prompt = str(prompt.get("faithful_translation_ja", ""))
        if "{description}" not in source_prompt:
            raise ValueError(f"{prompt_id}: 英語原文に{{description}}がありません。")
        if "{description}" not in japanese_prompt:
            raise ValueError(f"{prompt_id}: 日本語訳に{{description}}がありません。")

    return prompts


def validate_config(
    config: dict[str, Any],
    intents: pd.DataFrame,
    prompt_count: int,
) -> None:
    dataset = config["dataset"]
    actual_counts = {
        str(key): int(value)
        for key, value in intents["split"].value_counts().items()
    }
    for split in REQUIRED_SPLITS:
        expected = int(dataset[split])
        actual = int(actual_counts.get(split, 0))
        if actual != expected:
            raise ValueError(
                f"{split}件数が設定と一致しません: expected={expected}, actual={actual}"
            )

    if int(dataset["total"]) != len(intents):
        raise ValueError(
            f"購入意図総数が設定と一致しません: "
            f"expected={dataset['total']}, actual={len(intents)}"
        )

    expected_prompt_count = int(config["prompt_policy"]["initial_prompt_count"])
    if prompt_count != expected_prompt_count:
        raise ValueError(
            f"プロンプト数が設定と一致しません: "
            f"expected={expected_prompt_count}, actual={prompt_count}"
        )

    optimization = config["optimization"]
    train_count = int(dataset["train"])
    batches = int(optimization["batches_per_epoch"])
    batch_size = int(optimization["batch_size"])
    if batches * batch_size != train_count:
        raise ValueError(
            "batches_per_epoch × batch_size がTrain件数と一致しません: "
            f"{batches} × {batch_size} != {train_count}"
        )

    expected_updates = int(optimization["epochs"]) * (batches - 1)
    if int(optimization["meta_updates_per_prompt"]) != expected_updates:
        raise ValueError(
            "meta_updates_per_promptが設定から計算される値と一致しません: "
            f"expected={expected_updates}"
        )

    query_policy = config["query_policy"]
    if query_policy["optimization_query_form"] != "long":
        raise ValueError("最適化クエリはlongである必要があります。")
    if query_policy["short_query_is_used_during_optimization"]:
        raise ValueError("短文クエリを最適化に使用する設定になっています。")
    if not query_policy["short_query_runs_only_after_prompt_freeze"]:
        raise ValueError("短文クエリはプロンプト固定後のみ実行する必要があります。")


def deterministic_epoch_batches(
    train_ids: list[str],
    epochs: int,
    batches_per_epoch: int,
    batch_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = np.asarray(sorted(train_ids), dtype=object)

    for epoch in range(1, epochs + 1):
        rng = np.random.default_rng(seed + epoch - 1)
        shuffled = source[rng.permutation(len(source))]
        for batch in range(1, batches_per_epoch + 1):
            start = (batch - 1) * batch_size
            stop = start + batch_size
            batch_ids = [str(value) for value in shuffled[start:stop]]
            if len(batch_ids) != batch_size:
                raise ValueError(
                    f"epoch={epoch}, batch={batch}の件数が不正です。"
                )
            rows.append(
                {
                    "epoch": epoch,
                    "batch": batch,
                    "train_intent_ids": batch_ids,
                    "meta_update_after_batch": batch < batches_per_epoch,
                }
            )
    return rows


def build_schedule(
    prompts: list[dict[str, Any]],
    intents: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    optimization = config["optimization"]
    train_ids = intents.loc[
        intents["split"].eq("train"),
        "intent_id",
    ].astype(str).tolist()
    validation_ids = intents.loc[
        intents["split"].eq("validation"),
        "intent_id",
    ].astype(str).tolist()

    generic_batches = deterministic_epoch_batches(
        train_ids=train_ids,
        epochs=int(optimization["epochs"]),
        batches_per_epoch=int(optimization["batches_per_epoch"]),
        batch_size=int(optimization["batch_size"]),
        seed=int(optimization["numpy_seed"]),
    )

    rows: list[dict[str, Any]] = []
    for prompt in prompts:
        prompt_id = str(prompt["id"])
        version_number = 0
        for batch in generic_batches:
            version_number += 1
            rows.append(
                {
                    "initial_prompt_id": prompt_id,
                    "initial_prompt_name_ja": prompt.get("name_ja", ""),
                    "prompt_version_number": version_number,
                    "prompt_version_label": (
                        f"{prompt_id}__e{batch['epoch']}_b{batch['batch']}"
                    ),
                    "epoch": batch["epoch"],
                    "batch": batch["batch"],
                    "train_query_form": "long",
                    "train_intent_count": len(batch["train_intent_ids"]),
                    "train_intent_ids": "|".join(batch["train_intent_ids"]),
                    "validation_query_form": "long",
                    "validation_intent_count": len(validation_ids),
                    "validation_intent_ids": "|".join(validation_ids),
                    "history_accumulates": True,
                    "meta_update_after_batch": batch["meta_update_after_batch"],
                    "test_access_allowed": False,
                }
            )

    return pd.DataFrame(rows)


def call_components(
    plan: dict[str, Any],
    short_evaluates_initial: bool,
) -> list[dict[str, Any]]:
    prompt_count = int(plan["prompt_count"])
    train_count = int(plan["train_count"])
    validation_count = int(plan["validation_count"])
    test_count = int(plan["test_count"])
    epochs = int(plan["epochs"])
    batches = int(plan["batches_per_epoch"])
    batch_size = int(plan["batch_size"])
    training_engines = int(plan["training_reranker_count"])
    heldout_engines = int(plan["heldout_reranker_count"])
    run_short = bool(plan["run_supplemental_short"])

    evaluated_versions = epochs * batches
    train_rewrites = prompt_count * evaluated_versions * batch_size
    validation_rewrites = (
        prompt_count * evaluated_versions * validation_count
    )
    meta_updates = prompt_count * epochs * max(batches - 1, 0)

    rows = [
        {
            "stage": "candidate_selection",
            "role": "30件から10件を選ぶ",
            "api_calls": int(plan["candidate_selection_count"]),
        },
        {
            "stage": "original_rank_train_validation_long",
            "role": "Train・Validationの元順位を学習Re-rankerごとに一度だけキャッシュ",
            "api_calls": (train_count + validation_count) * training_engines,
        },
        {
            "stage": "original_rank_test_long",
            "role": "Test長文の元順位を評価専用Re-rankerごとにキャッシュ",
            "api_calls": test_count * heldout_engines,
        },
        {
            "stage": "optimization_rewrite_train",
            "role": "各プロンプト版でTrain対象商品の説明を書き換え",
            "api_calls": train_rewrites,
        },
        {
            "stage": "optimization_rank_train",
            "role": "Train書き換え後を学習Re-rankerで順位付け",
            "api_calls": train_rewrites * training_engines,
        },
        {
            "stage": "optimization_rewrite_validation",
            "role": "各プロンプト版でValidation対象商品の説明を書き換え",
            "api_calls": validation_rewrites,
        },
        {
            "stage": "optimization_rank_validation",
            "role": "Validation書き換え後を学習Re-rankerで順位付け",
            "api_calls": validation_rewrites * training_engines,
        },
        {
            "stage": "meta_optimizer",
            "role": "履歴を読んで次のリライトプロンプトを生成",
            "api_calls": meta_updates,
        },
        {
            "stage": "test_rewrite_initial",
            "role": "15種類の初期プロンプトをTest対象商品へ適用",
            "api_calls": prompt_count * test_count,
        },
        {
            "stage": "test_rank_initial_long",
            "role": "初期プロンプトのTest長文順位を評価専用Re-rankerで測定",
            "api_calls": prompt_count * test_count * heldout_engines,
        },
        {
            "stage": "test_rewrite_optimized",
            "role": "Validationで固定した最適化プロンプトをTest対象商品へ適用",
            "api_calls": prompt_count * test_count,
        },
        {
            "stage": "test_rank_optimized_long",
            "role": "最適化プロンプトのTest長文順位を評価専用Re-rankerで測定",
            "api_calls": prompt_count * test_count * heldout_engines,
        },
    ]

    if run_short:
        rows.extend(
            [
                {
                    "stage": "original_rank_test_short",
                    "role": "Test短文の元順位を評価専用Re-rankerでキャッシュ",
                    "api_calls": test_count * heldout_engines,
                },
                {
                    "stage": "test_rank_optimized_short",
                    "role": (
                        "長文Testで作成済みの最適化リライトを再利用し、"
                        "短文クエリだけで順位付け"
                    ),
                    "api_calls": prompt_count * test_count * heldout_engines,
                },
            ]
        )
        if short_evaluates_initial:
            rows.append(
                {
                    "stage": "test_rank_initial_short",
                    "role": (
                        "長文Testで作成済みの初期リライトを再利用し、"
                        "短文クエリだけで順位付け"
                    ),
                    "api_calls": prompt_count * test_count * heldout_engines,
                }
            )

    return rows


def build_call_plan(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    short_evaluates_initial = bool(
        config["query_policy"]["short_query_evaluates_initial_prompts"]
    )
    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for plan in config["execution_plans"]:
        components = call_components(plan, short_evaluates_initial)
        total = sum(int(row["api_calls"]) for row in components)
        for row in components:
            detail_rows.append(
                {
                    "plan_id": plan["id"],
                    "plan_label_ja": plan["label_ja"],
                    "formal_research_result": bool(
                        plan["formal_research_result"]
                    ),
                    **row,
                }
            )
        summary_rows.append(
            {
                "plan_id": plan["id"],
                "plan_label_ja": plan["label_ja"],
                "formal_research_result": bool(
                    plan["formal_research_result"]
                ),
                "prompt_count": int(plan["prompt_count"]),
                "training_reranker_count": int(
                    plan["training_reranker_count"]
                ),
                "heldout_reranker_count": int(
                    plan["heldout_reranker_count"]
                ),
                "planned_api_calls": total,
                "api_calls_executed": 0,
            }
        )

    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows)


def write_outputs(
    output_dir: Path,
    schedule: pd.DataFrame,
    call_detail: pd.DataFrame,
    call_summary: pd.DataFrame,
    intents: pd.DataFrame,
    prompts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_path = output_dir / "01_meta_optimization_schedule.csv"
    detail_path = output_dir / "02_api_call_plan_by_stage.csv"
    summary_path = output_dir / "03_api_call_plan_summary.csv"
    json_path = output_dir / "04_meta_optimization_plan.json"

    schedule.to_csv(schedule_path, index=False, encoding="utf-8-sig")
    call_detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    call_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    split_counts = {
        str(key): int(value)
        for key, value in intents["split"].value_counts().items()
    }
    plan = {
        "design_version": config["schema_version"],
        "status": "dry_run_complete_api_not_started",
        "api_calls_executed": 0,
        "test_locked": True,
        "optimization_query_form": "long",
        "supplemental_query_form": "short_after_prompt_freeze",
        "intent_count": int(len(intents)),
        "split_counts": split_counts,
        "prompt_count": len(prompts),
        "prompt_ids": [str(prompt["id"]) for prompt in prompts],
        "evaluated_prompt_versions_per_initial_prompt": int(
            config["optimization"]["epochs"]
        ) * int(config["optimization"]["batches_per_epoch"]),
        "meta_updates_per_initial_prompt": int(
            config["optimization"]["meta_updates_per_prompt"]
        ),
        "schedule_rows": int(len(schedule)),
        "execution_plan_summaries": call_summary.to_dict(orient="records"),
        "unresolved_before_api": [
            "候補30件から10件を選ぶAPIモデルの正式ID",
            "Rewriterの正式モデルID",
            "Meta-optimizerの正式モデルID",
            "学習Re-ranker 2モデルの正式ID",
            "評価専用Re-ranker 1モデルの正式ID",
            "各モデルの実行時点の公式料金と予算見積り",
        ],
        "input_hashes": {
            "intents": digest(
                intents[
                    ["intent_id", "split", "short_query", "long_query"]
                ].to_dict(orient="records")
            ),
            "initial_prompts": digest(prompts),
            "experiment_config": digest(config),
        },
        "next_step": (
            "05本体を、候補10件確定後にbaseline・initial prompt・"
            "meta-optimize・validation・freeze・testを段階実行できる"
            "状態へ改修する。APIはまだ実行しない。"
        ),
    }
    json_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return [schedule_path, detail_path, summary_path, json_path]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "TOEIC版E-GEOのメタ最適化スケジュールとAPI予定回数を作る。"
            "このコードはAPIを呼び出さない。"
        )
    )
    parser.add_argument("--intents", type=Path, default=DEFAULT_INTENTS)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    intents = load_intents(args.intents)
    config = read_json(args.config)
    prompts = validate_prompt_catalog(
        read_json(args.prompts),
        int(config["prompt_policy"]["initial_prompt_count"]),
    )
    validate_config(config, intents, len(prompts))

    schedule = build_schedule(prompts, intents, config)
    call_detail, call_summary = build_call_plan(config)

    print("05a メタ最適化実験計画の検査が完了しました。")
    print(f"  購入意図: {len(intents)}件")
    print(
        "  split: "
        + ", ".join(
            f"{split}={int((intents['split'] == split).sum())}"
            for split in REQUIRED_SPLITS
        )
    )
    print(f"  初期プロンプト: {len(prompts)}種類")
    print(
        "  最適化: "
        f"{config['optimization']['epochs']} epochs × "
        f"{config['optimization']['batches_per_epoch']} batches × "
        f"{config['optimization']['batch_size']}件"
    )
    print(
        "  各初期プロンプトの評価版数: "
        f"{config['optimization']['epochs'] * config['optimization']['batches_per_epoch']}"
    )
    print(
        "  各初期プロンプトのMeta-optimizer更新回数: "
        f"{config['optimization']['meta_updates_per_prompt']}"
    )
    for row in call_summary.itertuples(index=False):
        print(
            f"  {row.plan_id}: 予定API呼び出し {row.planned_api_calls}回 "
            f"（実行0回）"
        )
    print("  Testロック: 有効")
    print("  API呼び出し: 0回")

    if args.preview:
        print("Preview only. ファイルは作成していません。")
        return

    expected = [
        args.output_dir / "01_meta_optimization_schedule.csv",
        args.output_dir / "02_api_call_plan_by_stage.csv",
        args.output_dir / "03_api_call_plan_summary.csv",
        args.output_dir / "04_meta_optimization_plan.json",
    ]
    existing = [path for path in expected if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "実行計画が既にあります。再作成時は --overwrite を付けてください。\n"
            + "\n".join(str(path) for path in existing)
        )

    paths = write_outputs(
        args.output_dir,
        schedule,
        call_detail,
        call_summary,
        intents,
        prompts,
        config,
    )
    print("実行計画を保存しました。")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
