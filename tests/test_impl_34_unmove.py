"""impl/34_unmove — 後退解析を「一手前を直接作る」作りに替える。

#33 までの後退解析は、全探索の結果に連番を振り (P0)、番号を引く索引を作り (P1)、
未知局面の後続を全部作り (P2)、向きを逆にして前任の表に並べ替え (P4)、
174段ループでその表を引いていた。#34 では、全探索が展開した局面ごとに、
種類とキャッチ抜きの数をランクを添字にした 1 バイトの配列に書いておき、
後退解析では決まった局面から手を1つ戻して前任をその場で作る
(実験 unmove_bench〜forward_prep の形)。P0〜P4 と 174段ループの関数は消した。

ここで固定するもの:

- 差分の範囲 (`Makefile` は #33 とバイト同一。ファイルの顔ぶれは #33 と同じ)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  **詰め物の検査** (熱くない場所に関数を足しても、熱い関数の番地が動かない。#33 から写した)
- 打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・後退解析に渡す3本の列) が
  #33 と同じこと
- 全探索が書く準備の配列が、展開した局面の全部で、いまの生成器から数え直した値と同じこと
- 打ち切った全探索のあとの後退解析の答え (手数ごとの勝ち・負けの集合と引き分けの集合) が、
  同じ規則を Python で素直に書いた参照解と同じこと

⚠️ 打ち切った全探索の上では、後退解析の答えは #33 と同じにならない。#33 は
   「索引の外の後続」(まだ展開していない局面) を出次数に数えて決まらないまま残すが、
   #34 はキャッチ局面の形の後続を最初から数えないので、まだ展開していない
   キャッチ局面の形の後続だけが残った局面が決まりうる (全探索を最後まで回せば、
   どちらも同じ答えになる)。だから #33 とは比べず、#34 の規則の参照解と比べる。
   最後まで回した答えは、門番と本走のオラクルと指紋で見る。
"""

from __future__ import annotations

import ctypes
import pathlib
import re
import shutil
import types
from array import array
from collections import defaultdict
from typing import Any

import conftest
import pytest
from conftest import ROOT, chdir, load_impl
from test_impl_22_in_memory import COUNTS, ROUNDS, SMALL_BOARD_NUM_MAX
from test_impl_33_hot_layout import make, sections, symbols

IMPL = "34_unmove"
PREV = "33_hot_layout"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"

# 熱い関数 (F1 と後退解析のループ・初期化・引き分けを拾う段で実行される C の関数)。並びは C
# のファイルの順
HOT = (
    "invBoard",
    "nextBoardInvNormal",
    "nextBoardInvNormalNC",
    "nextBoardSeenNormal",
    "expandRound",
    "unmoveCandidates",
    "unmoveInit",
    "unmoveStep",
    "unmoveDraws",
)

# #33 で消した関数 (P1・P2・P4・174段ループと、連番からパック値への翻訳)
GONE = (
    "indexBuild",
    "indexFree",
    "nextBoardIndexNormal",
    "predCount",
    "predScatter",
    "retreatStep",
    "buildSuccRange",
    "gatherPacked",
    "gatherDraws",
)

PAD_AT = {
    "top": '#include "animal_shogi.h"\n',
    "mid": "int nextBoardSeenNormal(u_long b, uint32_t rb, u_long *out, uint32_t *out_rank) {",
}
PAD_SIZES = (8, 24, 40, 100, 1000)

PREP_TRY = 0xFE
PREP_CATCH = 0xFF


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def padded(c: str, where: str, n: int) -> str:
    """熱くない関数 (`n` バイトの `nop` を持つだけ) を1つ足した `.c` (#33 のテストと同じ形)。"""
    body = f'__asm__ volatile(".skip {n}, 0x90");'
    pad = f"__attribute__((used, noinline)) void layoutPad(void) {{ {body} }}\n"
    if where == "end":
        return c + pad
    anchor = PAD_AT[where]
    assert c.count(anchor) == 1, anchor
    if where == "top":
        return c.replace(anchor, anchor + pad)
    return c.replace(anchor, pad + anchor)


def hot_addresses(so: pathlib.Path) -> tuple[int, ...]:
    table = symbols(so)
    return tuple(table[fn][0] for fn in HOT)


@pytest.fixture(scope="module")
def tools() -> None:
    for tool in ("gcc", "make", "nm", "objdump", "readelf"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")


@pytest.fixture(scope="module")
def built(tools: None, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    root = tmp_path_factory.mktemp("make")
    return {impl: make(ROOT / "impl" / impl, root / impl) for impl in (PREV, IMPL)}


# --------------------------------------------------------------------------
# 差分の範囲と置き場所
# --------------------------------------------------------------------------


def test_the_makefile_is_byte_identical_to_impl_33() -> None:
    """★ビルドの指定 (gcc 行とリンカースクリプトの使い方) は #33 と同じ。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes()


def test_the_files_are_the_same_five_as_impl_33() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_linker_script_lists_the_hot_functions_in_order() -> None:
    """★リンカースクリプトの一覧とこのテストの `HOT` が同じ (どちらかだけ直すと落ちる)。"""
    listed = re.findall(r"\*\(\.text\.(\w+)\)", text(IMPL_DIR / LD))
    assert tuple(listed) == HOT


def test_every_hot_function_is_defined_in_the_c_and_the_old_retreat_is_gone() -> None:
    c = text(IMPL_DIR / "animal_shogi.c")
    for fn in HOT:
        assert re.search(rf"^\S[^;]*\b{fn}\(", c, re.M), fn
    # 歴史を書いたコメントには名前が残ってよい. コードだけを見る
    c = re.sub(r"//.*", "", c)
    py = re.sub(r"#.*", "", text(IMPL_DIR / "animal_shogi.py"))
    for fn in GONE:
        assert not re.search(rf"\b{fn}\(", c), f"{fn} が C に残っている"
        assert not re.search(rf"\b{fn}\b", py), f"{fn} が Python に残っている"


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


def test_padding_does_not_move_the_hot_functions(tools: None, tmp_path: pathlib.Path) -> None:
    """★詰め物の検査 (#33 から写した)。熱くない関数をファイルの頭・熱い関数の間・末尾に足しても、
    熱い関数の番地は1つも動かない。まだ使っていない libc の関数を呼んで `.plt` を伸ばしても、
    熱い関数のページの中の位置は動かない。"""
    c = text(IMPL_DIR / "animal_shogi.c")
    base = hot_addresses(make(IMPL_DIR, tmp_path / "base"))
    for where in ("top", "mid", "end"):
        for n in PAD_SIZES:
            got = hot_addresses(make(IMPL_DIR, tmp_path / f"{where}-{n}", padded(c, where, n)))
            assert got == base, (where, n)
    # `.plt` を伸ばすと, 区画の前の区画が 4 KiB の区切りをまたぐことがある (#34 ではまたいで,
    # 区画ごと
    # 1ページ後ろへずれる). リンカースクリプトが約束しているのは「ページの中の位置」なので,
    # 区画の先頭からの
    # 位置と, 先頭が 4 KiB の区切りであることを見る (#33 ではまたがず, 番地そのものが動かなかった)
    plt = (
        c
        + "#include <unistd.h>\n"
        + "__attribute__((used, noinline)) int layoutPadPid(void) { return (int)getpid(); }\n"
    )
    got = hot_addresses(make(IMPL_DIR, tmp_path / "plt", plt))
    assert got[0] % 4096 == 0
    assert [a - got[0] for a in got] == [a - base[0] for a in base]


# --------------------------------------------------------------------------
# 打ち切った全探索と、そのあとの後退解析
# --------------------------------------------------------------------------


def limited_forward(module: types.ModuleType, work: pathlib.Path) -> dict[str, Any]:
    """`searchAll()` を ROUNDS ラウンドで打ち切る。

    打ち切り方は `test_impl_22_in_memory.limited_run` と同じ。後退解析に渡す3本の列と
    待ち行列を拾って返す。"""
    counts: list[dict[str, int]] = []
    real_next = module.searchNext

    def limited() -> bool:
        flag = bool(real_next())
        counts.append({k: module._prof.get(k, 0) for k in COUNTS})
        return flag or len(counts) >= ROUNDS

    vars(module)["searchNext"] = limited
    vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
    with chdir(work):
        module.searchAll()
    return {
        "counts": counts,
        "queue": [a.tobytes() for a in module.queue],
        "uk_all": module.uk_all.tobytes(),
        "catch_wins": module.catch_wins.tobytes(),
        "try_loses": module.try_loses.tobytes(),
        "tbn": (module.tbn_uk, module.tbn_win, module.tbn_lose),
    }


@pytest.fixture(scope="module")
def runs(
    built: dict[str, pathlib.Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """#33 と #34 を同じところで打ち切る。#34 は続けて後退解析まで回す。
    ⚠️ `load_impl()` は自前の C を持つ実装に `conftest.impl_library()` (-O0 の自前の gcc 行) の
    `.so` を差し込むので、Makefile で作った `.so` に差し替える (#33 のテストと同じ)。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in (PREV, IMPL):
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            out[impl] = limited_forward(module, work)
            out[impl]["work"] = work
            if impl == IMPL:
                out[impl]["prep"] = prep_values(module)
                with chdir(work):
                    module.retreatAnalysis()
                out[impl]["module"] = module
    return out


def prep_values(module: types.ModuleType) -> dict[int, int]:
    """展開した局面 (後退解析に渡す3本の列) ごとの、準備の配列の値。"""
    lib = module.lib
    lib.prepPtr.restype = ctypes.c_void_p
    base = lib.prepPtr()
    assert base
    got = {}
    for name in ("uk_all", "catch_wins", "try_loses"):
        for b in getattr(module, name):
            got[b] = ctypes.c_uint8.from_address(base + module.rankBoard(b)).value
    return got


def test_the_forward_search_agrees_with_impl_33(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #33 と同じ。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key
    forward_files = ("win001te_*.bin", "lose000te_*.bin")
    for pattern in forward_files:
        names = sorted(p.name for p in (a["work"] / "dat").glob(pattern))
        assert names, pattern
        for name in names:
            got = (b["work"] / "dat" / name).read_bytes()
            assert (a["work"] / "dat" / name).read_bytes() == got, name


def successors(module: types.ModuleType, b: int) -> list[int]:
    buf = module.c_uint64_array48()
    n = module.nextBoardInvNormal(b, buf)
    return list(buf[:n]) if n > 0 else []


def is_catch(module: types.ModuleType, b: int) -> bool:
    return bool(module.nextBoardInvNormal(b, module.c_uint64_array48()) == 0)


def test_the_prep_array_matches_the_generator(runs: dict[str, dict[str, Any]]) -> None:
    """★展開した全局面で、準備の配列の値が、いまの生成器で数え直した値と同じ。"""
    module, prep = runs[IMPL]["module"], runs[IMPL]["prep"]
    assert len(prep) > 10000
    zero = 0
    for b, v in prep.items():
        n = module.nextBoardInvNormal(b, module.c_uint64_array48())
        if n == 0:
            assert v == PREP_CATCH, hex(b)
        elif n < 0:
            assert v == PREP_TRY, hex(b)
        else:
            k = sum(not is_catch(module, s) for s in successors(module, b))
            zero += k == 0
            assert v == k + 1, hex(b)
    assert zero > 0, "キャッチ抜きの数が 0 の局面が無い (テストが空振り)"


def reference(module: types.ModuleType) -> tuple[dict[tuple[int, str], set[int]], set[int]]:
    """#34 の規則を Python で素直に書いた後退解析 (打ち切った全探索の上)。

    未知局面 p の残りの数は、後続のうちキャッチ局面の形でないものの数 (重複込み)。
    トライ負けは手数 0 の負け、キャッチ局面は手数 1 の勝ちで前任をたどらない、
    残りの数が 0 の未知局面は手数 2 の負け。手数 nd の段は、手数 nd − 1 で決まった局面 q から、
    q を後続に持つ未定の未知局面 p (辺の重複込み) をたどる。
    """
    uk = list(module.uk_all)
    pred: dict[int, list[int]] = defaultdict(list)
    cnt: dict[int, int] = {}
    for p in uk:
        succ = successors(module, p)
        cnt[p] = sum(not is_catch(module, s) for s in succ)
        for s in succ:
            pred[s].append(p)
    dtm: dict[int, int] = {}
    zeros = [p for p in uk if cnt[p] == 0]
    for p in zeros:
        dtm[p] = 2
    out: dict[tuple[int, str], set[int]] = {}
    frontier = list(module.try_loses)
    nd = 1
    while True:
        found = []
        for q in frontier:
            for p in pred.get(q, ()):
                if p in dtm:
                    continue
                if nd % 2 == 0:
                    cnt[p] -= 1
                    if cnt[p]:
                        continue
                dtm[p] = nd
                found.append(p)
        if nd == 2:
            found += zeros
        out[(nd, "win" if nd % 2 else "lose")] = set(found)
        if not found:
            break
        frontier = found
        nd += 1
    return out, {p for p in uk if p not in dtm}


def read_dat(dat: pathlib.Path) -> tuple[dict[tuple[int, str], list[int]], list[int]]:
    got: dict[tuple[int, str], list[int]] = defaultdict(list)
    draws: list[int] = []
    for path in sorted(dat.glob("*.bin")):
        a = array("Q")
        a.frombytes(path.read_bytes())
        if m := re.match(r"^(win|lose)(\d+)te_\d+\.bin$", path.name):
            got[(int(m.group(2)), m.group(1))].extend(a)
        elif path.name.startswith("unknown"):
            draws.extend(a)
    return got, draws


def test_the_retreat_agrees_with_the_reference(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析の答えが、#34 の規則の参照解と同じ。

    手数ごとの勝ち・負けの集合 (1手勝ちは全探索が書いたキャッチ局面を除く、
    0手負けは全探索が書いたトライ負け) と、引き分けの集合。どのファイルにも同じ局面は2回出ない。
    """
    module, work = runs[IMPL]["module"], runs[IMPL]["work"]
    want, want_draws = reference(module)
    got, draws = read_dat(work / "dat")
    catch = array("Q")
    catch.frombytes(runs[IMPL]["catch_wins"])
    tries = array("Q")
    tries.frombytes(runs[IMPL]["try_loses"])
    assert len(want) > 5, f"手数が浅すぎる (テストが空振り): {sorted(want)}"
    assert sorted(got.pop((0, "lose"))) == sorted(tries)
    win1 = got.pop((1, "win"))
    assert sorted(win1) == sorted(list(catch) + list(want.pop((1, "win"))))
    for key, values in got.items():
        assert len(values) == len(set(values)), key
    assert {k: set(v) for k, v in got.items()} == {k: v for k, v in want.items() if k != (1, "win")}
    assert len(draws) == len(set(draws))
    assert set(draws) == want_draws
    assert want_draws, "引き分けが無い (テストが空振り)"


def test_the_retreat_summary_has_the_new_spans(runs: dict[str, dict[str, Any]]) -> None:
    """後退解析の区間は U_init・U_loop・U_draw・U_uk と合計。残差を出すための境界も全部ある。"""
    rows = dict(
        line.split("\t", 1)
        for line in text(runs[IMPL]["work"] / "kaiseki_log" / "retreat_summary.tsv").splitlines()
    )
    spans = ("U_init", "U_loop", "U_draw", "U_uk")
    total = float(rows["retreat_total"])
    assert abs(sum(float(rows[s]) for s in spans) - total) < 1e-3
    for mark in ("R_start", *spans):
        for prefix in ("t_", "rss_", "hwm_", "min_", "maj_", "utime_", "stime_"):
            assert prefix + mark in rows, prefix + mark
    for key in ("anonhuge_init_kB", "anonhuge_loop_kB"):
        assert key in rows, key
