"""実験 dtm_ahead の腕 ahead1 (記録試行ではない) — 後退解析の unmoveStep で, 手数の配列の
先読みを1局面先にする。

impl/39_rank_lean の unmoveStep は, フロンティアの局面 i の前任の候補を作って番号を出し, 手数の行を
先読みした**すぐあとに**同じ局面 i の候補の手数を読んでいた。ahead1 は候補と番号の配列を2組持ち,
局面 i の候補をふるう前に局面 i + 1 の候補を作って番号を出し, 先読みを頼む
(experiments/dtm_ahead/patches/ahead1.patch)。候補を作ることと番号を出すことは手数の配列を
見ず, 局面 i をふるう・決めるのは局面 i − 1 を決め終えたあとなので, 決める順も found に積む順も
変わらない。

ここで固定するもの (実験の一致の検査。完走の dat/ のバイト比較は実験の側で回す):

- パッチが変える関数は unmoveStep だけ。ふるう・決めるの中身は1文字も変わらない
- 関数の記号が #39 と同じ (新しい関数は無い)
- 打ち切った走行の後退解析で, 手数ごとの unmoveStep の返り値・out[0..2]・found の中身 (並びまで) が
  #39 と同じ。続く dat/ の全ファイルも #39 とバイト一致
- found があふれて途中で返る (-2) とき, 返り値・out・found の中身が #39 と同じ
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
from test_impl_33_hot_layout import make
from test_impl_34_unmove import limited_forward

IMPL = "39_rank_lean"
IMPL_DIR = ROOT / "impl" / IMPL
PATCH = ROOT / "experiments" / "dtm_ahead" / "patches" / "ahead1.patch"
ARMS = ("base", "ahead1")
FN = re.compile(r"^[^\s}][^;{}\n]*?\b(\w+)\(([^()]*)\)\s*\{", re.M)


def bodies(c: str) -> dict[str, str]:
    """関数名 → 本体 (先頭から, 波括弧が閉じるところまで。コメントは除く)。
    tests/test_impl_39_rank_lean.py の同名の関数と同じ読み方。"""
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
def patched(tmp_path_factory: pytest.TempPathFactory) -> str:
    import shutil

    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    work = tmp_path_factory.mktemp("patch")
    (work / "animal_shogi.c").write_bytes((IMPL_DIR / "animal_shogi.c").read_bytes())
    subprocess.run(
        ["patch", "--quiet", "--fuzz=0", "-p1", "-d", str(work), "-i", str(PATCH)], check=True
    )
    return (work / "animal_shogi.c").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built(patched: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    import shutil

    for tool in ("gcc", "make", "nm"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} が無い")
    root = tmp_path_factory.mktemp("make")
    return {
        "base": make(IMPL_DIR, root / "base"),
        "ahead1": make(IMPL_DIR, root / "ahead1", patched),
    }


def test_only_unmovestep_changes(patched: str) -> None:
    """★変わる関数は unmoveStep だけ。"""
    a, b = bodies((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")), bodies(patched)
    assert sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)) == ["unmoveStep"]


def test_sieve_and_decide_are_unchanged(patched: str) -> None:
    """★ふるう・決めるの中身 (ふるうループの頭から関数の終わりまで) は1文字も変わらない。
    g_prep の先読みもふるうループの中のまま, 先読みの引数も同じ。"""
    head = (
        "        for (int j = 0; j < nc; j++) {\n"
        "            if (g_dtm[r[j]] != DTM_UNDECIDED) continue;"
    )

    def tail(c: str) -> str:
        body = c[c.index("int unmoveStep(") :]
        body = body[: body.index("\n}\n") + 3]
        assert body.count(head) == 1
        return body[body.index(head) :]

    a = tail((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    assert tail(patched) == a
    assert "if (odd) __builtin_prefetch(&g_prep[r[j]], 1, 3);" in a
    step = patched[patched.index("int unmoveStep(") :]
    step = step[: step.index("\n}\n")]
    assert re.findall(r"__builtin_prefetch\(&g_dtm\[.*\], (\d), (\d)\)", step) == [("1", "3")] * 2


def function_symbols(so: pathlib.Path) -> list[str]:
    out = subprocess.run(["nm", str(so)], check=True, capture_output=True, text=True).stdout
    return sorted(c[2] for ln in out.splitlines() if len(c := ln.split()) == 3 and c[1] in "tT")


def test_no_new_function_symbol(built: dict[str, pathlib.Path]) -> None:
    assert function_symbols(built["ahead1"]) == function_symbols(built["base"])


# --------------------------------------------------------------------------
# 打ち切った走行の後退解析で, unmoveStep を手数ごとに比べる
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
    """2腕を同じところで打ち切り, 後退解析を最後まで回す。
    ⚠️ `load_impl()` が差し込む -O0 の `.so` を, Makefile で作った `.so` に差し替える
    (#33 のテストと同じ)。"""
    out: dict[str, dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as mp:
        for arm in ARMS:
            mp.setattr(conftest, "impl_library", lambda impl, arm=arm: built[arm])
            work = tmp_path_factory.mktemp(arm)
            module = load_impl(IMPL, work, built[arm])
            limited_forward(module, work)
            calls: list[dict[str, Any]] = []
            recording(module, calls)
            with chdir(work):
                module.retreatAnalysis()
            out[arm] = {"work": work, "calls": calls}
    return out


def test_every_step_is_the_same(runs: dict[str, dict[str, Any]]) -> None:
    """★手数ごとに, 返り値・out[0..2]・found の中身 (並びまで) が #39 と同じ。"""
    a, b = runs["base"]["calls"], runs["ahead1"]["calls"]
    assert len(a) >= 5, "後退解析が浅すぎる (テストが空振り)"
    assert any(c["odd"] and c["out"][0] for c in a) and any(not c["odd"] and c["out"][0] for c in a)
    assert any(c["n"] >= 100 for c in a), "フロンティアが小さすぎる (テストが空振り)"
    assert len(a) == len(b)
    for ca, cb in zip(a, b, strict=True):
        assert ca == cb, ca["nd"]


def test_the_whole_dat_is_byte_identical(runs: dict[str, dict[str, Any]]) -> None:
    """★後退解析の dat/ の全ファイルが #39 とバイト一致する。"""
    da, db = runs["base"]["work"] / "dat", runs["ahead1"]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir())
    assert any(n.startswith("win003te") for n in names), "後退解析が浅すぎる (テストが空振り)"
    for name in names:
        assert (da / name).read_bytes() == (db / name).read_bytes(), name


# --------------------------------------------------------------------------
# found があふれて途中で返るとき (-2)
# --------------------------------------------------------------------------


def overflow(so: pathlib.Path, work: pathlib.Path, last: int, cap: int) -> list[Any]:
    """打ち切った全探索のあと, 手数 1 から last − 1 までを Python の後退解析と同じに進め
    (手数 2 のあとに手数 2 の負けを足す), 手数 last を found の空きを cap にして呼ぶ。
    (返り値, out, found の中身) を手数ごとに返す。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(conftest, "impl_library", lambda impl: so)
        module = load_impl(IMPL, work, so)
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


def test_overflow_returns_the_same(
    runs: dict[str, dict[str, Any]],
    built: dict[str, pathlib.Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """★前任の残りの数を減らす段 (odd) で, found がフロンティアの途中であふれたとき,
    返り値 -2・out (書かない)・それまでに積んだ found の中身が #39 と同じ。
    あふれさせる段は, 決まる数がいちばん多い odd の段。"""
    calls = runs["base"]["calls"]
    last = max((c for c in calls if c["odd"]), key=lambda c: c["out"][0])
    cap = last["out"][0] // 2
    assert cap >= 10, "あふれさせる段が小さすぎる (テストが空振り)"
    got = {
        arm: overflow(built[arm], tmp_path_factory.mktemp(f"of_{arm}"), last["nd"], cap)
        for arm in ARMS
    }
    base = got["base"]
    assert [r[1] for r in base[:-1]] == [c["out"] for c in calls[: last["nd"] - 1]]
    assert base[-1][0] == -2 and base[-1][1] == [0, 0, 0]
    assert base[-1][2] == last["found"][:cap]
    assert got["ahead1"] == base
