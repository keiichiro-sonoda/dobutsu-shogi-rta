"""impl/37_mirror1 — 逆向きの生成器で鏡像を1回にする。

#36 の逆向きの生成器 `unmoveCandidates()` は, 手を指した直後の盤が q か鏡像の q のどちらかなので,
その両方 (q が左右対称なら q だけ) から手を戻し, 戻した p が正規形のものだけを残していた
(戻した盤の約半分を捨てていた). #37 では q だけから戻して正規化する
(実験 mirror1_keep の腕 mirror1。もとは unmove_gen)。辺の本数を変えないための2つの規則:

- q が左右対称でない: 戻した候補 c ごとに正規形 N(c) を出し, c が左右対称なら2回出す
- q が左右対称: 今までと同じく, c が正規形のものだけを残す

候補の多重集合は #36 と同じだが, 並びは変わる. だから後退解析が局面を決める順と, 後退解析の側の
dat/ の並びが変わる (#34 と同じ). 答えは手数ごとに束ねた集合で見る。

ここで固定するもの:

- 差分の範囲 (C は「#36 ＋ mirror1_keep の mirror1.patch」そのもの。
  ほかのファイルは #36 とバイト同一. 変わった関数は逆向きの生成器とその下請けだけ)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  (詰め物の検査は tests/test_hot_layout_padding.py が, `hot_layout.ld` の中身ごとに1回回す)
- 逆向きの生成器が, 打ち切った全探索で展開した局面とその前任の候補を q にして,
  候補の数と多重集合が #36 と同じ (左右対称な q と, 左右対称な候補が出る q を必ず含める)
- 打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・後退解析に渡す3本の列) が #36 と同じこと
- 打ち切った全探索のあとの後退解析の dat/ が, ファイルの名前と大きさ, 手数ごとに束ねた集合で
  #36 と同じこと (並びは比べない)

全局面 (到達可能な 246,803,167 局面) での一致の検査は experiments/mirror1_keep が行った
(この実装の .so は mirror1_keep の mirror1 の .so とバイト一致する。門番 #37 の README)。
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

IMPL = "37_mirror1"
PREV = "36_bb_unmove"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "mirror1_keep" / "patches" / "mirror1.patch"
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
def test_the_other_files_are_byte_identical_to_impl_36(name: str) -> None:
    """★C 以外 (ビルドの指定・熱い関数の一覧・ヘッダ・Python) は #36 とバイト同一。"""
    assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes()


def test_the_files_are_the_same_five_as_impl_36() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_c_is_impl_36_plus_the_mirror1_patch(tools: None, tmp_path: pathlib.Path) -> None:
    """★C は #36 に mirror1_keep の mirror1.patch を当てたものそのもの (ほかの変更を混ぜない)。"""
    (tmp_path / "animal_shogi.c").write_bytes((PREV_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(tmp_path), "-i", str(PATCH)], check=True
    )
    assert (tmp_path / "animal_shogi.c").read_bytes() == (IMPL_DIR / "animal_shogi.c").read_bytes()


def test_only_the_unmove_generator_and_its_helpers_changed() -> None:
    """変わった関数は逆向きの生成器 unmoveCandidates と下請けの unmoveRaw・unmovePiece・
    unmoveCaptures・unmoveEmit だけ. 表を作る関数・unmoveStep・全探索の側は変わらない。
    関数名は, 引数の並びの前の最後の名前 (`__attribute__((...))` を飛ばす)。"""
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
    assert changed == [
        "unmoveCandidates",
        "unmoveCaptures",
        "unmoveEmit",
        "unmovePiece",
        "unmoveRaw",
    ], changed
    assert "unmoveCandidates" in a and "unmoveCandidates" in b


def test_the_linker_script_lists_the_hot_functions_in_order() -> None:
    """★リンカースクリプトの一覧と `HOT` (#34 のテスト) が同じ。逆向きの生成器の名前は変えていない。
    新しい関数は無い。"""
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
    """#36 と #37 を同じところで打ち切り、どちらも続けて後退解析まで回す。
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


def unmover(so: pathlib.Path) -> Any:
    """その実装の逆向きの生成器。同じパスの .so を開き直す (表は中で作られる)。"""
    fn = ctypes.CDLL(str(so)).unmoveCandidates
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]
    return fn


def mirror(b: int) -> int:
    return ((b >> 48) << 48) | ((b & 0xFFFF) << 32) | (b & 0xFFFF0000) | ((b >> 32) & 0xFFFF)


def test_the_unmove_generator_agrees_with_impl_36_as_a_multiset(
    runs: dict[str, dict[str, Any]], built: dict[str, pathlib.Path]
) -> None:
    """★展開した局面とその前任の候補 (到達しない局面も混ざる) を q として, 前任の候補の数と
    多重集合が #36 と同じ (並びは比べない)。左右対称な q (正規形だけを残す規則) と,
    左右対称でない q で左右対称な候補が出る局面 (2回出す規則) を両方通したことも確かめる。"""
    g0, g1 = unmover(built[PREV]), unmover(built[IMPL])
    boards = runs[PREV]["expanded"]
    assert len(boards) > 10000
    a, b = (ctypes.c_uint64 * 1024)(), (ctypes.c_uint64 * 1024)()
    kinds = {"none": 0, "sym_q": 0, "sym_cand": 0, "order_differs": 0}
    queue, seen = list(boards), set(boards)
    for x in queue:
        r0, r1 = g0(x, a), g1(x, b)
        assert r0 == r1, hex(x)
        c0, c1 = list(a[:r0]), list(b[:r1])
        assert sorted(c0) == sorted(c1), hex(x)
        kinds["none"] += r0 == 0
        if mirror(x) == x:
            kinds["sym_q"] += r0 > 0
        elif any(mirror(c) == c for c in c0):
            kinds["sym_cand"] += 1
        kinds["order_differs"] += c0 != c1
        if len(queue) < 4 * len(boards):
            for c in c0:
                if c not in seen:
                    seen.add(c)
                    queue.append(c)
    assert all(kinds.values()), f"通したい局面が揃っていない (テストが空振り): {kinds}"


def test_the_forward_search_is_byte_identical_to_impl_36(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #35 と同じ
    (全探索は変えていない)。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key


def groups(d: pathlib.Path) -> dict[str, list[int]]:
    """名前の接頭辞 (lose002te など。手数と勝ち負け, 引き分けは unknown) ごとに,
    番号順に連結して並べ替えた局面。"""
    out: dict[str, list[int]] = {}
    for p in sorted(d.iterdir()):
        key = re.sub(r"_?\d+\.bin$", "", p.name)
        raw = p.read_bytes()
        out.setdefault(key, []).extend(
            int.from_bytes(raw[i : i + 8], "little") for i in range(0, len(raw), 8)
        )
    return {k: sorted(v) for k, v in out.items()}


def test_the_dat_has_the_same_sets_per_depth_as_impl_36(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析まで含めて, dat/ のファイルの名前と大きさが #36 と同じで,
    手数ごと (と引き分け) に束ねた局面の集合が #36 と同じ。並びは比べない
    (後退解析が局面を決める順が変わる)。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    sa = {p.name: p.stat().st_size for p in da.iterdir()}
    sb = {p.name: p.stat().st_size for p in db.iterdir()}
    assert sa == sb
    assert any(n.startswith("win003te") for n in sa), "後退解析が浅すぎる (テストが空振り)"
    assert any(n.startswith("unknown") for n in sa)
    ga, gb = groups(da), groups(db)
    assert ga.keys() == gb.keys()
    for k in ga:
        assert ga[k] == gb[k], k
        assert len(set(ga[k])) == len(ga[k]), f"{k} に重複がある"
