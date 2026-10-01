"""impl/28_march_native — `gcc` 行に `-march=native` を足す。

変数は1つ。`.c` / `.h` / `.py` は impl/27 とバイト同一で、`Makefile` の差はこのフラグ1つだけ
(`-O2 -fno-semantic-interposition` は残す)。`-march=native` は `-mtune` も一緒に変える。

計測機では `gcc -march=native -Q --help=target` が `-march=broadwell` / `-mtune=broadwell` に
解決され、BMI2 の `shlx` / `shrx` などが使えるようになる。⚠️ **別の CPU では別のバイナリになる。**
命令の数を見るテストは、BMI2 を持つ CPU でだけ走らせる。

⚠️ 等価性検査と `conftest` の `.so` は自前の gcc 行でビルドするので `Makefile` を通らない
(#18・#27 と同じ事情)。ここでは2つの実装を**それぞれの `Makefile` で** ビルドし、命令が
変わったことと、打ち切って回した成果物が impl/27 とバイト一致することを見る。
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
from test_impl_27_no_interposition import make_so

IMPL = "28_march_native"
PREV = "27_no_interposition"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
FLAG = "-march=native"
# BMI2 で増えるシフト (シフト量を cl に置かなくてよい)
BMI2_SHIFTS = ("shlx", "shrx", "sarx")


def makefile(path: pathlib.Path) -> str:
    return (path / "Makefile").read_text(encoding="utf-8")


def has_bmi2() -> bool:
    try:
        flags = pathlib.Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"^flags\s*:.*\bbmi2\b", flags, flags=re.M) is not None


def mnemonics(so: pathlib.Path) -> dict[str, list[str]]:
    """関数ごとの命令の名前の並び (objdump -d)。"""
    out = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", str(so)], capture_output=True, text=True, check=True
    ).stdout
    table: dict[str, list[str]] = {}
    fn = ""
    for line in out.splitlines():
        if m := re.match(r"^[0-9a-f]+ <(\S+)>:$", line):
            fn = m.group(1)
        elif m := re.match(r"^\s+[0-9a-f]+:\t(\S+)", line):
            table.setdefault(fn, []).append(m.group(1))
    return table


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    root = tmp_path_factory.mktemp("make")
    return {impl: make_so(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}


# --------------------------------------------------------------------------
# 1変数であること
# --------------------------------------------------------------------------


def test_everything_but_the_makefile_is_byte_identical_to_impl_27() -> None:
    """★C も .h も Python も #27 とバイト同一。動くのはビルドのフラグだけ。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "animal_shogi.py"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_the_makefile_differs_by_exactly_the_one_flag() -> None:
    """★`Makefile` の差は gcc 行に `-march=native` を1つ足しただけ。

    移動表の `static const`・`-O3`・`-mtune` だけの腕は別の試行 (混ぜると帰属が取れない)。
    """
    prev, cur = makefile(PREV_DIR).splitlines(), makefile(IMPL_DIR).splitlines()
    assert len(prev) == len(cur)
    diff = [(a, b) for a, b in zip(prev, cur, strict=True) if a != b]
    assert len(diff) == 1, diff
    before, after = (d.split() for d in diff[0])
    assert [t for t in after if t not in before] == [FLAG]
    assert [t for t in after if t != FLAG] == before
    assert "-fno-semantic-interposition" in after and "-O2" in after
    assert not [t for t in after if t.startswith("-mtune")], "-mtune は別に足さない"
    assert diff[0][1].startswith("\t"), "レシピの行はタブで始まる"


def test_no_impl_env_needed() -> None:
    """★既定のビルド・実行コマンドで走ること (`impl.env` だと impl_sha256 が #27 と同じになる)。"""
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# フラグが効いていること (それぞれの Makefile でビルドして見る)
# --------------------------------------------------------------------------


def test_the_builds_differ(built: dict[str, pathlib.Path]) -> None:
    assert built[PREV].read_bytes() != built[IMPL].read_bytes(), "フラグが効いていない"


def test_the_generator_uses_bmi2_shifts(built: dict[str, pathlib.Path]) -> None:
    """★BMI2 を持つ CPU なら、生成器 (`nextBoardInvNormal`) に `shlx` / `shrx` が入る。

    #27 のビルドには1つも無い (x86-64 のベースライン向け)。
    """
    if shutil.which("objdump") is None:
        pytest.skip("objdump が無い")
    if not has_bmi2():
        pytest.skip("この CPU は BMI2 を持たない (-march=native の中身が計測機と違う)")
    old, new = mnemonics(built[PREV]), mnemonics(built[IMPL])
    assert not [m for ms in old.values() for m in ms if m in BMI2_SHIFTS]
    assert sum(m in BMI2_SHIFTS for m in new["nextBoardInvNormal"]) > 0


# --------------------------------------------------------------------------
# 走らせて impl/27 と突き合わせる (それぞれの Makefile の .so で)
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


def test_the_rounds_and_p0_agree_with_impl_27(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/27 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_27(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/27 とバイト一致する (命令を替えても値は同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
