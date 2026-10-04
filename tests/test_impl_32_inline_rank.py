"""impl/32_inline_rank — `rankOf()` を呼び出し元へ必ずインライン展開させる。

変数は1つ。#30 の `rankOf()` (`static inline`) は `gcc -O2` が大きさの見積もりで展開せず,
`nextBoardSeenNormal()` から後続ごとに `call` になっていた (門番 #30 の `calls.py` で確かめた)。
`__attribute__((always_inline))` を付けて, 必ず展開させる。ランクの計算の中身は変えていない。
`.h` / `.py` / `Makefile` は #30 とバイト同一 (`Makefile` のフラグで全体の展開の基準は変えない)。

ここで固定するもの:

- 差分の範囲 (`.c` は `rankOf()` の定義の行に属性を付けたことと, その説明のコメントだけ)
- `objdump` で `rankOf` への `call` が無いこと (#30 には `nextBoardSeenNormal` などから3つある)
- 打ち切って後退解析まで回した成果物が #30 とバイト一致すること (それぞれの Makefile の .so で)
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any

import conftest
import pytest
from conftest import ROOT, load_impl
from test_impl_22_in_memory import limited_run
from test_impl_27_no_interposition import calls, make_so

IMPL = "32_inline_rank"
PREV = "30_rank_seen"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
OLD_DEF = "static inline uint64_t rankOf(u_long b) {\n"
NEW_DEF = "static inline __attribute__((always_inline)) uint64_t rankOf(u_long b) {\n"


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    root = tmp_path_factory.mktemp("make")
    return {impl: make_so(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}


# --------------------------------------------------------------------------
# 1変数であること (差分の範囲)
# --------------------------------------------------------------------------


def test_everything_but_the_c_is_byte_identical_to_impl_30() -> None:
    """★`.h` / `.py` / `Makefile` は #30 とバイト同一 (フラグで全体の展開の基準を変えていない)。"""
    for name in ("animal_shogi.h", "animal_shogi.py", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_the_c_only_adds_always_inline_to_rank_of() -> None:
    """★`.c` の差は `rankOf()` の定義に `always_inline` を付けたことと, 直前のコメントだけ。"""
    old, new = text(PREV_DIR / "animal_shogi.c"), text(IMPL_DIR / "animal_shogi.c")
    assert old.count(OLD_DEF) == 1 and new.count(NEW_DEF) == 1
    before, after = new.split(NEW_DEF)
    comment = before[before.rindex("// 記録 #32:") :]
    assert all(ln.startswith("// ") for ln in comment.splitlines()), comment
    assert before[: -len(comment)] + OLD_DEF + after == old


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# 展開されたこと (それぞれの Makefile でビルドして見る)
# --------------------------------------------------------------------------


def test_rank_of_is_no_longer_called(built: dict[str, pathlib.Path]) -> None:
    """★`rankOf` への `call` が無い。

    #30 には `nextBoardSeenNormal`・`seenInsert`・`seenContains` から3つあった。

    `rankOf` から呼ぶ小さな関数 (`rankFindKoma` など) も `call` として残っていない。
    """
    if shutil.which("objdump") is None:
        pytest.skip("objdump が無い")
    old, new = calls(built[PREV]), calls(built[IMPL])
    assert sorted(fn for fn, ts in old.items() for t in ts if t == "rankOf") == [
        "nextBoardSeenNormal",
        "seenContains",
        "seenInsert",
    ]
    helpers = ("rankOf", "rankFindKoma", "rankSqueeze", "rankHalf")
    assert not [(fn, t) for fn, ts in new.items() for t in ts if t.split("@")[0] in helpers]
    out = subprocess.run(
        ["nm", str(built[IMPL])], capture_output=True, text=True, check=True
    ).stdout
    assert " rankOf" not in out, "rankOf の本体が残っている"


# --------------------------------------------------------------------------
# 走らせて impl/30 と突き合わせる (それぞれの Makefile の .so で)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(
    built: dict[str, pathlib.Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """⚠️ `load_impl()` は自前の C を持つ実装に `conftest.impl_library()` (-O0 の自前の gcc 行) の
    `.so` を差し込むので、ここだけそれを Makefile で作った `.so` に差し替える。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in (PREV, IMPL):
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            assert (work / "animal_shogi.so").read_bytes() == built[impl].read_bytes()
            out[impl] = limited_run(module, work)
    return out


def test_the_rounds_and_p0_agree_with_impl_30(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/30 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_30(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/30 とバイト一致する (ランクの値は同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
