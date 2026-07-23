from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DATA_DIR = ROOT / "data_ja" / "processed"
DEFAULT_INPUT = DATA_DIR / "test_data_ja.json"
DEFAULT_OUTPUT = DATA_DIR / "initial_ranking_ja.json"

sys.path.insert(0, str(SRC_DIR))

from utils import extract_json_object, format_products  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)


def build_ranking_prompt(query: str, products: list[dict[str, Any]]) -> str:
    formatted_products = format_products(products)
    return f"""
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


def call_llm(provider: str, model: str, system_prompt: str, user_prompt: str) -> str:
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        endpoint = "https://api.openai.com/v1/chat/completions"
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
    else:
        raise ValueError(f"unsupported provider: {provider}")

    if not api_key:
        raise RuntimeError(
            f"API key not found. Set {provider.upper()}_API_KEY or OPENROUTER_API_KEY before running."
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 1000,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com"
        headers["X-Title"] = "E-GEO Japanese sample"

    req = request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    with request.urlopen(req, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"unexpected API response: {body}") from exc


def parse_result(text: str) -> dict[str, Any]:
    parsed = extract_json_object(text)
    if parsed is None:
        raise ValueError("LLM response did not contain valid JSON.")

    ranking = parsed.get("ranking")
    if not isinstance(ranking, list):
        raise ValueError("ranking field is missing or invalid.")

    ranking_numbers = [int(item) for item in ranking]
    if sorted(ranking_numbers) != list(range(1, 11)):
        raise ValueError("ranking must contain each number from 1 to 10 exactly once.")

    questionable = parsed.get("questionable_products") or []
    if not isinstance(questionable, list):
        raise ValueError("questionable_products must be a list.")

    return {
        "ranking": ranking_numbers,
        "questionable_products": [int(item) for item in questionable],
    }


def confirm_execution() -> bool:
    answer = input(
        "APIを実際に呼び出して課金が発生します。続けますか？ [y/N]: "
    ).strip().lower()
    return answer in {"y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="日本語TOEIC教材データの初期順位を取得するスクリプト"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="入力JSONのパス (default: data_ja/processed/test_data_ja.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力JSONのパス (default: data_ja/processed/initial_ranking_ja.json)",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "openrouter"],
        help="API provider",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="モデル名 (default: gpt-4.1-mini)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="APIを実際に呼び出してランキングを取得する",
    )
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output

    if not input_path.exists():
        raise FileNotFoundError(f"input file not found: {input_path}")

    test_data = load_json(input_path)

    if not args.execute:
        print("dry-run mode: APIは呼び出しません。実際に取得するには --execute を指定してください。")
        for query_id in test_data:
            print(f"- {query_id}: preview prompt will be generated")
        return 0

    print("API実行前に確認します。")
    if not confirm_execution():
        print("キャンセルしました。")
        return 0

    system_prompt = (
        "あなたは商品ランキングを返すJSON生成AIです。"
        "ユーザーの要望に合う順序で、候補商品の番号を並べてください。"
    )

    results: dict[str, Any] = {}
    for query_id, query_data in test_data.items():
        query = query_data["query"]
        products = query_data["products"]
        user_prompt = build_ranking_prompt(query, products)
        response_text = call_llm(args.provider, args.model, system_prompt, user_prompt)
        ranking_result = parse_result(response_text)
        results[query_id] = {"results": ranking_result}
        print(f"[{query_id}] 取得しました")

    write_json(output_path, results)
    print(f"保存しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
