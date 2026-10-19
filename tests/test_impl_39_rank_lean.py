"""impl/39_rank_lean — 局面の番号の計算 `rankOf` の命令を、値を変えずに減らす。

#38 の `rankOf` は、ライオンの2マスを `rankFindKoma` で1頭ずつ探し、反転したあとの盤から
その2マスを `rankSqueeze` で1つずつ抜いて詰め、持ち駒の部分を掛け算と足し算で出していた。
#39 は実験 rank_fast の腕 lean をそのまま移し、この3か所を書き換えた:

1. ライオンの2マス: 4ビットの駒の値の下位3ビットが 100 なのはライオン (4 と 12) だけなので,
   両方の印を1回で作り, 上のビット (持ち主) で分けて tzcnt する
2. 詰め: 2マスを抜くマスクの表 `g_rank_keep[144]` で `pext` を1回 (BMI2)
3. 持ち駒の部分: 前後の組の和 s0 + s1 は合わせた組と同じ値 (種類ごとに 2 以下なので3進の桁が
   上がらない) なので, 表 `g_rank_hpart[27][64]` を1回引く

番号の値は1つも変わらない (rank_fast の一致の検査: 到達可能な全局面・その全候補・乱数の盤 1 億で
不一致 0)。だから発見済みの表・準備の配列・手数の配列の添字も, dat/ も #38 と同じになる。

ここで固定するもの:

- 差分の範囲 (C は「#38 ＋ rank_fast の lean.patch」そのもの. ほかのファイルは #38 とバイト同一.
  変わった関数は rankOf と表を作る rankTablesBuild だけ)
- 関数の記号が #38 と同じ (新しい下請けは無い)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  (詰め物の検査は tests/test_hot_layout_padding.py が, `hot_layout.ld` の中身ごとに1回回す)
- `rankBoard` の値が #38 と同じ: 打ち切った走行の全局面, それを q にした `unmoveCandidates()` の
  全候補, `rankValid` が真になる乱数の盤 (固定の種). ライオンの組が左右反転される側の盤と,
  持ち駒のある盤を, それぞれ1つ以上含む
- 打ち切った全探索の出力と, そのあとの後退解析の dat/ の全ファイルが #38 とバイト一致すること

全局面での一致の検査は experiments/rank_fast が行った (この実装の .so は rank_fast の lean の .so と
バイト一致する。門番 #39 の README)。
"""

from __future__ import annotations

import ctypes
import pathlib
import re
import subprocess
from collections.abc import Iterator
from typing import Any

import conftest
import pytest
from conftest import ROOT, chdir, load_impl
from test_impl_22_in_memory import ROUNDS
from test_impl_33_hot_layout import make, sections, symbols
from test_impl_34_unmove import HOT, limited_forward

IMPL = "39_rank_lean"
PREV = "38_precheck"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "rank_fast" / "patches" / "lean.patch"
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"
INDEX_EMPTY = (1 << 64) - 1
UNMOVE_MAX = 1024  # animal_shogi.c の UNMOVE_MAX
N_RANDOM = 200_000
# animal_shogi.h の enum PEACES
CHICK1, GIRAFFE1, ELEPHANT1, LION1, CHICKEN1 = 1, 2, 3, 4, 5
CHICK2, GIRAFFE2, ELEPHANT2, LION2, CHICKEN2 = 9, 10, 11, 12, 13


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
def test_the_other_files_are_byte_identical_to_impl_38(name: str) -> None:
    """★C 以外 (ビルドの指定・熱い関数の一覧・ヘッダ・Python) は #38 とバイト同一。"""
    assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes()


def test_the_files_are_the_same_five_as_impl_38() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_c_is_impl_38_plus_the_lean_patch(tools: None, tmp_path: pathlib.Path) -> None:
    """★C は #38 に rank_fast の lean.patch を当てたものそのもの (ほかの変更を混ぜない)。"""
    (tmp_path / "animal_shogi.c").write_bytes((PREV_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(tmp_path), "-i", str(PATCH)], check=True
    )
    assert (tmp_path / "animal_shogi.c").read_bytes() == (IMPL_DIR / "animal_shogi.c").read_bytes()


def test_only_rankof_and_its_tables_changed() -> None:
    """変わった関数は rankOf と, 表を作る rankTablesBuild (g_rank_keep と g_rank_hpart を足す)
    だけ。rankFindKoma と rankSqueeze (ほかでも使う) は残る。
    関数名は, 引数の並びの前の最後の名前。"""
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
    assert changed == ["rankOf", "rankTablesBuild"], changed
    assert {"rankFindKoma", "rankSqueeze"} <= set(b)


def function_symbols(so: pathlib.Path) -> list[str]:
    out = subprocess.run(["nm", str(so)], check=True, capture_output=True, text=True).stdout
    return sorted(c[2] for ln in out.splitlines() if len(c := ln.split()) == 3 and c[1] in "tT")


def test_no_new_function_symbol(built: dict[str, pathlib.Path]) -> None:
    """★関数の記号 (nm の t / T) が #38 と同じ。rankOf はどこでもインライン展開され,
    熱い関数は増えない。"""
    assert function_symbols(built[IMPL]) == function_symbols(built[PREV])


def test_rankof_uses_pext(built: dict[str, pathlib.Path]) -> None:
    """詰めが pext (BMI2) になっている (Makefile の -march=native で使われる)。
    #38 の .so には pext が無い。"""
    asm = {
        impl: subprocess.run(
            ["objdump", "-d", str(built[impl])], check=True, capture_output=True, text=True
        ).stdout
        for impl in (PREV, IMPL)
    }
    assert "\tpext " not in asm[PREV]
    assert "\tpext " in asm[IMPL]


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
    """#38 と #39 を同じところで打ち切り、どちらも続けて後退解析まで回す。
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


def ranker(so: pathlib.Path) -> Any:
    """その実装の公開の rankBoard (rankValid が真なら rankOf, 偽なら INDEX_EMPTY)。"""
    fn = ctypes.CDLL(str(so)).rankBoard
    fn.restype = ctypes.c_uint64
    fn.argtypes = [ctypes.c_uint64]
    return fn


def candidates(so: pathlib.Path) -> Any:
    fn = ctypes.CDLL(str(so)).unmoveCandidates
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]
    return fn


def mirror_side() -> set[tuple[int, int]]:
    """ライオンの組 (LION1 のマス, LION2 のマス) のうち, 番号を出す前に盤を左右反転する側。
    rankTablesBuild と同じ走査で, 先に出てきた側を代表にし, その鏡像を反転する側にする。"""

    def mirror(sq: int) -> int:
        return (2 - sq // 4) * 4 + sq % 4

    seen: set[tuple[int, int]] = set()
    flipped: set[tuple[int, int]] = set()
    for a in range(12):
        for c in range(12):
            if a == c or (a, c) in seen:
                continue
            seen |= {(a, c), (mirror(a), mirror(c))}
            if (mirror(a), mirror(c)) != (a, c):
                flipped.add((mirror(a), mirror(c)))
    return flipped


FLIPPED = mirror_side()


def lions(b: int) -> tuple[int, int]:
    sq = {(b >> (4 * s)) & 0xF: s for s in range(12)}
    return sq[LION1], sq[LION2]


def random_boards(n: int) -> Iterator[int]:
    """rankValid が真になる盤 (rank_fast の verify.c の random_board と同じ作り. 固定の種の
    xorshift64*)。ライオンを1頭ずつ別のマスに, ひよこ・きりん・ぞうを2枚ずつ, 空いたマス
    (持ち主と, ひよこは成りも選ぶ) か, どちらかの持ち駒に置く。"""
    mask = (1 << 64) - 1
    rng = 0x9E3779B97F4A7C15

    def nxt() -> int:
        nonlocal rng
        rng ^= rng >> 12
        rng ^= (rng << 25) & mask
        rng ^= rng >> 27
        return (rng * 0x2545F4914F6CDD1D) & mask

    kinds = (
        (CHICK1, CHICK2, CHICKEN1, CHICKEN2, 0, 6),
        (GIRAFFE1, GIRAFFE2, 0, 0, 2, 8),
        (ELEPHANT1, ELEPHANT2, 0, 0, 4, 10),
    )
    for _ in range(n):
        a = nxt() % 12
        c = nxt() % 11
        c += c >= a
        b = LION1 << (4 * a) | LION2 << (4 * c)
        sq = [i for i in range(12) if i not in (a, c)]
        h = 0
        for k, kind in enumerate(kinds):
            for _p in range(2):
                r = nxt() % (len(sq) + 2)
                if r < len(sq):
                    s, own = sq[r], nxt() & 1
                    koma = kind[own]
                    if k == 0 and nxt() & 1:
                        koma = kind[2 + own]
                    b |= koma << (4 * s)
                    sq[r] = sq[-1]
                    sq.pop()
                else:
                    h += 1 << kind[4 + r - len(sq)]
        yield b | h << 48


def compare(
    boards: list[int], r0: Any, r1: Any, kinds: dict[str, int], *, valid: bool
) -> list[str]:
    """2つの rankBoard の値が違う盤 (最初の 5 個)。valid なら #38 の値が INDEX_EMPTY でないことも
    見る。kinds に「反転する側」と「持ち駒あり」の数を足す。"""
    bad = []
    for b in boards:
        x, y = r0(b), r1(b)
        if x != y or (valid and x == INDEX_EMPTY):
            bad.append(f"{b:016x}: #38 {x} / #39 {y}")
            if len(bad) >= 5:
                break
        if x != INDEX_EMPTY:
            kinds["flipped"] += lions(b) in FLIPPED
            kinds["hand"] += (b >> 48) != 0
    return bad


def test_rank_is_the_same_on_every_expanded_board(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★打ち切った走行の全局面で, rankBoard の値が #38 と同じ (どれも正しい盤)。
    左右反転する側の盤と持ち駒のある盤を, それぞれ1つ以上通す。"""
    r0, r1 = ranker(built[PREV]), ranker(built[IMPL])
    boards = runs[PREV]["expanded"]
    assert len(boards) > 10000
    kinds = {"flipped": 0, "hand": 0}
    assert compare(boards, r0, r1, kinds, valid=True) == []
    assert all(kinds.values()), f"種類が揃っていない (テストが空振り): {kinds}"


def test_rank_is_the_same_on_every_unmove_candidate(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★打ち切った走行の全局面を q にした #38 の unmoveCandidates() の全候補 (U_loop で rankOf に
    渡る盤. 到達しない局面も含む) で, rankBoard の値が #38 と同じ。"""
    r0, r1, cand = ranker(built[PREV]), ranker(built[IMPL]), candidates(built[PREV])
    out = (ctypes.c_uint64 * UNMOVE_MAX)()
    boards: list[int] = []
    for q in runs[PREV]["expanded"]:
        k = cand(q, out)
        assert 0 <= k <= UNMOVE_MAX, hex(q)
        boards.extend(out[:k])
    assert len(boards) > 4 * len(runs[PREV]["expanded"])
    kinds = {"flipped": 0, "hand": 0}
    assert compare(boards, r0, r1, kinds, valid=False) == []
    assert all(kinds.values()), f"種類が揃っていない (テストが空振り): {kinds}"


def test_rank_is_the_same_on_random_valid_boards(built: dict[str, pathlib.Path]) -> None:
    """★rankValid が真になる乱数の盤 (固定の種. 到達しない盤も含めて番号の範囲の全体を突く) で,
    rankBoard の値が #38 と同じ。ライオンの全 132 通りの置き方を通す。"""
    r0, r1 = ranker(built[PREV]), ranker(built[IMPL])
    boards = list(random_boards(N_RANDOM))
    kinds = {"flipped": 0, "hand": 0}
    assert compare(boards, r0, r1, kinds, valid=True) == []
    assert all(kinds.values()), f"種類が揃っていない (テストが空振り): {kinds}"
    assert len({lions(b) for b in boards}) == 132


def test_the_forward_search_is_byte_identical_to_impl_38(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #38 と同じ。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key


def test_the_whole_dat_is_byte_identical_to_impl_38(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析まで含めて, dat/ の全ファイルが #38 とバイト一致する
    (番号の値が同じなので, 発見済みの表・準備の配列・手数の配列の添字も同じ)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir())
    assert any(n.startswith("win003te") for n in names), "後退解析が浅すぎる (テストが空振り)"
    assert any(n.startswith("unknown") for n in names)
    for name in names:
        assert (da / name).read_bytes() == (db / name).read_bytes(), name
