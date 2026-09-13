"""baseline/ が2021年11月のまま凍結されていることを守る。

RTA の出発点なので、ここが変わるとタイムの意味が消える。
改善はすべて別ディレクトリで行う、という README の約束を機械で担保する。
"""

from __future__ import annotations

import hashlib
import re

from conftest import BASELINE_DIR

# 2021年11月版のソースの sha256。baseline/README.md に載っている値と同じ。
FROZEN_SHA256 = {
    "animal_shogi.py": "cc354e302192baec01f4b8bc217a022729b594fef828a7cfc726753bd48085f7",
    "animal_shogi.c": "7998981366e0bf2dcd8b2ec12e0e77a2453ad45396d674337e5e567fe42f27ad",
    "animal_shogi.h": "fdec3e10de656dd82c55b5ba21f6dc0331195f2fe2dfc191dff33017e9365db6",
}


def test_sources_are_unchanged() -> None:
    for name, expected in FROZEN_SHA256.items():
        path = BASELINE_DIR / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"baseline/{name} が変更されている。\n"
            f"  期待: {expected}\n"
            f"  実際: {actual}\n"
            f"baseline/ は凍結されている。改善は別ディレクトリで行うこと。"
        )


def test_readme_hashes_match_the_pinned_ones() -> None:
    """baseline/README.md の短縮 sha256 が、上のピン留めとずれていないこと。"""
    readme = (BASELINE_DIR / "README.md").read_text(encoding="utf-8")
    for name, expected in FROZEN_SHA256.items():
        short = f"{expected[:8]}…{expected[-8:]}"
        assert short in readme, f"baseline/README.md に {name} の {short} が無い"


def test_makefile_has_no_optimization_flag() -> None:
    """`-O3 を付ける` は改善の梯子の1段目。baseline/ に混ぜてはいけない。"""
    makefile = (BASELINE_DIR / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"-O[0-9fgsz]", makefile) is None, (
        "baseline/Makefile に最適化フラグが入っている。"
        "ベースラインは -O0 のまま。フラグ変更は別ディレクトリの記録として出すこと。"
    )
    assert "-march" not in makefile
