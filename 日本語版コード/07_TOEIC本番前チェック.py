from __future__ import annotations

import argparse
import csv
import json
import os
import string
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INSTANCES = Path(
    "日本語版データ/TOEIC/04_候補商品/toeic_experiment_instances.json"
)
DEFAULT_PROMPTS = Path("日本語版設定/TOEIC_EGEOプロンプト設定.json")
DEFAULT_API_SCRIPT = Path("日本語版コード/05_TOEIC_API実験を実行.py")
DEFAULT_ANALYSIS_SCRIPT = Path("日本語版コード/06_TOEIC実験結果を分析.py")
DEFAULT_OUTPUT_DIR = Path("日本語版データ/TOEIC/07_本番前チェック")

EXPECTED_SPLITS = {"train": 40, "validation": 10, "test": 30}
QUERY_FORMS = ("short", "long")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def format_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name:
            fields.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return fields


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
    severity: str = "error",
) -> None:
    checks.append(
        {
            "name": name,
            "status": "pass" if passed else "fail",
            "severity": severity,
            "detail": detail,
        }
    )


def validate_instances(
    instances: Any,
    checks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    if not isinstance(instances, list):
        add_check(checks, "実験インスタンス形式", False, "JSONの最上位が配列ではありません。")
        return [], Counter(), Counter()

    add_check(
        checks,
        "購入意図数",
        len(instances) == 80,
        f"{len(instances)}件（期待値80件）",
    )

    split_counts = Counter(str(row.get("split", "")) for row in instances)
    add_check(
        checks,
        "Train・Validation・Test件数",
        dict(split_counts) == EXPECTED_SPLITS,
        f"実際={dict(split_counts)} / 期待={EXPECTED_SPLITS}",
    )

    intent_ids = [str(row.get("intent_id", "")) for row in instances]
    add_check(
        checks,
        "intent_idの一意性",
        bool(intent_ids)
        and all(intent_ids)
        and len(intent_ids) == len(set(intent_ids)),
        f"総数={len(intent_ids)} / 一意数={len(set(intent_ids))}",
    )

    candidate_errors: list[str] = []
    target_errors: list[str] = []
    category_errors: list[str] = []
    query_errors: list[str] = []
    source_counts: Counter[str] = Counter()

    for row in instances:
        intent_id = str(row.get("intent_id", "不明"))
        queries = row.get("queries", {})
        short = str(queries.get("short", "")).strip()
        long = str(queries.get("long", "")).strip()
        source_counts[str(queries.get("source", ""))] += 1
        if not short or not long:
            query_errors.append(intent_id)

        products = row.get("products", [])
        positions = sorted(
            int(product.get("candidate_position", 0))
            for product in products
            if str(product.get("candidate_position", "")).strip()
        )
        product_ids = [str(product.get("product_id", "")) for product in products]

        if (
            len(products) != 10
            or positions != list(range(1, 11))
            or len(product_ids) != len(set(product_ids))
            or not all(product_ids)
        ):
            candidate_errors.append(intent_id)

        targets = [product for product in products if bool(product.get("is_target"))]
        target_position = int(row.get("target_candidate_position", 0) or 0)
        target_product_id = str(row.get("target_product_id", ""))
        if (
            len(targets) != 1
            or int(targets[0].get("candidate_position", 0)) != target_position
            or str(targets[0].get("product_id", "")) != target_product_id
        ):
            target_errors.append(intent_id)

        intent_category = str(row.get("category", ""))
        if any(str(product.get("category", "")) != intent_category for product in products):
            category_errors.append(intent_id)

    add_check(
        checks,
        "短文・長文クエリ",
        not query_errors,
        "全件に短文・長文あり"
        if not query_errors
        else f"不足: {query_errors[:10]}",
    )
    add_check(
        checks,
        "候補商品10件",
        not candidate_errors,
        "全件で候補番号1〜10・商品ID重複なし"
        if not candidate_errors
        else f"問題あり: {candidate_errors[:10]}",
    )
    add_check(
        checks,
        "対象商品1件の固定",
        not target_errors,
        "全件で対象位置と商品IDが一致"
        if not target_errors
        else f"問題あり: {target_errors[:10]}",
    )
    add_check(
        checks,
        "カテゴリの一致",
        not category_errors,
        "各購入意図の10商品が同一カテゴリ"
        if not category_errors
        else f"問題あり: {category_errors[:10]}",
    )

    all_final = source_counts and set(source_counts) == {"final"}
    add_check(
        checks,
        "クエリ確定状態",
        bool(all_final),
        f"query_source={dict(source_counts)}。仮データでの開発は可能だが、本番前にfinalへ更新する。",
        severity="warning",
    )
    return instances, split_counts, source_counts


def validate_prompts(config: Any, checks: list[dict[str, Any]]) -> list[str]:
    if not isinstance(config, dict):
        add_check(checks, "プロンプト設定形式", False, "JSONの最上位がオブジェクトではありません。")
        return []

    conditions = config.get("conditions", {})
    enabled = [
        name
        for name, setting in conditions.items()
        if name == "original" or bool(setting.get("enabled", False))
    ]
    add_check(
        checks,
        "基本比較条件",
        all(name in enabled for name in ("original", "en_zero", "ja_zero")),
        f"有効条件={enabled}",
    )

    rewrite_errors: list[str] = []
    for name in ("en_zero", "ja_zero"):
        setting = conditions.get(name, {})
        template = str(setting.get("user_prompt", ""))
        fields = format_fields(template)
        if not template or "description" not in fields or "query" in fields:
            rewrite_errors.append(f"{name}: placeholders={sorted(fields)}")
        try:
            template.format(
                title="商品名",
                description="商品説明",
                author="著者",
                price_yen="2000",
            )
        except Exception as exc:
            rewrite_errors.append(f"{name}: format失敗={exc}")

    add_check(
        checks,
        "query-blind書き換え",
        not rewrite_errors,
        "EN-Zero・JA-Zeroは個別クエリを受け取らず、商品情報だけで整形可能"
        if not rewrite_errors
        else " / ".join(rewrite_errors),
    )

    ranker_template = str(config.get("ranker", {}).get("user_prompt", ""))
    ranker_fields = format_fields(ranker_template)
    ranker_ok = {"query", "products_text"}.issubset(ranker_fields)
    ranker_detail = f"placeholders={sorted(ranker_fields)}"
    try:
        rendered = ranker_template.format(
            query="購入要望",
            products_text="1. 商品A",
        )
        ranker_ok = ranker_ok and '"ranking"' in rendered
    except Exception as exc:
        ranker_ok = False
        ranker_detail += f" / format失敗={exc}"
    add_check(checks, "順位付けプロンプト", ranker_ok, ranker_detail)

    adapted = conditions.get("ja_adapted", {})
    add_check(
        checks,
        "JA-Adapted",
        bool(adapted.get("enabled", False)) and bool(adapted.get("user_prompt", "")),
        "Train・Validation後に確定して有効化する。現在は未確定でも設計上正常。",
        severity="warning",
    )
    return enabled


def validate_api_safety(path: Path, checks: list[dict[str, Any]]) -> None:
    if not path.exists():
        add_check(checks, "05コードの存在", False, f"見つかりません: {path}")
        return

    source = path.read_text(encoding="utf-8")
    required_parts = [
        'parser.add_argument("--execute", action="store_true")',
        "if not args.execute:",
        'if args.stage == "plan":',
        'os.getenv("OPENAI_API_KEY")',
    ]
    missing = [part for part in required_parts if part not in source]
    client_position = source.find("client = OpenAI()")
    guard_position = source.find("if not args.execute:")
    safe_order = (
        guard_position >= 0
        and client_position >= 0
        and guard_position < client_position
    )
    add_check(
        checks,
        "API誤実行防止",
        not missing and safe_order,
        "通常実行はdry-run。APIには--executeと実行stageの両方が必要。"
        if not missing and safe_order
        else f"不足={missing} / guard_before_client={safe_order}",
    )


def validate_analysis_script(path: Path, checks: list[dict[str, Any]]) -> None:
    if not path.exists():
        add_check(checks, "06コードの存在", False, f"見つかりません: {path}")
        return
    source = path.read_text(encoding="utf-8")
    parts = ["--self-test", "rank_improvement", "95"]
    missing = [part for part in parts if part not in source]
    add_check(
        checks,
        "分析自動化コード",
        not missing,
        "架空データself-testと順位改善集計を実装済み"
        if not missing
        else f"確認できなかった文字列={missing}",
    )


def make_call_budget(
    split_counts: Counter[str],
    enabled_conditions: list[str],
) -> list[dict[str, Any]]:
    rewrite_conditions = [
        condition for condition in enabled_conditions if condition != "original"
    ]
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation", "test", "all"):
        count = (
            sum(split_counts.values())
            if split == "all"
            else int(split_counts.get(split, 0))
        )
        rewrite_calls = count * len(rewrite_conditions)
        rank_calls = count * len(enabled_conditions) * len(QUERY_FORMS)
        rows.append(
            {
                "scope": split,
                "intent_count": count,
                "enabled_conditions": len(enabled_conditions),
                "rewrite_calls": rewrite_calls,
                "ranking_calls": rank_calls,
                "total_calls": rewrite_calls + rank_calls,
            }
        )
    return rows


def write_reports(
    output_dir: Path,
    checks: list[dict[str, Any]],
    split_counts: Counter[str],
    source_counts: Counter[str],
    enabled_conditions: list[str],
    call_budget: list[dict[str, Any]],
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    errors = [
        check for check in checks
        if check["status"] == "fail" and check["severity"] == "error"
    ]
    warnings = [
        check for check in checks
        if check["status"] == "fail" and check["severity"] == "warning"
    ]

    report = {
        "created_at": now(),
        "api_called": False,
        "implementation_ready": not errors,
        "paid_experiment_ready": not errors and not warnings,
        "split_counts": dict(split_counts),
        "query_source_counts": dict(source_counts),
        "enabled_conditions": enabled_conditions,
        "checks": checks,
        "blockers_before_paid_experiment": [check["detail"] for check in warnings],
        "call_budget": call_budget,
    }

    json_path = output_dir / "toeic_preflight_report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = output_dir / "toeic_api_call_budget.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(call_budget[0]))
        writer.writeheader()
        writer.writerows(call_budget)

    md_lines = [
        "# TOEIC版E-GEO 本番前チェック",
        "",
        f"- 作成日時: {report['created_at']}",
        "- API呼び出し: なし",
        f"- 実装準備: {'完了' if report['implementation_ready'] else '要修正'}",
        f"- 有料本番準備: {'完了' if report['paid_experiment_ready'] else '未完了'}",
        "",
        "## チェック結果",
        "",
    ]
    for check in checks:
        icon = "✅" if check["status"] == "pass" else (
            "⚠️" if check["severity"] == "warning" else "❌"
        )
        md_lines.append(f"- {icon} **{check['name']}**: {check['detail']}")

    md_lines.extend(
        [
            "",
            "## 現在のAPI予定回数",
            "",
            "|範囲|購入意図|書き換え|順位付け|合計|",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in call_budget:
        md_lines.append(
            f"|{row['scope']}|{row['intent_count']}|"
            f"{row['rewrite_calls']}|{row['ranking_calls']}|{row['total_calls']}|"
        )

    md_lines.extend(
        [
            "",
            "## 次に必要なこと",
            "",
            "1. 03の短文・長文クエリを確定し、review_statusを承認へ変更する。",
            "2. 04を再実行して、確定クエリに対する候補10件を固定する。",
            "3. API実行前に少数パイロットの条件・モデル・上限回数を決める。",
            "4. Train・Validationの結果からJA-Adaptedを確定し、Testには触れずに固定する。",
            "",
            "このレポート作成処理はAPIを呼びません。",
        ]
    )
    md_path = output_dir / "toeic_preflight_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, csv_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "TOEIC版E-GEOのデータ・プロンプト・API安全装置・分析コードを"
            "APIなしで一括点検する。"
        )
    )
    parser.add_argument("--instances", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--api-script", type=Path, default=DEFAULT_API_SCRIPT)
    parser.add_argument("--analysis-script", type=Path, default=DEFAULT_ANALYSIS_SCRIPT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    instances, split_counts, source_counts = validate_instances(
        read_json(args.instances),
        checks,
    )
    enabled_conditions = validate_prompts(read_json(args.prompts), checks)
    validate_api_safety(args.api_script, checks)
    validate_analysis_script(args.analysis_script, checks)

    call_budget = make_call_budget(split_counts, enabled_conditions)
    json_path, csv_path, md_path = write_reports(
        args.output_dir,
        checks,
        split_counts,
        source_counts,
        enabled_conditions,
        call_budget,
    )

    errors = [
        check for check in checks
        if check["status"] == "fail" and check["severity"] == "error"
    ]
    warnings = [
        check for check in checks
        if check["status"] == "fail" and check["severity"] == "warning"
    ]

    print("07 本番前チェックが完了しました。")
    print("  API呼び出し: 0回")
    print(f"  実装上のエラー: {len(errors)}件")
    print(f"  本番前の未完了項目: {len(warnings)}件")
    print(f"  レポート: {md_path}")
    print(f"  JSON: {json_path}")
    print(f"  API予定回数表: {csv_path}")

    if errors:
        print("実装上の修正が必要です。レポートの❌を確認してください。")
        raise SystemExit(1)

    if warnings:
        print("仮データでの開発準備は完了しています。")
        print("有料API実験の前に、レポートの⚠️を解消してください。")
    else:
        print("有料API実験へ進める状態です。")


if __name__ == "__main__":
    main()
