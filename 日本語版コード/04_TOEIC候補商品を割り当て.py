from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo


DEFAULT_PRODUCTS = Path(
    "日本語版データ/TOEIC/02_商品プール/toeic_product_pool_final.csv"
)
DEFAULT_INTENTS = Path(
    "日本語版データ/TOEIC/03_購入意図/toeic_query_intents_review.xlsx"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/04_候補商品")
DEFAULT_SEED = 42
DEFAULT_CANDIDATE_COUNT = 10
DEFAULT_PRESELECT_COUNT = 30

PRODUCT_REQUIRED_COLUMNS = [
    "product_id",
    "title",
    "category_hint",
    "description_clean",
]
INTENT_REQUIRED_COLUMNS = [
    "intent_id",
    "split",
    "category",
    "short_query_draft",
    "long_query_draft",
    "short_query_final",
    "long_query_final",
    "review_status",
]

POSITIVE_INTENT_COLUMNS = [
    "short_query",
    "long_query",
    "category_label",
    "persona_or_current_score",
    "target_score",
    "primary_need",
    "must_have",
    "nice_to_have",
    "query_focus_hint",
]
PRODUCT_TEXT_COLUMNS = [
    "title",
    "description_clean",
    "author_clean",
    "publisher",
    "series_name",
    "book_format",
    "score_hint",
]


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\u0000-\u001f]", " ", text)
    text = re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠々ー&+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def nonempty(value: Any) -> bool:
    return bool(normalize_text(value))


def char_wb_ngrams(text: str, min_n: int = 3, max_n: int = 5) -> list[str]:
    """scikit-learn の char_wb に近い、単語境界付き文字 n-gram。"""
    normalized = normalize_text(text)
    features: list[str] = []
    for token in normalized.split():
        padded = f" {token} "
        for n in range(min_n, max_n + 1):
            if len(padded) < n:
                continue
            features.extend(
                f"c{n}:{padded[index:index + n]}"
                for index in range(len(padded) - n + 1)
            )
        if re.fullmatch(r"[0-9a-z&+]+", token):
            features.append(f"w:{token}")
    return features


def parse_first_number(value: Any) -> float | None:
    match = re.search(r"\d{3,4}", normalize_text(value))
    if not match:
        return None
    return float(match.group())


def score_affinity(target_score: Any, product_score: Any) -> float:
    target = parse_first_number(target_score)
    product = parse_first_number(product_score)
    if target is None or product is None:
        return 0.0
    difference = abs(target - product)
    return 0.08 * math.exp(-difference / 180.0)


def weighted_join(row: pd.Series, columns: Iterable[str]) -> str:
    parts: list[str] = []
    for column in columns:
        value = str(row.get(column, "") or "").strip()
        if not value:
            continue
        repeat = 1
        if column == "title":
            repeat = 4
        elif column in {"category_label", "must_have", "primary_need"}:
            repeat = 2
        parts.extend([value] * repeat)
    return " ".join(parts)


def load_products(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"商品プールが見つかりません: {path}\n"
            "02_実験用TOEIC商品プールを作成.pyを先に実行してください。"
        )
    frame = pd.read_csv(
        path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    ).fillna("")
    missing = [column for column in PRODUCT_REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise ValueError("商品プールに必要な列がありません: " + ", ".join(missing))
    if frame["product_id"].duplicated().any():
        duplicated = frame.loc[frame["product_id"].duplicated(), "product_id"].tolist()
        raise ValueError(f"product_idが重複しています: {duplicated[:5]}")
    return frame.reset_index(drop=True)


def load_intents(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"購入意図ファイルが見つかりません: {path}\n"
            "03_TOEIC購入意図テンプレートを作成.pyを先に実行してください。"
        )
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        frame = pd.read_excel(path, sheet_name="query_intents", dtype=str).fillna("")
    else:
        frame = pd.read_csv(
            path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
        ).fillna("")
    missing = [column for column in INTENT_REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise ValueError("購入意図に必要な列がありません: " + ", ".join(missing))
    if frame["intent_id"].duplicated().any():
        raise ValueError("intent_idが重複しています。")
    return frame.reset_index(drop=True)


def resolve_queries(intents: pd.DataFrame, require_approved: bool) -> pd.DataFrame:
    resolved = intents.copy()
    resolved["short_query"] = resolved.apply(
        lambda row: row["short_query_final"]
        if nonempty(row["short_query_final"])
        else row["short_query_draft"],
        axis=1,
    )
    resolved["long_query"] = resolved.apply(
        lambda row: row["long_query_final"]
        if nonempty(row["long_query_final"])
        else row["long_query_draft"],
        axis=1,
    )
    resolved["query_source"] = resolved.apply(
        lambda row: (
            "final"
            if nonempty(row["short_query_final"])
            and nonempty(row["long_query_final"])
            else "draft_or_mixed"
        ),
        axis=1,
    )

    empty = resolved.loc[
        ~resolved["short_query"].map(nonempty)
        | ~resolved["long_query"].map(nonempty),
        "intent_id",
    ].tolist()
    if empty:
        raise ValueError(f"短文または長文クエリが空です: {empty[:10]}")

    if require_approved:
        not_approved = resolved.loc[
            resolved["review_status"].ne("承認"), "intent_id"
        ].tolist()
        missing_final = resolved.loc[
            resolved["query_source"].ne("final"), "intent_id"
        ].tolist()
        messages: list[str] = []
        if not_approved:
            messages.append(f"未承認: {not_approved[:10]}")
        if missing_final:
            messages.append(f"final未入力: {missing_final[:10]}")
        if messages:
            raise ValueError(
                "API実験用の確定データとして使えません。\n" + "\n".join(messages)
            )
    return resolved


class TfidfIndex:
    def __init__(self, documents: list[str]) -> None:
        self.document_counts = [Counter(char_wb_ngrams(text)) for text in documents]
        document_frequency: Counter[str] = Counter()
        for counts in self.document_counts:
            document_frequency.update(counts.keys())
        total = len(documents)
        self.idf = {
            term: math.log((1 + total) / (1 + frequency)) + 1.0
            for term, frequency in document_frequency.items()
        }
        self.document_vectors = [self._vectorize_counts(counts) for counts in self.document_counts]
        self.document_norms = [self._norm(vector) for vector in self.document_vectors]

    def _vectorize_counts(self, counts: Counter[str]) -> dict[str, float]:
        return {
            term: (1.0 + math.log(count)) * self.idf.get(term, 0.0)
            for term, count in counts.items()
            if term in self.idf and count > 0
        }

    @staticmethod
    def _norm(vector: dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))

    def similarities(self, query: str) -> np.ndarray:
        query_vector = self._vectorize_counts(Counter(char_wb_ngrams(query)))
        query_norm = self._norm(query_vector)
        if query_norm == 0:
            return np.zeros(len(self.document_vectors), dtype=float)
        scores = np.zeros(len(self.document_vectors), dtype=float)
        for index, document_vector in enumerate(self.document_vectors):
            denominator = query_norm * self.document_norms[index]
            if denominator == 0:
                continue
            if len(query_vector) < len(document_vector):
                dot = sum(
                    value * document_vector.get(term, 0.0)
                    for term, value in query_vector.items()
                )
            else:
                dot = sum(
                    value * query_vector.get(term, 0.0)
                    for term, value in document_vector.items()
                )
            scores[index] = dot / denominator
        return scores


def stable_target_positions(
    intents: pd.DataFrame, candidate_count: int, seed: int
) -> dict[str, int]:
    """論文同様、固定seedで各クエリの対象商品indexを一度だけ引く。"""
    ordered_ids = sorted(intents["intent_id"].astype(str).tolist())
    rng = np.random.default_rng(seed)
    positions = rng.integers(1, candidate_count + 1, size=len(ordered_ids))
    return {intent_id: int(position) for intent_id, position in zip(ordered_ids, positions)}


def candidate_indices_for_intent(
    intent: pd.Series,
    products: pd.DataFrame,
    positive_index: TfidfIndex,
    negative_index: TfidfIndex,
    candidate_count: int,
    preselect_count: int,
) -> tuple[list[int], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    positive_query = weighted_join(intent, POSITIVE_INTENT_COLUMNS)
    negative_query = str(intent.get("avoid", "") or "")
    scores = positive_index.similarities(positive_query)
    negative_scores = (
        negative_index.similarities(negative_query)
        if nonempty(negative_query)
        else np.zeros(len(products), dtype=float)
    )

    adjusted = scores - 0.20 * negative_scores
    target_score = intent.get("target_score", "")
    adjusted += np.array(
        [score_affinity(target_score, value) for value in products.get("score_hint", "")],
        dtype=float,
    )

    same_category = products["category_hint"].eq(str(intent["category"]))
    eligible_indices = np.flatnonzero(same_category.to_numpy())
    if len(eligible_indices) < candidate_count:
        eligible_indices = np.arange(len(products))

    ranked = sorted(
        eligible_indices.tolist(),
        key=lambda index: (-float(adjusted[index]), int(index)),
    )
    preselected = ranked[: max(preselect_count, candidate_count)]

    selected: list[int] = []
    used_description_groups: set[str] = set()
    for index in preselected:
        group = str(products.iloc[index].get("description_group_id", "") or "")
        if group and group in used_description_groups:
            continue
        selected.append(index)
        if group:
            used_description_groups.add(group)
        if len(selected) == candidate_count:
            break

    if len(selected) < candidate_count:
        for index in ranked:
            if index in selected:
                continue
            selected.append(index)
            if len(selected) == candidate_count:
                break

    if len(selected) != candidate_count:
        raise ValueError(
            f"{intent['intent_id']}で候補{candidate_count}件を確保できませんでした。"
        )

    rank_by_index = {index: rank for rank, index in enumerate(ranked, start=1)}
    retrieval_meta = {
        index: {
            "retrieval_rank": rank_by_index[index],
            "retrieval_score": round(float(adjusted[index]), 8),
        }
        for index in selected
    }

    preselection_rows: list[dict[str, Any]] = []
    for retrieval_rank, index in enumerate(preselected[:preselect_count], start=1):
        product = products.iloc[index]
        preselection_rows.append(
            {
                "intent_id": intent["intent_id"],
                "retrieval_rank": retrieval_rank,
                "selected_top10": index in selected,
                "retrieval_score": round(float(adjusted[index]), 8),
                "product_id": product.get("product_id", ""),
                "title": product.get("title", ""),
                "category_hint": product.get("category_hint", ""),
                "score_hint": product.get("score_hint", ""),
            }
        )
    return selected, preselection_rows, retrieval_meta


def build_assignments(
    products: pd.DataFrame,
    intents: pd.DataFrame,
    candidate_count: int,
    preselect_count: int,
    seed: int,
    target_positions: dict[str, int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    product_documents = [
        weighted_join(row, PRODUCT_TEXT_COLUMNS)
        for _, row in products.iterrows()
    ]
    positive_index = TfidfIndex(product_documents)
    negative_index = positive_index
    assignment_rows: list[dict[str, Any]] = []
    preselection_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []

    for _, intent in intents.sort_values("intent_id").iterrows():
        selected, preselection, retrieval_meta = candidate_indices_for_intent(
            intent,
            products,
            positive_index,
            negative_index,
            candidate_count,
            preselect_count,
        )
        preselection_rows.extend(preselection)
        target_position = target_positions[str(intent["intent_id"])]
        target_product = products.iloc[selected[target_position - 1]]
        product_payloads: list[dict[str, Any]] = []
        title_list: list[str] = []

        for candidate_position, product_index in enumerate(selected, start=1):
            product = products.iloc[product_index]
            is_target = candidate_position == target_position
            retrieval_entry = retrieval_meta[product_index]
            assignment = {
                "intent_id": intent["intent_id"],
                "split": intent["split"],
                "category": intent["category"],
                "category_label": intent.get("category_label", ""),
                "intent_review_status": intent["review_status"],
                "query_source": intent["query_source"],
                "short_query": intent["short_query"],
                "long_query": intent["long_query"],
                "candidate_position": candidate_position,
                "target_candidate_position": target_position,
                "is_target": is_target,
                "retrieval_rank": retrieval_entry["retrieval_rank"],
                "retrieval_score": retrieval_entry["retrieval_score"],
                "product_id": product.get("product_id", ""),
                "isbn": product.get("isbn", ""),
                "title": product.get("title", ""),
                "author_clean": product.get("author_clean", ""),
                "price_yen_num": product.get("price_yen_num", ""),
                "category_hint": product.get("category_hint", ""),
                "score_hint": product.get("score_hint", ""),
                "publisher": product.get("publisher", ""),
                "description_clean": product.get("description_clean", ""),
                "description_length_num": product.get("description_length_num", ""),
                "product_url": product.get("product_url", ""),
                "candidate_set_status": "未確認",
                "candidate_review_note": "",
                "target_selection_seed": seed,
                "target_selection_rule": "fixed_seed_uniform_index_1_to_10",
            }
            assignment_rows.append(assignment)
            title_list.append(str(product.get("title", "")))
            product_payloads.append(
                {
                    "candidate_position": candidate_position,
                    "product_id": str(product.get("product_id", "")),
                    "title": str(product.get("title", "")),
                    "author": str(product.get("author_clean", "")),
                    "price_yen": str(product.get("price_yen_num", "")),
                    "category": str(product.get("category_hint", "")),
                    "description": str(product.get("description_clean", "")),
                    "is_target": is_target,
                }
            )

        summary_rows.append(
            {
                "intent_id": intent["intent_id"],
                "split": intent["split"],
                "category": intent["category"],
                "short_query": intent["short_query"],
                "long_query": intent["long_query"],
                "query_source": intent["query_source"],
                "target_candidate_position": target_position,
                "target_product_id": target_product.get("product_id", ""),
                "target_title": target_product.get("title", ""),
                "candidate_titles": "\n".join(
                    f"{index}. {title}" for index, title in enumerate(title_list, start=1)
                ),
                "candidate_set_review": "未確認",
                "review_note": "",
            }
        )
        instances.append(
            {
                "intent_id": str(intent["intent_id"]),
                "split": str(intent["split"]),
                "category": str(intent["category"]),
                "queries": {
                    "short": str(intent["short_query"]),
                    "long": str(intent["long_query"]),
                    "source": str(intent["query_source"]),
                },
                "target_candidate_position": target_position,
                "target_product_id": str(target_product.get("product_id", "")),
                "products": product_payloads,
            }
        )

    assignments = pd.DataFrame(assignment_rows)
    preselection_frame = pd.DataFrame(preselection_rows)
    intent_summary = pd.DataFrame(summary_rows)
    return assignments, preselection_frame, intent_summary, instances


def validate_assignments(assignments: pd.DataFrame, candidate_count: int) -> None:
    counts = assignments.groupby("intent_id").size()
    invalid_counts = counts[counts.ne(candidate_count)]
    if not invalid_counts.empty:
        raise ValueError(f"候補件数が不正です: {invalid_counts.to_dict()}")

    duplicate_pairs = assignments.duplicated(["intent_id", "product_id"])
    if duplicate_pairs.any():
        raise ValueError("同じ購入意図の候補内で商品が重複しています。")

    target_counts = assignments.groupby("intent_id")["is_target"].sum()
    invalid_targets = target_counts[target_counts.ne(1)]
    if not invalid_targets.empty:
        raise ValueError(f"対象商品数が不正です: {invalid_targets.to_dict()}")

    category_mismatch = assignments.loc[
        assignments["category"].ne(assignments["category_hint"])
    ]
    if not category_mismatch.empty:
        examples = category_mismatch[["intent_id", "category", "category_hint"]].head()
        raise ValueError(
            "カテゴリの異なる商品が候補に混ざっています。\n"
            + examples.to_string(index=False)
        )


def style_workbook(path: Path) -> None:
    workbook = load_workbook(path)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    summary = workbook["intent_summary"]
    widths = {
        "A": 14, "B": 12, "C": 14, "D": 46, "E": 80,
        "F": 16, "G": 12, "H": 18, "I": 46, "J": 100,
        "K": 18, "L": 40,
    }
    for column, width in widths.items():
        summary.column_dimensions[column].width = width
    review = DataValidation(type="list", formula1='"未確認,承認,要修正,除外"')
    summary.add_data_validation(review)
    review.add(f"K2:K{summary.max_row}")
    table = Table(displayName="IntentCandidateSummary", ref=summary.dimensions)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    summary.add_table(table)

    assignments = workbook["candidate_assignments"]
    for column in ("A", "B", "C", "D", "E", "F", "G"):
        assignments.column_dimensions[column].width = 16
    assignments.column_dimensions["H"].width = 46
    assignments.column_dimensions["I"].width = 80
    assignments.column_dimensions["U"].width = 48
    assignments.column_dimensions["AC"].width = 100

    preselection = workbook["preselection_top30"]
    preselection.column_dimensions["F"].width = 70

    instructions = workbook["instructions"]
    instructions.column_dimensions["A"].width = 24
    instructions.column_dimensions["B"].width = 110
    workbook.save(path)


def write_outputs(
    output_dir: Path,
    assignments: pd.DataFrame,
    preselection: pd.DataFrame,
    intent_summary: pd.DataFrame,
    instances: list[dict[str, Any]],
    intents: pd.DataFrame,
    products: pd.DataFrame,
    seed: int,
    candidate_count: int,
    preselect_count: int,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assignments_path = output_dir / "toeic_candidate_assignments.csv"
    summary_csv_path = output_dir / "toeic_candidate_intent_summary.csv"
    instances_path = output_dir / "toeic_experiment_instances.json"
    summary_json_path = output_dir / "toeic_candidate_assignment_summary.json"
    review_path = output_dir / "toeic_candidate_assignments_review.xlsx"

    assignments.to_csv(assignments_path, index=False, encoding="utf-8-sig")
    intent_summary.to_csv(summary_csv_path, index=False, encoding="utf-8-sig")
    instances_path.write_text(
        json.dumps(instances, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    digest_source = "\n".join(
        f"{row.intent_id}:{row.product_id}:{row.candidate_position}:{int(row.is_target)}"
        for row in assignments.itertuples()
    )
    summary = {
        "design_version": "query_first_candidate_assignment_v1",
        "intent_count": int(assignments["intent_id"].nunique()),
        "candidate_rows": int(len(assignments)),
        "candidate_count_per_intent": candidate_count,
        "preselect_count": preselect_count,
        "product_pool_count": int(len(products)),
        "target_selection_seed": seed,
        "target_selection_rule": "fixed_seed_uniform_index_1_to_10",
        "query_source_counts": {
            str(key): int(value)
            for key, value in intents["query_source"].value_counts().items()
        },
        "split_counts": {
            str(key): int(value)
            for key, value in intent_summary["split"].value_counts().items()
        },
        "assignment_sha256": hashlib.sha256(
            digest_source.encode("utf-8")
        ).hexdigest(),
        "method": [
            "購入意図のカテゴリと同じカテゴリの商品だけを検索対象にする",
            "タイトルを強く重み付けしたchar_wb TF-IDF（3〜5文字）で候補を順位付けする",
            "avoid条件との類似度を減点する",
            "目標スコアと商品スコアが近い場合に小さな加点を行う",
            "同一説明文の商品が同じ候補集合へ重複しないよう優先的に除く",
            "対象商品indexは先行研究同様に固定seedで一度だけ抽選し全条件で共有する",
        ],
    }
    summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    instructions = pd.DataFrame(
        [
            ["確認対象", "intent_summaryシートを上から確認する。80件×10商品を1行ずつ見る必要はない。"],
            ["候補商品", "購入意図に対して明らかに無関係な商品が混ざっていないか確認する。"],
            ["対象商品", "target_candidate_positionの1商品だけがAPI実験で書き換え対象になる。"],
            ["短文・長文", "同じ候補10件と同じ対象商品を共用する。"],
            ["承認", "問題なければcandidate_set_reviewを「承認」にする。"],
            ["要修正", "問題がある購入意図だけ「要修正」にし、review_noteへ理由を書く。"],
            ["重要", "初期LLM順位を見てから対象商品を選び直さない。"],
            ["再現性", f"対象商品選定seedは{seed}。候補集合と対象商品は全条件で固定する。"],
        ],
        columns=["項目", "説明"],
    )

    with pd.ExcelWriter(review_path, engine="openpyxl") as writer:
        intent_summary.to_excel(writer, sheet_name="intent_summary", index=False)
        assignments.to_excel(writer, sheet_name="candidate_assignments", index=False)
        preselection.to_excel(writer, sheet_name="preselection_top30", index=False)
        instructions.to_excel(writer, sheet_name="instructions", index=False)
    style_workbook(review_path)

    return [
        assignments_path,
        summary_csv_path,
        instances_path,
        summary_json_path,
        review_path,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "確定したTOEIC購入意図ごとに商品プールから候補10件を固定し、"
            "固定seedで書き換え対象商品1件を選ぶ。APIは呼び出さない。"
        )
    )
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--intents", type=Path, default=DEFAULT_INTENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT)
    parser.add_argument("--preselect-count", type=int, default=DEFAULT_PRESELECT_COUNT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    if args.candidate_count <= 1:
        raise ValueError("candidate-countは2以上にしてください。")
    if args.preselect_count < args.candidate_count:
        raise ValueError("preselect-countはcandidate-count以上にしてください。")

    products = load_products(args.products)
    all_intents = resolve_queries(load_intents(args.intents), args.require_approved)
    target_position_source = all_intents.copy()
    intents = all_intents.sort_values("intent_id").reset_index(drop=True)
    if args.limit is not None:
        if args.limit <= 0:
            raise ValueError("limitは1以上にしてください。")
        intents = intents.head(args.limit).copy()

    # limit時も対象商品indexを本番と同じにするため、全intentでseed抽選後に対象行だけ使う。
    full_positions = stable_target_positions(
        target_position_source, args.candidate_count, args.seed
    )
    assignments, preselection, intent_summary, instances = build_assignments(
        products,
        intents,
        args.candidate_count,
        args.preselect_count,
        args.seed,
        full_positions,
    )
    validate_assignments(assignments, args.candidate_count)

    print("候補商品割当の検査が完了しました。")
    print(f"  商品プール: {len(products)}件")
    print(f"  購入意図: {len(intents)}件")
    print(f"  候補商品: {len(assignments)}行（各{args.candidate_count}件）")
    print(f"  対象商品seed: {args.seed}")
    print(
        "  query source: "
        + ", ".join(
            f"{key}={value}"
            for key, value in intents["query_source"].value_counts().items()
        )
    )
    for row in intent_summary.head(3).itertuples():
        print(f"  {row.intent_id}: 対象={row.target_candidate_position}番 {row.target_title}")

    if args.preview:
        print("Preview only. ファイルは変更していません。")
        return

    expected_paths = [
        args.output_dir / "toeic_candidate_assignments.csv",
        args.output_dir / "toeic_candidate_intent_summary.csv",
        args.output_dir / "toeic_experiment_instances.json",
        args.output_dir / "toeic_candidate_assignment_summary.json",
        args.output_dir / "toeic_candidate_assignments_review.xlsx",
    ]
    existing = [path for path in expected_paths if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "出力が既にあります。再作成時は --overwrite を付けてください。\n"
            + "\n".join(str(path) for path in existing)
        )

    paths = write_outputs(
        args.output_dir,
        assignments,
        preselection,
        intent_summary,
        instances,
        intents,
        products,
        args.seed,
        args.candidate_count,
        args.preselect_count,
    )
    print("04の出力を作成しました。")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
