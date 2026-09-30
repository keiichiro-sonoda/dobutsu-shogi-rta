"""impl/27_no_interposition — `gcc` 行に `-fno-semantic-interposition` を足す。

変数は1つ。`.c` / `.h` / `.py` は impl/26 とバイト同一で、`Makefile` の差はこのフラグ1つだけ。

`-fPIC -shared` の既定では、同じ `.so` の中の関数どうしの呼び出しも「実行時に別の定義へ
差し替えられうる」ものとして扱われ、PLT を経由し、インライン展開もされない。このフラグは
「差し替えない」と約束して、それをやめさせる。`nextBoardInvNormal()` の中の
`normalBoard@plt` への `call` 3か所が 0 になり (インライン展開)、`nextBoardSeenNormal()` →
`nextBoardInvNormal()` などは PLT を通らない直接の呼び出しになる。このリポジトリは `.so` を
ctypes から呼ぶだけで、関数を差し替える仕組みは使っていない。

⚠️ 等価性検査 (`tests/test_*_equivalence.py`) と `conftest.build_library()` は自前の gcc 行で
ビルドするので、`Makefile` を1行も通らない (test_impl_18_optimized.py と同じ事情)。ここでは
両方の実装を**それぞれの `Makefile` で** ビルドし、呼び出しが変わったことと、打ち切って回した
成果物が impl/26 とバイト一致することを見る。
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

IMPL = "27_no_interposition"
PREV = "26_inv_bits"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
FLAG = "-fno-semantic-interposition"


def makefile(path: pathlib.Path) -> str:
    return (path / "Makefile").read_text(encoding="utf-8")


def make_so(src: pathlib.Path, work: pathlib.Path) -> pathlib.Path:
    """その実装の `Makefile` で `.so` を作る。"""
    work.mkdir(parents=True, exist_ok=True)
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        shutil.copy(src / name, work / name)
    done = subprocess.run(
        ["make", "animal_shogi.so"], cwd=work, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"make が失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"
    return work / "animal_shogi.so"


def calls(so: pathlib.Path) -> dict[str, list[str]]:
    """関数ごとの `call` の行き先 (objdump -d)。"""
    out = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", str(so)], capture_output=True, text=True, check=True
    ).stdout
    table: dict[str, list[str]] = {}
    fn = ""
    for line in out.splitlines():
        if m := re.match(r"^[0-9a-f]+ <(\S+)>:$", line):
            fn = m.group(1)
        elif "\tcall" in line:
            table.setdefault(fn, []).append(line.split()[-1].strip("<>"))
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


def test_everything_but_the_makefile_is_byte_identical_to_impl_26() -> None:
    """★C も .h も Python も #26 とバイト同一。動くのはビルドのフラグだけ。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "animal_shogi.py"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), name


def test_the_makefile_differs_by_exactly_the_one_flag() -> None:
    """★`Makefile` の差は gcc 行に `-fno-semantic-interposition` を1つ足しただけ。

    `-march=native`・`-O3`・移動表の `static const` は別の試行で測る (混ぜると帰属が取れない)。
    """
    prev, cur = makefile(PREV_DIR).splitlines(), makefile(IMPL_DIR).splitlines()
    assert len(prev) == len(cur)
    diff = [(a, b) for a, b in zip(prev, cur, strict=True) if a != b]
    assert len(diff) == 1, diff
    before, after = (d.split() for d in diff[0])
    assert [t for t in after if t not in before] == [FLAG]
    assert [t for t in after if t != FLAG] == before
    assert diff[0][1].startswith("\t"), "レシピの行はタブで始まる"


def test_no_impl_env_needed() -> None:
    """★既定のビルド・実行コマンドで走ること (`impl.env` だと impl_sha256 が #26 と同じになる)。"""
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# フラグが効いていること (それぞれの Makefile でビルドして見る)
# --------------------------------------------------------------------------


def test_the_builds_differ(built: dict[str, pathlib.Path]) -> None:
    assert built[PREV].read_bytes() != built[IMPL].read_bytes(), "フラグが効いていない"


def test_normal_board_is_inlined_and_the_hot_calls_skip_the_plt(
    built: dict[str, pathlib.Path],
) -> None:
    """★`normalBoard@plt` への call が 3 → 0。熱い経路の呼び出しは PLT を通らなくなる。

    `nextBoardInvNormal()` の中の `invBoard()` は、フラグを付けてもインライン展開されず
    直接の call として残る (gcc の判断。フラグが約束するのは差し替えないことだけ)。
    """
    if shutil.which("objdump") is None:
        pytest.skip("objdump が無い")
    old, new = calls(built[PREV]), calls(built[IMPL])
    assert old["nextBoardInvNormal"].count("normalBoard@plt") == 3
    assert old["nextBoardInvNormal"].count("invBoard@plt") == 1
    assert not [t for ts in new.values() for t in ts if t == "normalBoard@plt"]
    assert not [t for ts in new.values() for t in ts if t.startswith("normalBoard")]
    assert new["nextBoardInvNormal"].count("invBoard") == 1
    for caller, callee in (
        ("nextBoardSeenNormal", "nextBoardInvNormal"),
        ("nextBoardIndexNormal", "nextBoardInvNormal"),
        ("expandRound", "nextBoardSeenNormal"),
        ("buildSuccRange", "nextBoardIndexNormal"),
    ):
        assert f"{callee}@plt" in old[caller], (caller, callee)
        assert callee in new[caller] and f"{callee}@plt" not in new[caller], (caller, callee)


# --------------------------------------------------------------------------
# 走らせて impl/26 と突き合わせる (それぞれの Makefile の .so で)
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


def test_the_rounds_and_p0_agree_with_impl_26(runs: dict[str, dict[str, Any]]) -> None:
    """★ラウンドごとの件数と、P0 に渡る中身・P0 が詰めたバイト列が impl/26 と一致する。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) > 10
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"):
        assert a[key] == b[key], key


def test_the_artifacts_are_byte_identical_to_impl_26(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/26 とバイト一致する (インライン展開しても値は同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
