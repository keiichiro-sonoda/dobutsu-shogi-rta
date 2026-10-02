"""impl/29_static_const_moves — 移動表4本を `static const` にする。

変数は1つ。`GIRAFFE_MOVE` / `ELEPHANT_MOVE` / `LION_MOVE` / `CHICKEN2_MOVE` を
外部リンケージの非 `const` グローバルから `static const int` にし、`nextBoardInvNormal()` の
`moves` を `const int *` にした (`= NULL` と #20 のコメントは残す)。`.h` からは `extern` 宣言を
消した (`.c` の `static` と食い違うため)。`.py` と `Makefile` は #28 とバイト同一。

#28 までは `-fPIC` のため、表を選ぶたびに GOT から表の番地を読んでいた
(`readelf -r` の `GLOB_DAT` に4本)。`static const` なら番地を RIP 相対の `lea` で直接作れる。
`.so` の外 (Python 側) からこの表を読んでいる所は無い。

⚠️ #27・#28 と違って C のソースが変わるので、差分の範囲をここで固定する。等価性検査と
`conftest` の `.so` は自前の gcc 行でビルドするので `Makefile` を通らない。ここでは2つの実装を
**それぞれの `Makefile` で** ビルドする。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from typing import Any

import conftest
import pytest
from conftest import ROOT, load_impl
from test_impl_22_in_memory import limited_run
from test_impl_23_loop_prefetch import code_only
from test_impl_27_no_interposition import make_so

IMPL = "29_static_const_moves"
PREV = "28_march_native"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
TABLES = ("GIRAFFE_MOVE", "ELEPHANT_MOVE", "LION_MOVE", "CHICKEN2_MOVE")


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


def test_the_python_and_the_makefile_are_byte_identical_to_impl_28() -> None:
    """★`.py` と `Makefile` は #28 とバイト同一 (gcc 行のフラグも #28 のまま)。"""
    for name in ("animal_shogi.py", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_the_header_only_drops_the_four_extern_declarations() -> None:
    """★`.h` の差は移動表4本の `extern` 宣言 (と直後の空行) を消しただけ。"""
    old = text(PREV_DIR / "animal_shogi.h")
    block = "".join(
        f"extern int {name}[{n}];\n" for name, n in zip(TABLES, (4, 4, 8, 6), strict=True)
    )
    assert old.count(block + "\n") == 1
    assert text(IMPL_DIR / "animal_shogi.h") == old.replace(block + "\n", "", 1)


def test_the_c_differs_only_in_the_tables_and_the_pointer_type() -> None:
    """★`.c` のコード (コメントを除く) の差は、表4本の `static const` と `moves` の型だけ。"""
    old = text(PREV_DIR / "animal_shogi.c")
    for name in TABLES:
        old = re.sub(rf"^int {name}\[", f"static const int {name}[", old, count=1, flags=re.M)
    decl = "    int i, j, dst, own_num, own_p, *moves = NULL, moves_num, src_mod16, dst_mod16;\n"
    assert old.count(decl) == 1
    old = old.replace(
        decl,
        "    int i, j, dst, own_num, own_p, moves_num, src_mod16, dst_mod16;\n"
        "    const int *moves = NULL;\n",
    )
    assert code_only(text(IMPL_DIR / "animal_shogi.c")) == code_only(old)


def test_no_python_reads_the_tables_from_the_so() -> None:
    """★`.so` の外から移動表を読んでいる所が無い (static にするとシンボルが外から見えなくなる)。

    ctypes で読むなら `lib.GIRAFFE_MOVE` のような属性か `in_dll(..., "GIRAFFE_MOVE")` になるので、
    その形だけを探す (門番の tables.py のように、readelf / objdump の出力を読むために名前を文字列で
    持つのは読んでいるうちに入らない)。
    """
    names = "|".join(TABLES)
    pattern = re.compile(rf"\.\s*(?:{names})\b|in_dll\([^)]*(?:{names})")
    hits = [
        p
        for top in ("impl/29_static_const_moves", "tools", "tests", "experiments")
        for p in (ROOT / top).rglob("*.py")
        if p != pathlib.Path(__file__).resolve() and pattern.search(text(p))
    ]
    assert hits == [], hits


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# 表の読み方が変わったこと (それぞれの Makefile でビルドして見る)
# --------------------------------------------------------------------------


def test_the_tables_leave_the_got(built: dict[str, pathlib.Path]) -> None:
    """★`readelf -r` の `GLOB_DAT` から移動表4本が消える (#28 は4本とも GOT 経由)。"""
    if shutil.which("readelf") is None:
        pytest.skip("readelf が無い")

    def relocated(so: pathlib.Path) -> set[str]:
        out = subprocess.run(
            ["readelf", "-rW", str(so)], capture_output=True, text=True, check=True
        ).stdout
        return {
            name for name in TABLES for ln in out.splitlines() if name in ln and "GLOB_DAT" in ln
        }

    assert relocated(built[PREV]) == set(TABLES)
    assert relocated(built[IMPL]) == set()


def test_the_generator_takes_the_table_address_rip_relative(
    built: dict[str, pathlib.Path],
) -> None:
    """★生成器は GOT から番地を読む `mov` の代わりに、RIP 相対の `lea` で表の番地を作る。"""
    if shutil.which("objdump") is None:
        pytest.skip("objdump が無い")

    def body(so: pathlib.Path) -> list[str]:
        out = subprocess.run(
            ["objdump", "-d", "--no-show-raw-insn", str(so)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        start = out.index("<nextBoardInvNormal>:\n")
        return out[start : out.index("\n\n", start)].splitlines()

    old, new = body(built[PREV]), body(built[IMPL])
    assert sum("mov" in ln and "_MOVE@@Base" in ln for ln in old) == 4
    assert not [ln for ln in new if "@@Base" in ln and "_MOVE" in ln]
    assert sorted(t for t in TABLES for ln in new if "lea" in ln and f"<{t}>" in ln) == sorted(
        TABLES
    )


# --------------------------------------------------------------------------
# 走らせて impl/28 と突き合わせる (それぞれの Makefile の .so で)
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


def test_the_rounds_and_p0_agree_with_impl_28(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/28 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_28(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/28 とバイト一致する (表の値も並びも同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
