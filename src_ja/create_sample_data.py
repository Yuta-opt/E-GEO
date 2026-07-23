from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data_ja" / "raw"
PROCESSED_DIR = ROOT / "data_ja" / "processed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# すべて研究用の架空データ
products = [
    {
        "product_id": "TOEIC001",
        "title": "はじめてのTOEIC基礎総合",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000001",
        "description": "英語の基礎から学び、TOEIC600点を目指す初心者向け教材です。",
        "features": "中学英文法／基本単語／音声付き／1日30分",
        "target_score": "600",
        "target_part": "全般",
        "level": "初級",
        "price": "1800",
        "source_url": "",
    },
    {
        "product_id": "TOEIC002",
        "title": "TOEIC頻出単語1000",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000002",
        "description": "TOEICで頻出する単語を例文と音声で学習できる単語帳です。",
        "features": "頻出単語1000語／例文／音声付き／復習テスト",
        "target_score": "730",
        "target_part": "単語",
        "level": "初中級",
        "price": "1600",
        "source_url": "",
    },
    {
        "product_id": "TOEIC003",
        "title": "Part 5文法問題集中講義",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000003",
        "description": "Part 5の文法問題を体系的に学習するための問題集です。",
        "features": "文法解説／500問／弱点診断／問題形式別",
        "target_score": "730",
        "target_part": "Part 5",
        "level": "中級",
        "price": "2200",
        "source_url": "",
    },
    {
        "product_id": "TOEIC004",
        "title": "通学時間で学ぶTOEICリスニング",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000004",
        "description": "短時間の音声学習を繰り返してリスニング力を高める教材です。",
        "features": "5分音声／スマートフォン対応／Part 2から4／スクリプト付き",
        "target_score": "700",
        "target_part": "Part 2・3・4",
        "level": "初中級",
        "price": "1900",
        "source_url": "",
    },
    {
        "product_id": "TOEIC005",
        "title": "TOEIC730点突破総合演習",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000005",
        "description": "730点突破に必要な語彙、文法、読解、リスニングを総合的に扱います。",
        "features": "総合対策／模擬試験2回／詳しい解説／学習計画付き",
        "target_score": "730",
        "target_part": "全般",
        "level": "中級",
        "price": "2600",
        "source_url": "",
    },
    {
        "product_id": "TOEIC006",
        "title": "TOEIC公式形式模試3回分",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000006",
        "description": "本番形式の模擬試験を3回分収録した実戦向け教材です。",
        "features": "模試3回／時間配分練習／音声付き／解答解説",
        "target_score": "800",
        "target_part": "全般",
        "level": "中上級",
        "price": "3000",
        "source_url": "",
    },
    {
        "product_id": "TOEIC007",
        "title": "Part 7速読トレーニング",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000007",
        "description": "Part 7の長文を時間内に読み切るための速読教材です。",
        "features": "長文読解／時間計測／設問タイプ別／語彙解説",
        "target_score": "800",
        "target_part": "Part 7",
        "level": "中上級",
        "price": "2100",
        "source_url": "",
    },
    {
        "product_id": "TOEIC008",
        "title": "TOEIC900点精選問題集",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000008",
        "description": "900点を目指す学習者向けに難易度の高い問題を収録しています。",
        "features": "難問中心／上級語彙／詳細解説／全パート対応",
        "target_score": "900",
        "target_part": "全般",
        "level": "上級",
        "price": "2800",
        "source_url": "",
    },
    {
        "product_id": "TOEIC009",
        "title": "2か月完成TOEIC学習プラン",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000009",
        "description": "2か月で学習を完了できるよう、毎日の課題を設定した教材です。",
        "features": "60日計画／毎日の課題／進捗表／総合対策",
        "target_score": "700",
        "target_part": "全般",
        "level": "初中級",
        "price": "2400",
        "source_url": "",
    },
    {
        "product_id": "TOEIC010",
        "title": "やさしいTOEIC英文法入門",
        "author": "研究用サンプル",
        "publisher": "サンプル出版",
        "isbn13": "9780000000010",
        "description": "英文法に苦手意識がある学習者向けに基礎から説明する教材です。",
        "features": "中学英文法／図解／確認問題／初心者向け",
        "target_score": "600",
        "target_part": "Part 5",
        "level": "初級",
        "price": "1700",
        "source_url": "",
    },
]


fieldnames = list(products[0].keys())

with (RAW_DIR / "toeic_products_sample.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(products)


def to_egeo_product(product: dict[str, str]) -> dict:
    """CSV形式の商品をE-GEO形式へ変換する。"""
    feature_list = product["features"].split("／")

    details = {
        "author": product["author"],
        "publisher": product["publisher"],
        "isbn13": product["isbn13"],
        "target_score": product["target_score"],
        "target_part": product["target_part"],
        "level": product["level"],
    }

    return {
        "average_rating": None,
        "description": str([product["description"]]),
        "details": str(details),
        "features": str(feature_list),
        "main_category": "TOEIC教材",
        "price": int(product["price"]),
        "product_id": product["product_id"],
        "rating_number": None,
        "store": product["publisher"],
        "title": product["title"],
    }


egeo_products = [to_egeo_product(product) for product in products]

queries = {
    "JA001": (
        "TOEICを初めて受験します。現在は400点程度で、まず600点を目指しています。"
        "英語の基礎から学べて、1日30分程度で続けられる教材を探しています。"
    ),
    "JA002": (
        "TOEICで730点を目指しています。特にPart 5の文法問題が苦手です。"
        "解説が詳しく、問題演習を多くできる教材を教えてください。"
    ),
    "JA003": (
        "通学時間を使ってTOEICのリスニング対策をしたいです。"
        "短い時間で取り組めて、音声とスクリプトが付いた教材を探しています。"
    ),
}

selected_indices = {
    "JA001": 0,
    "JA002": 2,
    "JA003": 3,
}

test_data = {}
test_selected_products = {}

for number, (query_id, query) in enumerate(queries.items(), start=1):
    test_data[query_id] = {
        "custom_id": number,
        "products": egeo_products,
        "query": query,
    }

    index = selected_indices[query_id]
    test_selected_products[query_id] = {
        "product": egeo_products[index],
        "ind": index,
    }


with (PROCESSED_DIR / "test_data_ja.json").open("w", encoding="utf-8") as file:
    json.dump(test_data, file, ensure_ascii=False, indent=2, allow_nan=False)

with (PROCESSED_DIR / "test_selected_products_ja.json").open(
    "w", encoding="utf-8"
) as file:
    json.dump(
        test_selected_products,
        file,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )

print("作成完了")
print(f"商品数: {len(products)}")
print(f"クエリ数: {len(queries)}")
print(f"CSV: {RAW_DIR / 'toeic_products_sample.csv'}")
print(f"JSON: {PROCESSED_DIR}")