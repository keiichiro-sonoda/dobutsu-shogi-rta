"""impl/35_bitboard — 全探索の生成器をビットボード型にする。

#34 の生成器 `nextBoardInvNormalNC()` は、12 マスを1つずつ分岐で調べていた (空きか・駒の種類・
行き先に駒があるか・自分の駒か・盤の外か)。#35 では、マスの集合をビットで持ち、表引きとビット演算で
行き先の集合を作って `ctz` で1つずつ取り出す (実験 bitboard_gen の腕 bb_nibble をそのまま移した)。
手番側の駒のマスと行き先を番号の小さい順に取り出すので、後続の列は並びまで #34 と同じ。

ここで固定するもの:

- 差分の範囲 (C は「#34 ＋ bitboard_gen の bb_nibble.patch」そのもの。
  ほかのファイルは #34 とバイト同一)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  (詰め物の検査は tests/test_hot_layout_padding.py が, `hot_layout.ld` の中身ごとに1回回す)
- 生成器が、打ち切った全探索で展開した全局面で、#34 と戻り値・後続の列 (並びまで)・
  キャッチ抜きの数が同じ
- 打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・後退解析に渡す3本の列・全探索の側の dat/) が
  #34 とバイト一致すること
- 打ち切った全探索のあとの後退解析の dat/ が #34 とバイト一致すること (後続の順番が同じなので,
  採番順も同じ。#34 のテストは #33 と比べられなかったが, ここは比べられる)

全局面 (到達可能な 246,803,167 局面) での一致の検査は experiments/bitboard_gen が行った
(この実装の .so は bitboard_gen の bb_nibble の .so とバイト一致する。門番 #35 の README)。
"""

from __future__ import annotations

import ctypes
import pathlib
import re
import subprocess
from typing import Any

import conftest
import pytest
from conftest import ROOT, chdir, load_impl
from test_impl_22_in_memory import ROUNDS
from test_impl_33_hot_layout import make, sections, symbols
from test_impl_34_unmove import HOT, limited_forward

IMPL = "35_bitboard"
PREV = "34_unmove"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "bitboard_gen" / "patches" / "bb_nibble.patch"
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tools() -> None:
    import shutil

    for tool in ("gcc", "make", "nm", "objdump", "readelf", "patch"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")


@pytest.fixture(scope="module")
def built(tools: None, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    root = tmp_path_factory.mktemp("make")
    return {impl: make(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}


# --------------------------------------------------------------------------
# 差分の範囲と置き場所
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Makefile", "hot_layout.ld", "animal_shogi.h", "animal_shogi.py"])
def test_the_other_files_are_byte_identical_to_impl_34(name: str) -> None:
    """★C 以外 (ビルドの指定・熱い関数の一覧・ヘッダ・Python) は #34 とバイト同一。"""
    assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes()


def test_the_files_are_the_same_five_as_impl_34() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_c_is_impl_34_plus_the_bb_nibble_patch(tools: None, tmp_path: pathlib.Path) -> None:
    """★C は #34 に bitboard_gen の bb_nibble.patch を当てたものそのもの (ほかの変更を混ぜない)。"""
    (tmp_path / "animal_shogi.c").write_bytes((PREV_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(tmp_path), "-i", str(PATCH)], check=True
    )
    assert (tmp_path / "animal_shogi.c").read_bytes() == (IMPL_DIR / "animal_shogi.c").read_bytes()


def test_only_the_generator_and_its_table_changed() -> None:
    """変わった関数は nextBoardInvNormalNC と, 行き先の表を作る dstTableBuild だけ。"""
    fn = re.compile(r"^\S[^;\n]*?\b(\w+)\([^;]*?\)\s*\{", re.M)

    def bodies(c: str) -> dict[str, str]:
        """関数名 → 本体 (先頭から, 波括弧が閉じるところまで。コメントは除く)。"""
        c = re.sub(r"//.*", "", c)
        out = {}
        for m in fn.finditer(c):
            depth, i = 0, m.end() - 1
            while True:
                depth += {"{": 1, "}": -1}.get(c[i], 0)
                if depth == 0:
                    break
                i += 1
            out[m.group(1)] = c[m.start() : i + 1]
        return out

    a, b = bodies(text(PREV_DIR / "animal_shogi.c")), bodies(text(IMPL_DIR / "animal_shogi.c"))
    changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    assert changed == ["dstTableBuild", "nextBoardInvNormalNC"], changed


def test_the_linker_script_lists_the_hot_functions_in_order() -> None:
    """★リンカースクリプトの一覧と `HOT` (#34 のテスト) が同じ。生成器の名前は変えていない。"""
    listed = re.findall(r"\*\(\.text\.(\w+)\)", text(IMPL_DIR / LD))
    assert tuple(listed) == HOT


def test_the_hot_functions_sit_in_their_own_section_before_text(
    built: dict[str, pathlib.Path],
) -> None:
    """★熱い関数は全部 `.text.hot_layout` の中に一覧の順で並び、区画は `.text` の前にある。"""
    secs, syms = sections(built[IMPL]), symbols(built[IMPL])
    start, size, align = secs[SECTION]
    assert align == 4096 and start % 4096 == 0
    assert start + size <= secs[".text"][0], "区画が .text の後ろにある"
    addrs = [syms[fn][0] for fn in HOT]
    assert addrs == sorted(addrs), "並びが一覧の順でない"
    assert addrs[0] == start
    for fn in HOT:
        a, s = syms[fn]
        assert start <= a and a + s <= start + size, f"{fn} が区画の外にある"
        assert a % 64 == 0, f"{fn} の先頭が 64 バイトの区切りでない: {a:#x}"
    inside = {
        fn.removesuffix(".localalias") for fn, (a, _s) in syms.items() if start <= a < start + size
    }
    assert sorted(inside) == sorted(HOT), "区画に一覧の外の関数がある"


# --------------------------------------------------------------------------
# 打ち切った全探索と、そのあとの後退解析
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(
    built: dict[str, pathlib.Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """#34 と #35 を同じところで打ち切り、どちらも続けて後退解析まで回す。
    ⚠️ `load_impl()` が差し込む -O0 の `.so` を, Makefile で作った `.so` に差し替える
    (#33 のテストと同じ)。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in (PREV, IMPL):
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            out[impl] = limited_forward(module, work)
            out[impl]["work"] = work
            out[impl]["module"] = module
            out[impl]["expanded"] = [
                b for name in ("uk_all", "catch_wins", "try_loses") for b in getattr(module, name)
            ]
            with chdir(work):
                module.retreatAnalysis()
    return out


def generator(so: pathlib.Path) -> Any:
    """その実装の生成器。同じパスの .so を開き直すので, 走行で作った利きの表をそのまま使う。"""
    fn = ctypes.CDLL(str(so)).nextBoardInvNormalNC
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_int)]
    return fn


def test_the_generator_agrees_with_impl_34(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★展開した全局面で、生成器の戻り値・後続の列 (並びまで)・キャッチ抜きの数が #34 と同じ。"""
    g0, g1 = generator(built[PREV]), generator(built[IMPL])
    boards = runs[PREV]["expanded"]
    assert len(boards) > 10000
    kinds = {"catch": 0, "try": 0, "unknown": 0}
    a, b = (ctypes.c_uint64 * 64)(), (ctypes.c_uint64 * 64)()
    na, nb = ctypes.c_int(-7), ctypes.c_int(-7)
    for x in boards:
        r0 = g0(x, a, ctypes.byref(na))
        r1 = g1(x, b, ctypes.byref(nb))
        assert (r0, na.value) == (r1, nb.value), hex(x)
        if r0 > 0:
            assert list(a[:r0]) == list(b[:r1]), hex(x)
        kinds["catch" if r0 == 0 else "try" if r0 < 0 else "unknown"] += 1
    assert all(kinds.values()), f"種類が揃っていない (テストが空振り): {kinds}"


def test_the_forward_search_is_byte_identical_to_impl_34(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #34 と同じ。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key


def test_the_whole_dat_is_byte_identical_to_impl_34(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析まで含めて, dat/ の全ファイルが #34 とバイト一致する
    (後続の順番が同じなので, 後退解析の採番順も同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir())
    assert any(n.startswith("win003te") for n in names), "後退解析が浅すぎる (テストが空振り)"
    assert any(n.startswith("unknown") for n in names)
    for name in names:
        assert (da / name).read_bytes() == (db / name).read_bytes(), name
