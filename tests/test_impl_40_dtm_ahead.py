"""impl/40_dtm_ahead — 後退解析の unmoveStep で, 手数の配列 (g_dtm) の先読みを1局面先にする。

#39 の unmoveStep は, フロンティアの局面 i の前任の候補を作って番号を出し, 手数の行を先読みした
**すぐあとに**同じ局面 i の候補の手数を読んでいた (実験 perf_39 で, その1行に U_loop の約 6 秒)。
#40 は実験 dtm_ahead の腕 ahead1 をそのまま移した: 候補と番号の配列を2組持ち, 局面 i の候補を
ふるう前に局面 i + 1 の候補を作って番号を出し, 先読みを頼む。候補を作ることと番号を出すことは
手数の配列も準備の配列も見ず, 局面 i をふるう・決めるのは局面 i − 1 を決め終えたあとなので,
決める順も found に積む順も #39 と同じ。dat/ も #39 とバイト一致する。

ここで固定するもの:

- 差分の範囲 (C は「#39 ＋ dtm_ahead の ahead1.patch」そのもの. ほかのファイルは #39 とバイト同一.
  変わった関数は unmoveStep だけで, ふるう・決めるの中身は1文字も変わらない)
- 関数の記号が #39 と同じ (新しい関数は無い)
- 熱い関数の一覧がリンカースクリプトと同じで、全部が専用の区画に一覧の順で並ぶこと。
  (詰め物の検査は tests/test_hot_layout_padding.py が, `hot_layout.ld` の中身ごとに1回回す)
- 打ち切った走行で, 全探索の出力が #39 と同じ。後退解析の手数ごとの unmoveStep の返り値・out[0..2]・
  found の中身 (並びまで) が #39 と同じで, dat/ の全ファイルが #39 とバイト一致する
- found があふれて途中で返る (-2) とき, 返り値・out・found の中身が #39 と同じ

⚠️ このファイルは .so を4回 (#39 と #40 を2回ずつ) 読み込む。tools/run_tests.py が1プロセスで回し,
ピークの RSS が上限 (8 GiB) の内に収まることを見る。
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

IMPL = "40_dtm_ahead"
PREV = "39_rank_lean"
IMPLS = (PREV, IMPL)
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
PATCH = ROOT / "experiments" / "dtm_ahead" / "patches" / "ahead1.patch"
LD = "hot_layout.ld"
SECTION = ".text.hot_layout"
FN = re.compile(r"^[^\s}][^;{}\n]*?\b(\w+)\(([^()]*)\)\s*\{", re.M)


def text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def bodies(c: str) -> dict[str, str]:
    """関数名 → 本体 (先頭から, 波括弧が閉じるところまで。コメントは除く)。
    関数名は, 引数の並びの前の最後の名前 (tests/test_impl_39_rank_lean.py と同じ読み方)。"""
    c = re.sub(r"//.*", "", c)
    out = {}
    for m in FN.finditer(c):
        depth, i = 0, m.end() - 1
        while True:
            depth += {"{": 1, "}": -1}.get(c[i], 0)
            if depth == 0:
                break
            i += 1
        out[m.group(1)] = c[m.start() : i + 1]
    return out


@pytest.fixture(scope="module")
def tools() -> None:
    import shutil

    for tool in ("gcc", "make", "nm", "objdump", "readelf", "patch"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")


@pytest.fixture(scope="module")
def built(tools: None, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    root = tmp_path_factory.mktemp("make")
    return {impl: make(ROOT / "impl" / impl, root / impl) for impl in IMPLS}


# --------------------------------------------------------------------------
# 差分の範囲と置き場所
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Makefile", "hot_layout.ld", "animal_shogi.h", "animal_shogi.py"])
def test_the_other_files_are_byte_identical_to_impl_39(name: str) -> None:
    """★C 以外 (ビルドの指定・熱い関数の一覧・ヘッダ・Python) は #39 とバイト同一。"""
    assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes()


def test_the_files_are_the_same_five_as_impl_39() -> None:
    names = sorted(p.name for p in IMPL_DIR.iterdir() if p.name != "__pycache__")
    assert names == sorted(p.name for p in PREV_DIR.iterdir() if p.name != "__pycache__")
    assert not (IMPL_DIR / "impl.env").exists()


def test_the_c_is_impl_39_plus_the_ahead1_patch(tools: None, tmp_path: pathlib.Path) -> None:
    """★C は #39 に dtm_ahead の ahead1.patch を当てたものそのもの (ほかの変更を混ぜない)。"""
    (tmp_path / "animal_shogi.c").write_bytes((PREV_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(tmp_path), "-i", str(PATCH)], check=True
    )
    assert (tmp_path / "animal_shogi.c").read_bytes() == (IMPL_DIR / "animal_shogi.c").read_bytes()


def test_only_unmovestep_changed() -> None:
    """★変わった関数は unmoveStep だけ。"""
    a, b = bodies(text(PREV_DIR / "animal_shogi.c")), bodies(text(IMPL_DIR / "animal_shogi.c"))
    assert sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)) == ["unmoveStep"]


def test_sieve_and_decide_are_unchanged() -> None:
    """★ふるう・決めるの中身 (ふるうループの頭から関数の終わりまで) は1文字も変わらない。
    g_prep の先読みもふるうループの中のまま。g_dtm の先読みは2か所 (ループの前と中) で
    引数は同じ。"""
    head = (
        "        for (int j = 0; j < nc; j++) {\n"
        "            if (g_dtm[r[j]] != DTM_UNDECIDED) continue;"
    )

    def step(c: str) -> str:
        body = c[c.index("int unmoveStep(") :]
        return body[: body.index("\n}\n") + 3]

    def tail(c: str) -> str:
        body = step(c)
        assert body.count(head) == 1
        return body[body.index(head) :]

    prev, cur = text(PREV_DIR / "animal_shogi.c"), text(IMPL_DIR / "animal_shogi.c")
    assert tail(cur) == tail(prev)
    assert "if (odd) __builtin_prefetch(&g_prep[r[j]], 1, 3);" in tail(prev)
    pref = re.compile(r"__builtin_prefetch\(&g_dtm\[.*\], (\d), (\d)\)")
    assert pref.findall(step(cur)) == [("1", "3")] * 2


def function_symbols(so: pathlib.Path) -> list[str]:
    out = subprocess.run(["nm", str(so)], check=True, capture_output=True, text=True).stdout
    return sorted(c[2] for ln in out.splitlines() if len(c := ln.split()) == 3 and c[1] in "tT")


def test_no_new_function_symbol(built: dict[str, pathlib.Path]) -> None:
    """★関数の記号 (nm の t / T) が #39 と同じ。熱い関数は増えない。"""
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


def recording(module: Any, calls: list[dict[str, Any]]) -> None:
    """module の unmoveStep を, 呼ぶたびに引数と結果を calls に積むものに差し替える。"""
    real = module.unmoveStep

    def step(front: Any, n: int, odd: int, nd: int, found: Any, cap: int, out: Any) -> int:
        rc = int(real(front, n, odd, nd, found, cap, out))
        got = list(out)
        calls.append({
            "n": n, "odd": odd, "nd": nd, "cap": cap, "rc": rc, "out": got,
            "found": [found[i] for i in range(got[0])],
        })  # fmt: skip
        return rc

    vars(module)["unmoveStep"] = step


@pytest.fixture(scope="module")
def runs(
    built: dict[str, pathlib.Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """#39 と #40 を同じところで打ち切り、どちらも続けて後退解析まで回す。
    ⚠️ `load_impl()` が差し込む -O0 の `.so` を, Makefile で作った `.so` に差し替える
    (#33 のテストと同じ)。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: built[impl])
        for impl in IMPLS:
            work = tmp_path_factory.mktemp(impl)
            module = load_impl(impl, work, built[impl])
            out[impl] = limited_forward(module, work)
            out[impl]["work"] = work
            calls: list[dict[str, Any]] = []
            recording(module, calls)
            with chdir(work):
                module.retreatAnalysis()
            out[impl]["calls"] = calls
    return out


def test_the_forward_search_is_byte_identical_to_impl_39(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索の出力 (ラウンドごとの件数・待ち行列・3本の列) が #39 と同じ。"""
    a, b = runs[PREV], runs[IMPL]
    assert len(a["counts"]) == ROUNDS
    for key in ("counts", "queue", "uk_all", "catch_wins", "try_loses", "tbn"):
        assert a[key] == b[key], key


def test_every_unmove_step_is_the_same_as_impl_39(runs: dict[str, dict[str, Any]]) -> None:
    """★手数ごとに, unmoveStep の返り値・out[0..2]・found の中身 (並びまで) が #39 と同じ。"""
    a, b = runs[PREV]["calls"], runs[IMPL]["calls"]
    assert len(a) >= 5, "後退解析が浅すぎる (テストが空振り)"
    assert any(c["odd"] and c["out"][0] for c in a) and any(not c["odd"] and c["out"][0] for c in a)
    assert any(c["n"] >= 100 for c in a), "フロンティアが小さすぎる (テストが空振り)"
    assert len(a) == len(b)
    for ca, cb in zip(a, b, strict=True):
        assert ca == cb, ca["nd"]


def test_the_whole_dat_is_byte_identical_to_impl_39(runs: dict[str, dict[str, Any]]) -> None:
    """★打ち切った全探索のあとの後退解析まで含めて, dat/ の全ファイルが #39 とバイト一致する。"""
    da, db = runs[PREV]["work"] / "dat", runs[IMPL]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir())
    assert any(n.startswith("win003te") for n in names), "後退解析が浅すぎる (テストが空振り)"
    assert any(n.startswith("unknown") for n in names)
    for name in names:
        assert (da / name).read_bytes() == (db / name).read_bytes(), name


# --------------------------------------------------------------------------
# found があふれて途中で返るとき (-2)
# --------------------------------------------------------------------------


def overflow(impl: str, so: pathlib.Path, work: pathlib.Path, last: int, cap: int) -> list[Any]:
    """打ち切った全探索のあと, 手数 1 から last − 1 までを Python の後退解析と同じに進め
    (手数 2 のあとに手数 2 の負けを足す), 手数 last を found の空きを cap にして呼ぶ。
    (返り値, out, found の中身) を手数ごとに返す。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: so)
        module = load_impl(impl, work, so)
        limited_forward(module, work)
    assert module.lib.unmoveInit() == 0
    u64 = ctypes.c_uint64
    room = len(module.uk_all) + 1
    front: Any = (u64 * room)(*module.try_loses)
    n = len(module.try_loses)
    res = []
    for nd in range(1, last + 1):
        found = (u64 * room)()
        out = (u64 * 3)()
        c = cap if nd == last else room
        rc = module.unmoveStep(front, n, (nd - 1) % 2, nd, found, c, out)
        res.append((rc, list(out), list(found)[: (out[0] if rc == 0 else c)]))
        front, n = found, out[0]
        if nd == 2:
            n += module.unmoveZeros(
                ctypes.cast(ctypes.addressof(found) + 8 * n, ctypes.POINTER(u64)), room - n
            )
    return res


def test_overflow_returns_the_same_as_impl_39(
    runs: dict[str, dict[str, Any]],
    built: dict[str, pathlib.Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """★前任の残りの数を減らす段 (odd) で, found がフロンティアの途中であふれたとき,
    返り値 -2・out (書かない)・それまでに積んだ found の中身が #39 と同じ。
    あふれさせる段は, 決まる数がいちばん多い odd の段。"""
    calls = runs[PREV]["calls"]
    last = max((c for c in calls if c["odd"]), key=lambda c: c["out"][0])
    cap = last["out"][0] // 2
    assert cap >= 10, "あふれさせる段が小さすぎる (テストが空振り)"
    got = {
        impl: overflow(impl, built[impl], tmp_path_factory.mktemp(f"of_{impl}"), last["nd"], cap)
        for impl in IMPLS
    }
    prev = got[PREV]
    assert [r[1] for r in prev[:-1]] == [c["out"] for c in calls[: last["nd"] - 1]]
    assert prev[-1][0] == -2 and prev[-1][1] == [0, 0, 0]
    assert prev[-1][2] == last["found"][:cap]
    assert got[IMPL] == prev
