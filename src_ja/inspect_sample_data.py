from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data_ja" / "processed"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


test_data = load_json(PROCESSED_DIR / "test_data_ja.json")
selected_data = load_json(
    PROCESSED_DIR / "test_selected_products_ja.json"
)

# 基本的な整合性確認
assert set(test_data.keys()) == set(selected_data.keys())

for query_id, item in test_data.items():
    products = item["products"]
    selected_index = selected_data[query_id]["ind"]
    selected_product = selected_data[query_id]["product"]

    assert len(products) == 10
    assert 0 <= selected_index < len(products)
    assert (
        products[selected_index]["product_id"]
        == selected_product["product_id"]
    )

    print("=" * 70)
    print(f"クエリID: {query_id}")
    print(f"質問: {item['query']}")
    print()
    print(f"書き換え対象: {selected_index + 1}番目")
    print(
        f"対象教材: {selected_product['title']}"
    )
    print()
    print("候補教材:")

    for index, product in enumerate(products):
        marker = " ← 書き換え対象" if index == selected_index else ""
        print(
            f"{index + 1:>2}. "
            f"{product['title']} "
            f"[{product['product_id']}]"
            f"{marker}"
        )

print("=" * 70)
print("すべてのデータ確認が完了しました。")
print(f"クエリ数: {len(test_data)}")