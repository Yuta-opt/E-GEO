from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CODE_MOVES = [
    ("日本語版コード/07_TOEIC商品データクレンジング.py", "日本語版コード/01_楽天TOEIC商品データをクレンジング.py"),
    ("日本語版コード/08_TOEIC商品プール再構成.py", "日本語版コード/02_実験用TOEIC商品プールを作成.py"),
    ("日本語版コード/10_TOEIC購入意図テンプレート作成.py", "日本語版コード/03_TOEIC購入意図テンプレートを作成.py"),
    ("日本語版コード/08_TOEIC商品プール作成.py", "日本語版コード/99_旧版/旧_商品プール200件を作成.py"),
    ("日本語版コード/09_TOEIC商品プール最終化.py", "日本語版コード/99_旧版/旧_商品プールを最終化.py"),
]

ACTIVE_FILES = {
    "clean": REPO_ROOT / "日本語版コード/01_楽天TOEIC商品データをクレンジング.py",
    "pool": REPO_ROOT / "日本語版コード/02_実験用TOEIC商品プールを作成.py",
    "intent": REPO_ROOT / "日本語版コード/03_TOEIC購入意図テンプレートを作成.py",
}


def log(message: str) -> None:
    print(message)


def ensure_dir(path: Path, preview: bool) -> None:
    if path.exists():
        return
    log(f"[{'PREVIEW' if preview else 'CREATE'}] directory: {path.relative_to(REPO_ROOT)}")
    if not preview:
        path.mkdir(parents=True, exist_ok=True)


def move_file(source: Path, destination: Path, preview: bool) -> None:
    if not source.exists():
        if destination.exists():
            log(f"[OK] already organized: {destination.relative_to(REPO_ROOT)}")
        else:
            log(f"[SKIP] missing: {source.relative_to(REPO_ROOT)}")
        return
    if destination.exists():
        log(f"[SKIP] destination exists; source retained: {destination.relative_to(REPO_ROOT)}")
        return
    ensure_dir(destination.parent, preview)
    log(f"[{'PREVIEW' if preview else 'MOVE'}] {source.relative_to(REPO_ROOT)} -> {destination.relative_to(REPO_ROOT)}")
    if not preview:
        shutil.move(str(source), str(destination))


def merge_directory(source: Path, destination: Path, preview: bool) -> None:
    if not source.exists():
        return
    ensure_dir(destination, preview)
    for item in list(source.iterdir()):
        target = destination / item.name
        if item.is_dir():
            merge_directory(item, target, preview)
        else:
            move_file(item, target, preview)
    if not preview and source.exists() and not any(source.iterdir()):
        source.rmdir()


def replace_text(path: Path, replacements: list[tuple[str, str]], preview: bool) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig")
    updated = text
    for old, new in replacements:
        updated = updated.replace(old, new)
    if updated == text:
        return
    log(f"[{'PREVIEW' if preview else 'UPDATE'}] {path.relative_to(REPO_ROOT)}")
    if not preview:
        path.write_text(updated, encoding="utf-8", newline="\n")


def prepend_archive_notice(path: Path, preview: bool) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig")
    notice = "# 旧方式の保存用コードです。現在の実験では実行しません。\n\n"
    if text.startswith(notice.strip()):
        return
    log(f"[{'PREVIEW' if preview else 'UPDATE'}] archive notice: {path.relative_to(REPO_ROOT)}")
    if not preview:
        path.write_text(notice + text, encoding="utf-8", newline="\n")


def organize_code(preview: bool) -> None:
    log("\n=== 1. Organize Python files ===")
    for source_rel, destination_rel in CODE_MOVES:
        move_file(REPO_ROOT / source_rel, REPO_ROOT / destination_rel, preview)
    prepend_archive_notice(REPO_ROOT / "日本語版コード/99_旧版/旧_商品プール200件を作成.py", preview)
    prepend_archive_notice(REPO_ROOT / "日本語版コード/99_旧版/旧_商品プールを最終化.py", preview)


def organize_data(preview: bool) -> None:
    log("\n=== 2. Organize local data files ===")
    root = REPO_ROOT / "日本語版データ/TOEIC"
    ensure_dir(root, preview)
    merge_directory(root / "元データ", root / "00_元データ", preview)
    merge_directory(root / "加工済み", root / "01_クレンジング済み", preview)

    pool = root / "02_商品プール"
    intents = root / "03_購入意図"
    api = root / "04_API実験"
    analysis = root / "05_分析結果"
    archive = root / "99_旧版"
    old_outputs = archive / "旧実験データ"
    for directory in (pool, intents, api, analysis, archive):
        ensure_dir(directory, preview)

    old_experiment = root / "実験データ"
    if old_experiment.exists():
        pool_names = {
            "toeic_product_pool_final.csv",
            "toeic_product_pool_removed.csv",
            "toeic_product_pool_final_summary.json",
            "toeic_product_pool_final_review.xlsx",
        }
        for item in list(old_experiment.iterdir()):
            if item.is_dir():
                destination = old_outputs / item.name
            elif item.name.startswith("toeic_purchase_intents_"):
                destination = intents / item.name
            elif item.name in pool_names or item.name.startswith("toeic_product_pool_revised_"):
                destination = pool / item.name
            else:
                destination = old_outputs / item.name
            move_file(item, destination, preview)
        if not preview and old_experiment.exists() and not any(old_experiment.iterdir()):
            old_experiment.rmdir()

    merge_directory(REPO_ROOT / "日本語版データ/実験結果", analysis, preview)
    for directory in (api, analysis, archive):
        keep = directory / ".gitkeep"
        if not keep.exists():
            log(f"[{'PREVIEW' if preview else 'CREATE'}] {keep.relative_to(REPO_ROOT)}")
            if not preview:
                ensure_dir(directory, False)
                keep.touch()


def update_paths_and_docs(preview: bool) -> None:
    log("\n=== 3. Update paths and documentation ===")
    replace_text(ACTIVE_FILES["clean"], [
        ("日本語版データ/TOEIC/元データ/rakuten_toeic_raw_20260727.xlsx", "日本語版データ/TOEIC/00_元データ/rakuten_toeic_raw_20260727.xlsx"),
        ("日本語版データ/TOEIC/加工済み", "日本語版データ/TOEIC/01_クレンジング済み"),
    ], preview)
    replace_text(ACTIVE_FILES["pool"], [
        ("日本語版データ/TOEIC/加工済み", "日本語版データ/TOEIC/01_クレンジング済み"),
        ("日本語版データ/TOEIC/実験データ", "日本語版データ/TOEIC/02_商品プール"),
        ("07_TOEIC商品データクレンジング.py", "01_楽天TOEIC商品データをクレンジング.py"),
    ], preview)
    replace_text(ACTIVE_FILES["intent"], [
        ("日本語版データ/TOEIC/実験データ/toeic_product_pool_final.csv", "日本語版データ/TOEIC/02_商品プール/toeic_product_pool_final.csv"),
        ("日本語版データ/TOEIC/実験データ", "日本語版データ/TOEIC/03_購入意図"),
    ], preview)

    doc_replacements = [
        ("07_TOEIC商品データクレンジング.py", "01_楽天TOEIC商品データをクレンジング.py"),
        ("08_TOEIC商品プール再構成.py", "02_実験用TOEIC商品プールを作成.py"),
        ("10_TOEIC購入意図テンプレート作成.py", "03_TOEIC購入意図テンプレートを作成.py"),
        ("日本語版データ/TOEIC/元データ", "日本語版データ/TOEIC/00_元データ"),
        ("日本語版データ/TOEIC/加工済み", "日本語版データ/TOEIC/01_クレンジング済み"),
        ("日本語版データ/TOEIC/実験データ/toeic_product_pool", "日本語版データ/TOEIC/02_商品プール/toeic_product_pool"),
        ("日本語版データ/TOEIC/実験データ/toeic_purchase_intents", "日本語版データ/TOEIC/03_購入意図/toeic_purchase_intents"),
    ]
    docs = list((REPO_ROOT / "日本語版ドキュメント").rglob("*.md"))
    root_readme = REPO_ROOT / "README_日本語.md"
    if root_readme.exists():
        docs.append(root_readme)
    for path in docs:
        replace_text(path, doc_replacements, preview)


def update_gitignore(preview: bool) -> None:
    path = REPO_ROOT / ".gitignore"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8-sig")
    marker = "# Rakuten Books TOEIC local datasets and experiment outputs"
    before = text.split(marker, 1)[0].rstrip() if marker in text else text.rstrip()
    block = """
# Rakuten Books TOEIC local datasets and experiment outputs
日本語版データ/TOEIC/00_元データ/*
日本語版データ/TOEIC/01_クレンジング済み/*
日本語版データ/TOEIC/02_商品プール/*
日本語版データ/TOEIC/03_購入意図/*
日本語版データ/TOEIC/04_API実験/*
日本語版データ/TOEIC/05_分析結果/*
日本語版データ/TOEIC/99_旧版/*
!日本語版データ/TOEIC/04_API実験/.gitkeep
!日本語版データ/TOEIC/05_分析結果/.gitkeep
!日本語版データ/TOEIC/99_旧版/.gitkeep
""".strip()
    updated = before + "\n\n" + block + "\n"
    if updated != text:
        log(f"[{'PREVIEW' if preview else 'UPDATE'}] .gitignore")
        if not preview:
            path.write_text(updated, encoding="utf-8", newline="\n")


def write_readmes(preview: bool) -> None:
    code_readme = """# 日本語版コード

現在使うPythonファイルは、上から順番に実行します。

| 順番 | ファイル | 何をするか | 主な出力先 |
|---:|---|---|---|
| 1 | `01_楽天TOEIC商品データをクレンジング.py` | 元Excelを整形し、明らかに使えない商品を除外する | `01_クレンジング済み/` |
| 2 | `02_実験用TOEIC商品プールを作成.py` | 価格欠損と明確な同一商品だけを除き、商品プールを作る | `02_商品プール/` |
| 3 | `03_TOEIC購入意図テンプレートを作成.py` | 対象商品を分割し、購入意図記入用テンプレートを作る | `03_購入意図/` |

`99_旧版/`は以前の条件を再現する保存用コードです。現在の研究では実行しません。
"""
    data_readme = """# TOEIC研究データ

| フォルダ | 内容 |
|---|---|
| `00_元データ/` | Octoparseで取得した原本。直接編集しない |
| `01_クレンジング済み/` | 明らかに使えない商品を除外・整形したデータ |
| `02_商品プール/` | 実験対象候補と除外記録 |
| `03_購入意図/` | 短文・長文クエリのテンプレート |
| `04_API実験/` | 元順位、リライト、再順位、APIログ |
| `05_分析結果/` | 集計、統計検定、グラフ、ポスター用出力 |
| `99_旧版/` | 現在使わない途中生成物・旧方式の出力 |

CSV・Excel・API結果はGitHubへアップロードしません。
"""
    for path, content in [
        (REPO_ROOT / "日本語版コード/README.md", code_readme),
        (REPO_ROOT / "日本語版データ/TOEIC/README.md", data_readme),
    ]:
        log(f"[{'PREVIEW' if preview else 'WRITE'}] {path.relative_to(REPO_ROOT)}")
        if not preview:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize Japanese TOEIC research files safely.")
    parser.add_argument("--preview", action="store_true", help="Show planned changes without modifying files.")
    args = parser.parse_args()

    organize_code(args.preview)
    organize_data(args.preview)
    update_paths_and_docs(args.preview)
    update_gitignore(args.preview)
    write_readmes(args.preview)

    print("\n=== Result ===")
    if args.preview:
        print("Preview only. No files were changed.")
    else:
        print("Organization completed.")
        subprocess.run(["git", "status", "--short"], cwd=REPO_ROOT, check=False)


if __name__ == "__main__":
    main()
