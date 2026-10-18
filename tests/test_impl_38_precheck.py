"""impl/38_precheck — 全探索の生成器にキャッチの先行判定を入れる。

#37 の生成器 `nextBoardInvNormalNC()` は、手番側の駒の行き先を番号の小さい順に作っていき、
相手のライオンを取れる行き先に当たったところで `return 0` していた (キャッチ局面でも、その前に
利きの一覧を作り、いくつかの後続を作っていた)。#38 では、反転の直後・利きの一覧より前に
「手番側が相手のライオンを取れるか」だけを先に決め、取れれば後続を作らずに `return 0` する
(実験 f1_select_catch の腕 precheck をそのまま移した)。判定は、`g_dst` を裏返した表
`g_reach[駒][L]` と、駒の種類ごとの手番側の駒のマスの集合 `komaSet(b, 駒)` の AND を5つ OR で
まとめる形で、ループは無い。先行判定のあとの本体は #37 のまま。

前提: 反転したあとの盤に相手のライオン (LION1) がちょうど1ついること (いないと
`__builtin_ctzll(0)` で未定義動作)。

ここで固定するもの:

- 差分の範囲 (C は「#37 ＋ f1_select_catch の precheck.patch」に前提を述べるコメント3行を
  足したものそのもの。ほかのファイルは #37 とバイト同一. 変わった関数は生成器と表を作る関数と,
  足した static inline の komaSet だけ)
- 関数の記号が #37 と同じ (komaSet はインライン展開される)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  (詰め物の検査は tests/test_hot_layout_padding.py が, `hot_layout.ld` の中身ごとに1回回す)
- 生成器が、打ち切った全探索で展開した全局面で、#37 と戻り値・後続の列 (並びまで)・
  キャッチ抜きの数が同じ. キャッチ局面・トライ負けの局面・取れるのにトライの段にもいる局面を
  それぞれ1つ以上含む
- 生成器に渡る局面 (打ち切った走行の展開する全局面) で, 反転したあとの盤に LION1 がちょうど1つ
- 打ち切った全探索の出力と, そのあとの後退解析の dat/ の全ファイルが #37 とバイト一致すること

全局面 (到達可能な 246,803,167 局面) での一致の検査は experiments/f1_select_catch が行った
(この実装の .so は f1_select_catch の precheck の .so とバイト一致する。門番 #38 の README)。
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

IMPL = "38_precheck"
PREV = "37_mirror1"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "f1_select_catch" / "patches" / "precheck.patch"
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"
LION1 = 4
# 前提を述べるコメント (パッチの外で足した3行。.so は変わらない)
PREMISE = "    // 記録 #38 の前提:"


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
def test_the_other_files_are_byte_identical_to_impl_37(name: str) -> None:
    """★C 以外 (ビルドの指定・熱い関数の一覧・ヘッダ・Python) は #37 とバイト同一。"""
    assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes()


def test_the_files_are_the_same_five_as_impl_37() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def without_premise(c: str) -> str:
    """前提を述べるコメントの3行 (PREMISE で始まる行と, 続く2行) を除いた C。"""
    lines = c.splitlines(keepends=True)
    i = next(k for k, ln in enumerate(lines) if ln.startswith(PREMISE))
    assert all(ln.lstrip().startswith("//") for ln in lines[i : i + 3])
    return "".join(lines[:i] + lines[i + 3 :])


def test_the_c_is_impl_37_plus_the_precheck_patch(tools: None, tmp_path: pathlib.Path) -> None:
    """★C は #37 に f1_select_catch の precheck.patch を当て, 前提を述べるコメント3行を
    足したものそのもの (ほかの変更を混ぜない)。"""
    (tmp_path / "animal_shogi.c").write_bytes((PREV_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(tmp_path), "-i", str(PATCH)], check=True
    )
    assert text(tmp_path / "animal_shogi.c") == without_premise(text(IMPL_DIR / "animal_shogi.c"))


def test_only_the_generator_its_table_and_komaset_changed() -> None:
    """変わった関数は生成器 nextBoardInvNormalNC と, 表を作る dstTableBuild (g_reach を足す) と,
    足した static inline の komaSet だけ。関数名は, 引数の並びの前の最後の名前
    (`__attribute__((...))` を飛ばす)。"""
    fn = re.compile(r"^[^\s}][^;{}\n]*?\b(\w+)\(([^()]*)\)\s*\{", re.M)

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
    assert changed == ["dstTableBuild", "komaSet", "nextBoardInvNormalNC"], changed
    assert "komaSet" not in a


def function_symbols(so: pathlib.Path) -> list[str]:
    out = subprocess.run(["nm", str(so)], check=True, capture_output=True, text=True).stdout
    return sorted(c[2] for ln in out.splitlines() if len(c := ln.split()) == 3 and c[1] in "tT")


def test_no_new_function_symbol(built: dict[str, pathlib.Path]) -> None:
    """★関数の記号 (nm の t / T) が #37 と同じ。komaSet はインライン展開され,
    熱い関数は増えない。"""
    assert function_symbols(built[IMPL]) == function_symbols(built[PREV])


def test_the_linker_script_lists_the_hot_functions_in_order() -> None:
    """★リンカースクリプトの一覧と `HOT` (#34 のテスト) が同じ。新しい熱い関数は無い。"""
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
    """#37 と #38 を同じところで打ち切り、どちらも続けて後退解析まで回す。
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


def inverter(so: pathlib.Path) -> Any:
    fn = ctypes.CDLL(str(so)).invBoard
    fn.restype = ctypes.c_uint64
    fn.argtypes = [ctypes.c_uint64]
    return fn


def lion1_squares(ib: int) -> list[int]:
    """反転したあとの盤 ib で, 相手のライオン (LION1) がいるマスの番地 (0, 4, …, 44)。"""
    return [adr for adr in range(0, 48, 4) if (ib >> adr) & 0xF == LION1]


def test_the_generator_agrees_with_impl_37(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★展開した全局面で、生成器の戻り値・後続の列 (並びまで)・キャッチ抜きの数が #37 と同じ。
    キャッチ局面・トライ負けの局面 (相手のライオンがトライの段にいて, 取れない)・取れるのに
    トライの段にもいる局面 (先行判定の return 0 が, 本体のあとの -1 より先に勝つ) を
    それぞれ1つ以上通したことも確かめる。"""
    g0, g1 = generator(built[PREV]), generator(built[IMPL])
    inv = inverter(built[IMPL])
    boards = runs[PREV]["expanded"]
    assert len(boards) > 10000
    kinds = {"catch": 0, "try": 0, "unknown": 0, "catch_on_try_row": 0}
    a, b = (ctypes.c_uint64 * 64)(), (ctypes.c_uint64 * 64)()
    na, nb = ctypes.c_int(-7), ctypes.c_int(-7)
    for x in boards:
        r0 = g0(x, a, ctypes.byref(na))
        r1 = g1(x, b, ctypes.byref(nb))
        assert (r0, na.value) == (r1, nb.value), hex(x)
        if r0 > 0:
            assert list(a[:r0]) == list(b[:r1]), hex(x)
        kinds["catch" if r0 == 0 else "try" if r0 < 0 else "unknown"] += 1
        if r0 == 0 and any(adr % 16 == 12 for adr in lion1_squares(inv(x))):
            kinds["catch_on_try_row"] += 1
    assert all(kinds.values()), f"種類が揃っていない (テストが空振り): {kinds}"


def test_every_expanded_board_has_exactly_one_opponent_lion(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★先行判定の前提: 生成器に渡る局面 (打ち切った走行の展開する全局面) で, 反転したあとの盤に
    相手のライオン (LION1) がちょうど1つ。いないと __builtin_ctzll(0) で未定義動作になる。"""
    inv = inverter(built[IMPL])
    boards = runs[IMPL]["expanded"]
    assert len(boards) > 10000
    bad = [hex(x) for x in boards if len(lion1_squares(inv(x))) != 1]
    assert not bad, bad[:5]


def test_the_forward_search_is_byte_identical_to_impl_37(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #37 と同じ。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key


def test_the_whole_dat_is_byte_identical_to_impl_37(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析まで含めて, dat/ の全ファイルが #37 とバイト一致する
    (後続の列が並びまで同じなので, 後退解析の採番順も同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir())
    assert any(n.startswith("win003te") for n in names), "後退解析が浅すぎる (テストが空振り)"
    assert any(n.startswith("unknown") for n in names)
    for name in names:
        assert (da / name).read_bytes() == (db / name).read_bytes(), name
