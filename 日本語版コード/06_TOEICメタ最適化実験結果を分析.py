from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon


DEFAULT_RUN_DIR = Path(
    "日本語版データ/TOEIC/05_API実験/01_OpenAI単一キー実行"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/06_分析結果")
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

FEATURE_PATTERNS: dict[str, list[str]] = {
    "検索順位向上の目的": ["順位", "ランキング", "可視性", "上位"],
    "ユーザー意図": ["利用者", "ユーザー", "ニーズ", "目的", "探して"],
    "キーワード・同義語": ["キーワード", "同義語", "関連語", "検索語"],
    "冒頭要約": ["冒頭", "要約", "最初に", "概要"],
    "セクション見出し": ["見出し", "セクション", "h2", "h3", "小見出し"],
    "箇条書き": ["箇条書き", "リスト", "bullet"],
    "利用場面": ["利用場面", "使用場面", "ユースケース", "こんな人", "対象者"],
    "FAQ": ["faq", "よくある質問", "質問と回答"],
    "キーワード詰め込み禁止": ["詰め込み", "不自然な反復", "過剰なキーワード", "keyword stuffing"],
    "事実維持": ["事実", "正確", "追加しない", "捏造", "元の情報", "内容を維持"],
}


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONLが見つかりません: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONLを読めません: {path}:{number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONLの各行はobjectである必要があります: {number}")
        rows.append(value)
    return rows


def sem(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= 1:
        return 0.0
    return float(values.std(ddof=1) / np.sqrt(len(values)))


def summarize_test(frame: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "condition",
        "query_form",
        "prompt_id",
        "reranker_label",
        "reranker_model",
    ]
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_columns, dropna=False):
        values = pd.to_numeric(group["rank_improvement"], errors="coerce")
        rows.append(
            {
                **dict(zip(group_columns, keys)),
                "n": int(values.notna().sum()),
                "mean_rank_improvement": float(values.mean()),
                "median_rank_improvement": float(values.median()),
                "std_rank_improvement": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
                "sem_rank_improvement": sem(values),
                "positive_rate": float((values > 0).mean()),
                "unchanged_rate": float((values == 0).mean()),
                "negative_rate": float((values < 0).mean()),
                "questionable_target_rate": float(
                    pd.to_numeric(
                        group["rewritten_target_flagged_questionable"],
                        errors="coerce",
                    ).mean()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(group_columns).reset_index(drop=True)


def paired_initial_optimized(frame: pd.DataFrame) -> pd.DataFrame:
    long_frame = frame.loc[
        frame["condition"].isin(["test_initial_long", "test_optimized_long"])
    ].copy()
    index_columns = ["prompt_id", "reranker_label", "intent_id"]
    pivot = long_frame.pivot_table(
        index=index_columns,
        columns="condition",
        values="rank_improvement",
        aggfunc="first",
    ).reset_index()
    required = ["test_initial_long", "test_optimized_long"]
    for column in required:
        if column not in pivot:
            pivot[column] = np.nan
    pivot = pivot.dropna(subset=required)
    pivot["optimized_minus_initial"] = (
        pivot["test_optimized_long"] - pivot["test_initial_long"]
    )

    rows: list[dict[str, Any]] = []
    for (prompt_id, reranker), group in pivot.groupby(
        ["prompt_id", "reranker_label"], dropna=False
    ):
        difference = pd.to_numeric(group["optimized_minus_initial"], errors="coerce").dropna()
        if len(difference) and not np.allclose(difference.to_numpy(), 0):
            statistic, p_value = wilcoxon(difference.to_numpy(), zero_method="wilcox")
        else:
            statistic, p_value = 0.0, 1.0
        rows.append(
            {
                "prompt_id": prompt_id,
                "reranker_label": reranker,
                "n": int(len(group)),
                "initial_mean": float(group["test_initial_long"].mean()),
                "optimized_mean": float(group["test_optimized_long"].mean()),
                "mean_difference": float(group["optimized_minus_initial"].mean()),
                "median_difference": float(group["optimized_minus_initial"].median()),
                "improved_pair_rate": float((group["optimized_minus_initial"] > 0).mean()),
                "wilcoxon_statistic": float(statistic),
                "wilcoxon_p_value": float(p_value),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["reranker_label", "prompt_id"]
    ).reset_index(drop=True)


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    normalized = embeddings / np.clip(
        np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12, None
    )
    return 1.0 - normalized @ normalized.T


def mean_pairwise_distance(matrix: np.ndarray) -> float:
    if matrix.shape[0] <= 1:
        return 0.0
    return float(np.mean([matrix[i, j] for i, j in combinations(range(len(matrix)), 2)]))


def centroid_distances(embeddings: np.ndarray) -> np.ndarray:
    normalized = embeddings / np.clip(
        np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12, None
    )
    centroid = normalized.mean(axis=0)
    centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-12)
    return 1.0 - normalized @ centroid


def convergence_analysis(
    prompts: list[dict[str, Any]],
    model_name: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    from sentence_transformers import SentenceTransformer

    prompt_ids = [str(item["prompt_id"]) for item in prompts]
    initial = [str(item["initial_prompt"]) for item in prompts]
    optimized = [str(item["optimized_prompt"]) for item in prompts]
    model = SentenceTransformer(model_name)
    initial_embeddings = np.asarray(
        model.encode(initial, normalize_embeddings=True, convert_to_numpy=True),
        dtype=np.float32,
    )
    optimized_embeddings = np.asarray(
        model.encode(optimized, normalize_embeddings=True, convert_to_numpy=True),
        dtype=np.float32,
    )
    initial_matrix = cosine_distance_matrix(initial_embeddings)
    optimized_matrix = cosine_distance_matrix(optimized_embeddings)
    initial_centroid = centroid_distances(initial_embeddings)
    optimized_centroid = centroid_distances(optimized_embeddings)

    rows = []
    for index, prompt_id in enumerate(prompt_ids):
        rows.append(
            {
                "prompt_id": prompt_id,
                "initial_distance_to_centroid": float(initial_centroid[index]),
                "optimized_distance_to_centroid": float(optimized_centroid[index]),
                "centroid_distance_change": float(
                    optimized_centroid[index] - initial_centroid[index]
                ),
            }
        )
    summary = {
        "embedding_model": model_name,
        "prompt_count": len(prompt_ids),
        "initial_mean_pairwise_cosine_distance": mean_pairwise_distance(initial_matrix),
        "optimized_mean_pairwise_cosine_distance": mean_pairwise_distance(optimized_matrix),
        "pairwise_distance_change": (
            mean_pairwise_distance(optimized_matrix)
            - mean_pairwise_distance(initial_matrix)
        ),
        "initial_mean_centroid_distance": float(initial_centroid.mean()),
        "optimized_mean_centroid_distance": float(optimized_centroid.mean()),
        "centroid_distance_change": float(
            optimized_centroid.mean() - initial_centroid.mean()
        ),
        "convergence_observed": bool(
            mean_pairwise_distance(optimized_matrix)
            < mean_pairwise_distance(initial_matrix)
        ),
    }
    return pd.DataFrame(rows), summary


def contains_feature(text: str, patterns: list[str]) -> bool:
    lowered = str(text).casefold()
    return any(pattern.casefold() in lowered for pattern in patterns)


def feature_matrix(prompts: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in prompts:
        for condition, column in [
            ("initial", "initial_prompt"),
            ("optimized", "optimized_prompt"),
        ]:
            row: dict[str, Any] = {
                "prompt_id": item["prompt_id"],
                "condition": condition,
            }
            text = str(item[column])
            for feature, patterns in FEATURE_PATTERNS.items():
                row[feature] = int(contains_feature(text, patterns))
            rows.append(row)
    return pd.DataFrame(rows)


def feature_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    feature_columns = list(FEATURE_PATTERNS)
    rows = []
    for condition, group in matrix.groupby("condition"):
        for feature in feature_columns:
            rows.append(
                {
                    "condition": condition,
                    "feature": feature,
                    "prompt_count": int(len(group)),
                    "present_count": int(group[feature].sum()),
                    "present_rate": float(group[feature].mean()),
                }
            )
    return pd.DataFrame(rows)


def make_charts(
    test_summary: pd.DataFrame,
    paired: pd.DataFrame,
    convergence: dict[str, Any],
    output_dir: Path,
) -> list[Path]:
    paths: list[Path] = []

    if not paired.empty:
        chart = paired.groupby("prompt_id")[["initial_mean", "optimized_mean"]].mean()
        axis = chart.plot(kind="bar", figsize=(13, 6))
        axis.set_title("Test長文：初期プロンプトと最適化プロンプト")
        axis.set_xlabel("初期プロンプト")
        axis.set_ylabel("平均順位改善量")
        axis.axhline(0, linewidth=1)
        plt.tight_layout()
        path = output_dir / "07_initial_vs_optimized.png"
        plt.savefig(path, dpi=200)
        plt.close()
        paths.append(path)

    optimized = test_summary.loc[
        test_summary["condition"].isin(
            ["test_optimized_long", "test_optimized_short"]
        )
    ]
    if not optimized.empty:
        chart = optimized.groupby(["prompt_id", "query_form"])[
            "mean_rank_improvement"
        ].mean().unstack("query_form")
        axis = chart.plot(kind="bar", figsize=(13, 6))
        axis.set_title("最適化プロンプト：長文Testと短文Test")
        axis.set_xlabel("初期プロンプト")
        axis.set_ylabel("平均順位改善量")
        axis.axhline(0, linewidth=1)
        plt.tight_layout()
        path = output_dir / "08_long_vs_short.png"
        plt.savefig(path, dpi=200)
        plt.close()
        paths.append(path)

    labels = ["初期", "最適化後"]
    values = [
        convergence["initial_mean_pairwise_cosine_distance"],
        convergence["optimized_mean_pairwise_cosine_distance"],
    ]
    plt.figure(figsize=(6, 5))
    plt.bar(labels, values)
    plt.ylabel("平均ペアワイズ・コサイン距離")
    plt.title("15プロンプトの意味的収束")
    plt.tight_layout()
    path = output_dir / "09_prompt_convergence.png"
    plt.savefig(path, dpi=200)
    plt.close()
    paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "05cのTest結果を集計し、初期版と最適化版、長文と短文、"
            "プロンプト収束、10特徴を自動分析する。APIは呼び出さない。"
        )
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    args = parser.parse_args()

    versions_path = args.run_dir / "02_optimization_versions.jsonl"
    prompts_path = args.run_dir / "03_final_prompts.json"
    test_path = args.run_dir / "04_test_results.jsonl"
    cost_path = args.run_dir / "05_cost_ledger.csv"
    run_summary_path = args.run_dir / "06_run_summary.json"

    versions = read_jsonl(versions_path)
    final_prompts = read_json(prompts_path)
    test_rows = read_jsonl(test_path)
    run_summary = read_json(run_summary_path)
    if not isinstance(final_prompts, list) or not final_prompts:
        raise ValueError("final_promptsが空です。")
    if not test_rows:
        raise ValueError("Test結果が空です。")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    test_frame = pd.DataFrame(test_rows)
    test_frame["rank_improvement"] = pd.to_numeric(
        test_frame["rank_improvement"], errors="raise"
    )
    test_summary = summarize_test(test_frame)
    paired = paired_initial_optimized(test_frame)
    convergence_rows, convergence_summary = convergence_analysis(
        final_prompts, args.embedding_model
    )
    features = feature_matrix(final_prompts)
    features_summary = feature_summary(features)

    test_summary.to_csv(
        args.output_dir / "01_test_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    paired.to_csv(
        args.output_dir / "02_initial_vs_optimized_paired.csv",
        index=False,
        encoding="utf-8-sig",
    )
    convergence_rows.to_csv(
        args.output_dir / "03_prompt_convergence.csv",
        index=False,
        encoding="utf-8-sig",
    )
    features.to_csv(
        args.output_dir / "04_prompt_feature_matrix.csv",
        index=False,
        encoding="utf-8-sig",
    )
    features_summary.to_csv(
        args.output_dir / "05_prompt_feature_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    global_condition = (
        test_frame.groupby(["condition", "query_form"])["rank_improvement"]
        .agg(["count", "mean", "median", "std"])
        .reset_index()
        .to_dict(orient="records")
    )
    result_summary = {
        "run_status": run_summary.get("status"),
        "run_mode": run_summary.get("mode"),
        "prompt_count": len(final_prompts),
        "optimization_version_records": len(versions),
        "test_result_rows": len(test_frame),
        "global_condition_summary": global_condition,
        "convergence": convergence_summary,
        "estimated_api_cost_usd": run_summary.get("total_api_cost_usd_estimate"),
        "interpretation_rules": [
            "順位改善量が正なら対象商品の順位が上昇した。",
            "initial_vs_optimizedの正の差はメタ最適化後の改善を示す。",
            "pairwise distance changeが負ならプロンプト間の意味的収束を示す。",
            "短文結果は長文で固定した最適化プロンプトの追加転移評価である。",
        ],
    }
    (args.output_dir / "06_results_summary.json").write_text(
        json.dumps(result_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    charts = make_charts(
        test_summary, paired, convergence_summary, args.output_dir
    )

    with pd.ExcelWriter(
        args.output_dir / "10_results_review.xlsx",
        engine="openpyxl",
    ) as writer:
        test_summary.to_excel(writer, sheet_name="test_summary", index=False)
        paired.to_excel(writer, sheet_name="paired_test", index=False)
        convergence_rows.to_excel(writer, sheet_name="convergence", index=False)
        features.to_excel(writer, sheet_name="feature_matrix", index=False)
        features_summary.to_excel(writer, sheet_name="feature_summary", index=False)
        pd.DataFrame(global_condition).to_excel(
            writer, sheet_name="global_summary", index=False
        )
        if cost_path.exists():
            pd.read_csv(cost_path, encoding="utf-8-sig").to_excel(
                writer, sheet_name="cost_ledger", index=False
            )

    print("06 分析完了")
    print(f"  Test結果: {len(test_frame)}行")
    print(f"  初期・最適化paired: {len(paired)}集計")
    print(
        "  平均ペアワイズ距離: "
        f"{convergence_summary['initial_mean_pairwise_cosine_distance']:.4f} → "
        f"{convergence_summary['optimized_mean_pairwise_cosine_distance']:.4f}"
    )
    print(f"  収束判定: {convergence_summary['convergence_observed']}")
    print(f"  図表: {len(charts)}件")
    print(f"  出力: {args.output_dir}")


if __name__ == "__main__":
    main()
