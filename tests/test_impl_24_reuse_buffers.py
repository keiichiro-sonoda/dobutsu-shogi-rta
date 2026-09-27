"""impl/24_reuse_buffers — 展開 (F1) の作業用配列を使い回す。

変数は1つ。`searchNext()` の F1 に `experiments/lever_scan_2/patches/reuse.patch` を入れた
(コードはパッチのまま、コメントだけを記録の実装として書き直した)。

- 勝ち・負け・未知の受け皿3本を、毎ラウンド n 件ぶん新しく確保して 0 で埋めるのをやめ、
  最初のラウンドで `BOARD_NUM_MAX` 件ずつ1回だけ確保して上書きする (`_exp_bufs`)
- 入力は待ち行列の塊をそのまま渡す (写しの `arr` をやめる)
- 受け皿からは件数ぶんを `memoryview` で見て `frombytes` で足す (スライスの写しをやめる)

⚠️ 受け皿を 0 で埋め直さないので、前のラウンドの残りが読まれないことが要。
受け皿にあらかじめゴミを詰めて走らせても、ラウンドごとの件数・待ち行列・未知の並び・終端・
P0 の詰め方・成果物が impl/23 とバイト一致することまで見る。
C・`.h`・`Makefile` は impl/23 とバイト同一 (`.so` が変わらない)。
"""

from __future__ import annotations

import ast
import io
import itertools
import pathlib
import re
import shutil
import subprocess
import tokenize
from array import array
from collections import deque
from typing import Any

import pytest
from conftest import ROOT, chdir, impl_library, load_impl
from test_impl_22_in_memory import SMALL_BOARD_NUM_MAX, limited_run, statements, top_level

IMPL = "24_reuse_buffers"
PREV = "23_loop_prefetch"
IMPL_DIR = ROOT / "impl" / IMPL
PREV_DIR = ROOT / "impl" / PREV
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"
PATCH = ROOT / "experiments" / "lever_scan_2" / "patches" / "reuse.patch"

# 受け皿にあらかじめ詰めておくゴミ。盤面のパック値は 48 bit に収まるので、本物とは混ざらない
POISON = 0xDEAD_BEEF_DEAD_BEEF


def py_code(text: str) -> list[tuple[int, str]]:
    """Python のトークン列からコメントと空行を落とす。コメントの書き直しを無視して比べる。"""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return [(t.type, t.string) for t in tokens if t.type not in (tokenize.COMMENT, tokenize.NL)]


def search_next() -> str:
    return top_level(SOURCE, ast.FunctionDef)["searchNext"]


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_and_the_build_are_byte_identical_to_impl_23() -> None:
    """★C・`.h`・`Makefile` は impl/23 とバイト同一。`.so` が変わらないので関数の番地も動かない。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が impl/23 と違う"
        )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_the_python_is_impl_23_plus_the_reuse_patch(tmp_path: pathlib.Path) -> None:
    """★`.py` のコード (コメントを除く) が「impl/23 ＋ `reuse.patch`」と一致すること。"""
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    shutil.copy(PREV_SOURCE, tmp_path / "animal_shogi.py")
    with PATCH.open("rb") as f:
        done = subprocess.run(
            [
                "patch",
                "--forward",
                "--fuzz=0",
                "--no-backup-if-mismatch",
                "-p1",
                "-d",
                str(tmp_path),
            ],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, f"reuse.patch が impl/23 に当たらない:\n{done.stdout!r}"
    expected = py_code((tmp_path / "animal_shogi.py").read_text(encoding="utf-8"))
    assert py_code(SOURCE.read_text(encoding="utf-8")) == expected


def test_only_search_next_and_the_receivers_changed() -> None:
    """★変わった関数は `searchNext()` だけ。足した大域変数は受け皿の `_exp_bufs` だけ。

    後退解析 (`retreatAnalysis()` と P0 の `loadForwardResult()`) も、待ち行列の区切り
    (`queuePush()`) も触らない。
    """
    old, new = top_level(PREV_SOURCE, ast.FunctionDef), top_level(SOURCE, ast.FunctionDef)
    assert set(old) == set(new)
    assert {name for name in new if old[name] != new[name]} == {"searchNext"}
    old_a, new_a = top_level(PREV_SOURCE, ast.Assign), top_level(SOURCE, ast.Assign)
    assert set(new_a) - set(old_a) == {"_exp_bufs"}
    assert set(old_a) - set(new_a) == set()
    assert all(new_a[name] == old_a[name] for name in old_a), "既存の代入が変わっている"
    assert new_a["_exp_bufs"] == "_exp_bufs = None"


def test_the_receivers_are_allocated_once_and_the_copies_are_gone() -> None:
    """★受け皿は `_exp_bufs is None` のときだけ `BOARD_NUM_MAX` 件ずつ確保する。

    #23 までの毎ラウンドの確保 (`array("Q", bytes(8)) * n` を3本)、入力の写し
    (`array("Q", unexp_boards)`)、件数ぶんのスライスの写しは消えている。
    """
    code = "\n".join(statements(search_next()))
    assert 'array("Q", bytes(8)) * n' not in code
    assert 'array("Q", unexp_boards)' not in code
    assert "[:counts[" in code and code.count("memoryview(_exp_bufs[") == 3
    alloc = 'array("Q", bytes(8)) * BOARD_NUM_MAX'
    assert code.count(alloc) == 1
    guard = code.index("if _exp_bufs is None:")
    assert guard < code.index(alloc)
    # 受け皿から足すのは frombytes だけ (+= / extend で写しを作らない)
    for dst in ("catch_wins", "try_loses", "uk_all"):
        assert f"{dst}.frombytes(" in code
    assert "catch_wins +=" not in code and "uk_all.extend(" not in code


def test_the_size_check_comes_before_the_c_writes() -> None:
    """★塊が受け皿より大きければ、C が書き始める前に止める (C は受け皿の大きさを知らない)。"""
    code = "\n".join(statements(search_next()))
    check = code.index("if n > len(_exp_bufs[0]):")
    assert code.index("_exp_bufs = tuple(") < check < code.index("rc = expandRound(")


def test_a_chunk_larger_than_the_receivers_is_refused(tmp_path: pathlib.Path) -> None:
    """★待ち行列の塊が `BOARD_NUM_MAX` を超えていたら、展開せずに止まる。"""
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    work = tmp_path / "w"
    module = load_impl(IMPL, work, impl_library(IMPL))
    vars(module)["BOARD_NUM_MAX"] = 2
    with chdir(work):
        module.forwardInit()
        board = module.INITIAL_BOARD
        vars(module)["queue"] = deque([array("Q", [board, board, board])])
        probes = module.seenProbes()
        with pytest.raises(RuntimeError, match="受け皿に入らない"):
            module.searchNext()
    assert module.seenProbes() == probes, "止まる前に展開している"
    assert len(module._exp_bufs[0]) == 2


# --------------------------------------------------------------------------
# 走らせて impl/23 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """impl/23 と impl/24 を、同じ上限・同じラウンド数で打ち切って後退解析まで回す。

    impl/24 は2本。受け皿を最初のラウンドで確保する素の形と、受け皿にあらかじめゴミを
    詰めておいた形 (`poisoned`)。後者は「0 で埋め直さなくても前の残りを読まない」ことを見る。
    ⚠️ 実装を読み込むと前の実装の .so は閉じられるので、1つずつ最後まで回す。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out: dict[str, dict[str, Any]] = {}
    for name, impl in (("23", PREV), ("24", IMPL), ("poisoned", IMPL)):
        work = tmp_path_factory.mktemp(name)
        module = load_impl(impl, work, impl_library(impl))
        if name == "poisoned":
            bufs = tuple(array("Q", [POISON]) * SMALL_BOARD_NUM_MAX for _ in range(3))
            vars(module)["_exp_bufs"] = bufs
        out[name] = limited_run(module, work)
        if name == "poisoned":
            out[name]["injected"] = bufs
    return out


ARMS = ("24", "poisoned")


def test_the_run_is_long_enough_to_reuse_the_receivers(runs: dict[str, dict[str, Any]]) -> None:
    """テストが空振りしていないこと: 何ラウンドも回り、塊が受け皿いっぱいのラウンドがある。"""
    counts = runs["24"]["counts"]
    assert len(counts) > 10
    assert max(c["n_in"] for c in counts) == SMALL_BOARD_NUM_MAX
    # 3本それぞれに、前のラウンドより少ない件数を書くラウンドがある (受け皿に前の残りが居る状態)
    for key in ("n_win", "n_lose", "n_uk"):
        shrink = [b[key] < a[key] for a, b in itertools.pairwise(counts)]
        assert any(shrink), f"{key} が一度も前のラウンドより減らない"


def test_the_receivers_are_kept_across_rounds(runs: dict[str, dict[str, Any]]) -> None:
    """★受け皿は確保し直されない。ゴミを詰めて渡した配列が、最後まで同じものとして使われる。"""
    module = runs["poisoned"]["module"]
    assert module._exp_bufs is runs["poisoned"]["injected"]
    assert [len(b) for b in runs["24"]["module"]._exp_bufs] == [SMALL_BOARD_NUM_MAX] * 3


@pytest.mark.parametrize("arm", ARMS)
def test_the_rounds_agree_with_impl_23(runs: dict[str, dict[str, Any]], arm: str) -> None:
    """★ラウンドごとの件数 (`forward.tsv` の件数の列と同じ値) が impl/23 と一致する。"""
    assert runs[arm]["counts"] == runs["23"]["counts"]


HANDED = ["queue", "uk_all", "catch_wins", "try_loses", "tbn", "packed", "n"]


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("key", HANDED)
def test_the_memory_handed_to_p0_agrees_with_impl_23(
    runs: dict[str, dict[str, Any]], arm: str, key: str
) -> None:
    """★P0 に渡る待ち行列・未知の並び・終端の2本と、P0 が詰めたバイト列が impl/23 と一致する。"""
    assert runs[arm][key] == runs["23"][key]


@pytest.mark.parametrize("arm", ARMS)
def test_the_artifacts_are_byte_identical_to_impl_23(
    runs: dict[str, dict[str, Any]], arm: str
) -> None:
    """★後退解析まで回した成果物が impl/23 とバイト一致する。"""
    da, db = runs["23"]["work"] / "dat", runs[arm]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


@pytest.mark.parametrize("arm", ARMS)
def test_the_logs_agree_with_impl_23(runs: dict[str, dict[str, Any]], arm: str) -> None:
    """★サブログと手数別の行が impl/23 と一致する (落とすのは時刻と経過時間の行だけ)。"""
    clock = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$|経過$")

    def sub(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if not clock.search(ln)]

    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    wa, wb = runs["23"]["work"], runs[arm]["work"]
    assert sub(wa) == sub(wb)
    assert totals(wa) == totals(wb)
    assert len(totals(wb)) > 2, "手数別の行がほとんど出ていない (テストが空振り)"
