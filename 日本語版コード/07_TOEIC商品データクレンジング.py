from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_INPUT = Path(
    "日本語版データ/TOEIC/元データ/rakuten_toeic_raw_20260727.xlsx"
)
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/加工済み")
SOURCE_DATE = "2026-07-27"

REQUIRED_COLUMNS = [
    "title_raw",
    "product_url",
    "image_url",
    "isbn_raw",
    "author",
    "publication_info_raw",
    "price_raw",
    "description",
]

SECTION_HEADER_PATTERN = re.compile(
    r"^(?:"
    r"内容紹介(?:[（(].*?[）)])?"
    r"|目次(?:[（(].*?[）)])?"
    r"|著者情報(?:[（(].*?[）)])?"
    r"|出版社からのコメント"
    r"|編集者からのコメント"
    r"|商品説明"
    r")\s*$"
)


def normalize_text(value: Any) -> str:
    """Unicode・空白・HTMLエンティティを統一する。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = html.unescape(str(value))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def fix_toeic_registered_symbol(text: str) -> str:
    """Octoparse出力で登録商標記号が ? になった箇所だけを補正する。"""
    return re.sub(
        r"(?i)\bTOEIC\?\s*(?=L\s*&\s*R)",
        "TOEIC® ",
        text,
    )


def clean_title(value: Any) -> str:
    text = fix_toeic_registered_symbol(normalize_text(value))
    return re.sub(r"\s+", " ", text).strip()


def clean_description(value: Any) -> str:
    """
    商品説明を整形し、重複しやすいJPRO・BOOKデータベース・目次等は
    最初の「内容紹介」セクションより後を切り落とす。
    """
    text = normalize_text(value)
    if not text:
        return ""

    # HTMLタグらしい記述だけを削除する。
    text = re.sub(r"<[^<>]{1,100}>", " ", text)
    text = fix_toeic_registered_symbol(text)

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    # 先頭の内容紹介見出しを削除する。
    if lines and SECTION_HEADER_PATTERN.match(lines[0]):
        lines = lines[1:]

    first_section: list[str] = []
    for line in lines:
        if first_section and SECTION_HEADER_PATTERN.match(line):
            break
        first_section.append(line)

    cleaned = " ".join(first_section)
    cleaned = re.sub(r"更新日[:：]\s*\d{4}年\d{1,2}月\d{1,2}日", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_isbn(value: Any) -> str:
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits if len(digits) in {10, 13} else ""


def extract_price_yen(value: Any) -> int | None:
    match = re.search(r"[\d,]+", normalize_text(value))
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


def extract_rakuten_id(url: str) -> str:
    match = re.search(r"/rb/(\d+)/", url)
    return match.group(1) if match else ""


def parse_publication_info(value: Any) -> dict[str, str]:
    text = normalize_text(value)
    result = {
        "publication_info_clean": text,
        "release_info": "",
        "publisher": "",
        "book_format": "",
        "series_name": "",
    }
    if not text:
        return result

    if text.startswith("シリーズ名:"):
        result["series_name"] = text.split(":", 1)[1].strip()
        return result
    if text.startswith("シリーズ名："):
        result["series_name"] = text.split("：", 1)[1].strip()
        return result

    parts = [part.strip() for part in re.split(r"\s*／\s*", text) if part.strip()]
    if parts and "発売" in parts[0]:
        result["release_info"] = parts.pop(0)

    if not parts:
        return result

    # 電子書籍は「カテゴリ／出版社／対応端末」の形を取ることがある。
    device_index = next(
        (i for i, part in enumerate(parts) if part.startswith("対応端末")),
        None,
    )
    if device_index is not None:
        if device_index >= 1:
            result["publisher"] = parts[device_index - 1]
        result["book_format"] = parts[device_index]
        return result

    if len(parts) == 1:
        result["publisher"] = parts[0]
    else:
        result["publisher"] = parts[-2]
        result["book_format"] = parts[-1]
    return result


def is_ebook(title: str, publication_info: str) -> bool:
    return (
        "[電子書籍版]" in title
        or "対応端末:" in publication_info
        or "対応端末：" in publication_info
    )


def is_toeic_related(title: str) -> bool:
    lowered = title.casefold()
    return "toeic" in lowered or "トーイック" in lowered


def infer_category(title: str) -> str:
    """タイトルだけから、後工程の候補集合づくり用の粗いカテゴリを付与する。"""
    t = title.casefold()
    compact = re.sub(r"\s+", "", t)

    if "bridge" in t:
        return "bridge"
    if any(k in t for k in ["speaking", "writing", "スピーキング", "ライティング"]):
        return "speaking_writing"
    if any(
        k in t
        for k in ["模試", "問題集", "予想問題", "実戦テスト", "完全模擬", "厳選700問"]
    ):
        return "mock_test"
    if any(
        k in t
        for k in [
            "単語",
            "英単語",
            "語彙",
            "フレーズ",
            "熟語",
            "キクタン",
            "ボキャブラリー",
            "センテンス",
        ]
    ):
        return "vocabulary"
    if any(k in compact for k in ["part5", "part6", "パート5", "パート6"]) or any(
        k in t for k in ["文法", "穴埋め", "千本ノック", "1000問", "ひっかけ問題"]
    ):
        return "grammar"
    if any(
        k in compact
        for k in ["part1", "part2", "part3", "part4", "パート1", "パート2", "パート3", "パート4"]
    ) or any(k in t for k in ["リスニング", "聞こえる", "速聴", "音読", "応答問題"]):
        return "listening"
    if any(k in compact for k in ["part7", "パート7"]) or any(
        k in t for k in ["リーディング", "読解", "速読", "読める", "言い換え"]
    ):
        return "reading"
    if (
        re.search(r"(?<!\d)([2-9]\d{2}|990)\s*点", title)
        or any(
            k in t
            for k in [
                "全パート",
                "総合対策",
                "総合攻略",
                "入門",
                "はじめて",
                "初心者",
                "攻略",
                "対策",
                "教科書",
                "講義",
                "勉強",
                "学習法",
                "カリキュラム",
                "奪取",
                "直前",
                "スコアアップ",
                "戦略",
                "近道",
                "all in one",
                "金のパッケージ",
                "神ポイント",
                "ドリル",
                "満点を取る",
            ]
        )
        or any(k in compact for k in ["500+", "650+", "800+"])
    ):
        return "general"
    return "other"


def infer_score_hint(title: str) -> str:
    matches = re.findall(
        r"(?<!\d)([2-9]\d{2}|990)\s*(?=点|[+＋]|レベル|score)",
        title,
        flags=re.IGNORECASE,
    )
    unique = list(dict.fromkeys(matches))
    return ",".join(unique)


def append_reason(current: str, reason: str) -> str:
    return reason if not current else f"{current};{reason}"


def build_dataset(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = work.fillna("")
    work.insert(0, "source_row", range(2, len(work) + 2))
    work["source_date"] = SOURCE_DATE

    work["title"] = work["title_raw"].map(clean_title)
    work["author_clean"] = work["author"].map(
        lambda x: re.sub(r"\s+", " ", normalize_text(x)).strip()
    )
    work["product_url"] = work["product_url"].map(normalize_text)
    work["image_url"] = work["image_url"].map(normalize_text)
    work["isbn"] = work["isbn_raw"].map(extract_isbn)
    work["rakuten_product_id"] = work["product_url"].map(extract_rakuten_id)
    work["product_id"] = work.apply(
        lambda row: row["isbn"]
        if row["isbn"]
        else f"rakuten_{row['rakuten_product_id']}",
        axis=1,
    )
    work["price_yen"] = work["price_raw"].map(extract_price_yen)

    publication = work["publication_info_raw"].map(parse_publication_info)
    publication_df = pd.DataFrame(publication.tolist(), index=work.index)
    work = pd.concat([work, publication_df], axis=1)

    work["description_clean"] = work["description"].map(clean_description)
    work["description_length"] = work["description_clean"].str.len()
    work["category_hint"] = work["title"].map(infer_category)
    work["score_hint"] = work["title"].map(infer_score_hint)
    work["media_type"] = work.apply(
        lambda row: "ebook"
        if is_ebook(row["title"], row["publication_info_clean"])
        else "paper_or_unknown",
        axis=1,
    )

    work["exclusion_reasons"] = ""
    work["review_reasons"] = ""

    for idx, row in work.iterrows():
        exclusion = ""
        review = ""

        if not row["title"]:
            exclusion = append_reason(exclusion, "missing_title")
        if not row["isbn"]:
            exclusion = append_reason(exclusion, "invalid_isbn")
        if not row["description_clean"]:
            exclusion = append_reason(exclusion, "missing_description")
        if row["media_type"] == "ebook":
            exclusion = append_reason(exclusion, "ebook")
        if "[雑誌]" in row["title"] or row["book_format"] == "雑誌":
            exclusion = append_reason(exclusion, "magazine")
        if row["title"] and not is_toeic_related(row["title"]):
            exclusion = append_reason(exclusion, "non_toeic_title")
        if not row["product_url"]:
            exclusion = append_reason(exclusion, "missing_product_url")
        if row["price_yen"] is None:
            review = append_reason(review, "price_missing")
        if not row["author_clean"]:
            review = append_reason(review, "author_missing")
        if 0 < row["description_length"] < 100:
            review = append_reason(review, "description_short_lt_100")
        if row["description_length"] > 2000:
            review = append_reason(review, "description_long_gt_2000")
        if row["series_name"] and not row["release_info"]:
            review = append_reason(review, "publication_series_only")
        if row["category_hint"] == "other":
            review = append_reason(review, "category_other")
        if "謝恩価格本" in row["title"] or "バーゲン本" in row["title"]:
            review = append_reason(review, "discount_edition")

        work.at[idx, "exclusion_reasons"] = exclusion
        work.at[idx, "review_reasons"] = review

    duplicate_isbn = work["isbn"].ne("") & work.duplicated("isbn", keep="first")
    duplicate_url = work["product_url"].ne("") & work.duplicated(
        "product_url", keep="first"
    )
    for idx in work.index[duplicate_isbn]:
        work.at[idx, "exclusion_reasons"] = append_reason(
            work.at[idx, "exclusion_reasons"], "duplicate_isbn"
        )
    for idx in work.index[duplicate_url]:
        work.at[idx, "exclusion_reasons"] = append_reason(
            work.at[idx, "exclusion_reasons"], "duplicate_product_url"
        )

    work["is_excluded"] = work["exclusion_reasons"].ne("")
    work["needs_review"] = work["review_reasons"].ne("")

    output_columns = [
        "source_row",
        "source_date",
        "product_id",
        "rakuten_product_id",
        "isbn",
        "title",
        "author_clean",
        "price_yen",
        "media_type",
        "category_hint",
        "score_hint",
        "release_info",
        "publisher",
        "book_format",
        "series_name",
        "description_clean",
        "description_length",
        "product_url",
        "image_url",
        "needs_review",
        "review_reasons",
        "is_excluded",
        "exclusion_reasons",
        "title_raw",
        "isbn_raw",
        "author",
        "publication_info_raw",
        "price_raw",
        "description",
    ]
    return work[output_columns]


def count_reasons(series: pd.Series) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in series:
        for reason in str(value).split(";"):
            if reason:
                counter[reason] += 1
    return dict(sorted(counter.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="楽天ブックスのTOEIC商品データをクレンジングする。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"入力Excel。既定値: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"出力先。既定値: {DEFAULT_OUTPUT_DIR}",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(
            f"入力ファイルが見つかりません: {args.input}\n"
            "元Excelのファイル名と配置場所を確認してください。"
        )

    try:
        raw = pd.read_excel(args.input, dtype=str, engine="openpyxl")
    except ImportError as exc:
        raise RuntimeError(
            "Excel読込に openpyxl が必要です。"
            " `uv add openpyxl` を実行してから再実行してください。"
        ) from exc

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing_columns:
        raise ValueError(
            "入力Excelに必要な列がありません: " + ", ".join(missing_columns)
        )

    cleaned_all = build_dataset(raw[REQUIRED_COLUMNS])
    included = cleaned_all.loc[~cleaned_all["is_excluded"]].copy()
    excluded = cleaned_all.loc[cleaned_all["is_excluded"]].copy()
    review = included.loc[included["needs_review"]].copy()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    included_path = args.output_dir / "toeic_products_clean.csv"
    excluded_path = args.output_dir / "toeic_products_excluded.csv"
    review_path = args.output_dir / "toeic_products_review.csv"
    summary_path = args.output_dir / "toeic_cleaning_summary.json"

    included.to_csv(included_path, index=False, encoding="utf-8-sig")
    excluded.to_csv(excluded_path, index=False, encoding="utf-8-sig")
    review.to_csv(review_path, index=False, encoding="utf-8-sig")

    summary = {
        "source_file": str(args.input),
        "source_date": SOURCE_DATE,
        "raw_rows": int(len(cleaned_all)),
        "included_rows": int(len(included)),
        "excluded_rows": int(len(excluded)),
        "review_rows": int(len(review)),
        "description_available_raw": int(
            cleaned_all["description_clean"].ne("").sum()
        ),
        "description_length": {
            "min_included": int(included["description_length"].min())
            if len(included)
            else 0,
            "median_included": float(included["description_length"].median())
            if len(included)
            else 0,
            "max_included": int(included["description_length"].max())
            if len(included)
            else 0,
        },
        "category_counts_included": {
            str(k): int(v)
            for k, v in included["category_hint"]
            .value_counts()
            .sort_index()
            .items()
        },
        "exclusion_reason_counts": count_reasons(
            excluded["exclusion_reasons"]
        ),
        "review_reason_counts": count_reasons(review["review_reasons"]),
        "notes": [
            "短い説明文は自動除外せず review 対象とした。",
            "JPRO・BOOKデータベース・目次等の重複セクションは最初の内容紹介以降を切り落とした。",
            "電子書籍、説明欠損、TOEIC非関連タイトルは自動除外した。",
        ],
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("TOEIC商品データのクレンジングが完了しました。")
    print(f"  元データ: {len(cleaned_all)}件")
    print(f"  採用候補: {len(included)}件")
    print(f"  除外: {len(excluded)}件")
    print(f"  要確認: {len(review)}件")
    print(f"  出力: {included_path}")
    print(f"        {excluded_path}")
    print(f"        {review_path}")
    print(f"        {summary_path}")


if __name__ == "__main__":
    main()
