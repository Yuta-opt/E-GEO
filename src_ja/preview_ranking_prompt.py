from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DATA_DIR = ROOT / "data_ja" / "processed"

# 原版E-GEOのutils.pyを利用する
sys.path.insert(0, str(SRC_DIR))

from utils import format_products  # noqa: E402


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


test_data = load_json(DATA_DIR / "test_data_ja.json")

# 最初のクエリを取得
query_id = next(iter(test_data))
query_data = test_data[query_id]

query = query_data["query"]
products = query_data["products"]

# E-GEOと同じ形式で候補10商品を番号付きにする
formatted_products = format_products(products)

ranking_prompt = f"""
あなたは、TOEIC教材を推薦するランキングシステムです。

ユーザーの条件に最も合う順番で、候補教材10冊を並べてください。

【ユーザーの質問】
{query}

【候補教材】
{formatted_products}

【指示】
1. 10冊すべてを、ユーザーの条件に合う順に並べてください。
2. 同じ教材番号を重複させないでください。
3. 1から10までの教材番号を、すべて1回ずつ使用してください。
4. 元の商品情報にない、誇張表現や不自然な主張がある教材は
   questionable_productsに入れてください。
5. 説明や理由は書かず、JSONだけを返してください。

【出力形式】
{{
  "ranking": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  "questionable_products": []
}}
""".strip()

output_path = DATA_DIR / "ranking_prompt_preview.txt"

with output_path.open("w", encoding="utf-8") as file:
    file.write(ranking_prompt)

print("=" * 70)
print(f"クエリID: {query_id}")
print(f"商品数: {len(products)}")
print(f"保存先: {output_path}")
print("=" * 70)
print(ranking_prompt)