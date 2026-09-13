"""impl/01_wrapper — ベースラインからの変更はラッパーの1行だけ。

1試行1変数。C も Makefile も触らない (＝ -O0 のまま) ので、
記録 #1 のタイム差は「list(nba)[:nbn] をやめた」効果だけを表す。
"""

from __future__ import annotations

import difflib

from conftest import BASELINE_DIR, ROOT

IMPL_DIR = ROOT / "impl" / "01_wrapper"

# 唯一許される変更
EXPECTED_REMOVED = "        nbl = list(nba)[:nbn]"
EXPECTED_ADDED = "        nbl = nba[:nbn]"


def test_only_the_python_source_differs() -> None:
    """C・ヘッダ・Makefile はベースラインとバイト単位で同一。ビルドフラグも据え置き。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (BASELINE_DIR / name).read_bytes(), (
            f"impl/01_wrapper/{name} がベースラインと違う。この試行で変えるのはラッパーだけ"
        )


def test_python_differs_by_exactly_one_line() -> None:
    base = (BASELINE_DIR / "animal_shogi.py").read_text(encoding="utf-8").splitlines()
    impl = (IMPL_DIR / "animal_shogi.py").read_text(encoding="utf-8").splitlines()

    removed = [ln[2:] for ln in difflib.ndiff(base, impl) if ln.startswith("- ")]
    added = [ln[2:] for ln in difflib.ndiff(base, impl) if ln.startswith("+ ")]

    assert removed == [EXPECTED_REMOVED], f"想定外の削除行: {removed}"
    assert added == [EXPECTED_ADDED], f"想定外の追加行: {added}"


def test_needs_no_impl_env() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()
