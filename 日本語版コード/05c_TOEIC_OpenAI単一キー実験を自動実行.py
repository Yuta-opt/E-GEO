from __future__ import annotations

import runpy
from pathlib import Path


INTERNAL_RUNNER = Path(__file__).with_name(
    "05c_TOEICメタ最適化API実験を自動実行.py"
)


if __name__ == "__main__":
    # OpenAIだけを使う実行入口。
    # 実験ロジック本体は既存の内部ランナーへ集約し、二重実装を避ける。
    runpy.run_path(str(INTERNAL_RUNNER), run_name="__main__")
