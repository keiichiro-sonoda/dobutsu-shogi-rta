"""後退解析が本当に同じ答えを出すかを、小さく実際に走らせて確かめる。

impl/04 は未知盤面をディスクからメモリへ移した。取り出しが `set.pop()` から
`list.pop()` に変わり、`organizeUKFiles()` も消えるので、チャンクの分かれ方は
impl/03 と一致しない。そこで `tools/fingerprint_dat.py` の指紋
(深さごとの 件数・総和・XOR) で突き合わせる。要素の順序に依存しないので、
分割が変わっても「どの局面がどの手数か」まで比較できる。

全探索を途中で切った `dat/` を使う。局面の意味づけは本物の完全解析ではないが、
**同じ入力から同じ出力が出るか**の検査としてはこれで足り、数秒で終わる。
"""

from __future__ import annotations

import pathlib
import types

import fingerprint_dat
import pytest
from conftest import chdir, load_impl, load_pickles, run_forward, run_retreat

FORWARD_ROUNDS = 7

# 未知盤面が複数チャンクに割れる大きさにしておく。1チャンクだけだと
# uk_chunks[i] = new_uk_boards の差し替えが1回しか通らない。本番は 5,000,000。
SMALL_BOARD_NUM_MAX = 2000

PREV = "03_resident_seen"
CUR = "04_resident_unknown"


@pytest.fixture(scope="module")
def retreat_runs(
    shared_library: pathlib.Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, pathlib.Path]:
    """打ち切った dat/ を作り、両実装の後退解析を最後まで回す。"""
    out: dict[str, pathlib.Path] = {}
    for impl in (PREV, CUR):
        work = tmp_path_factory.mktemp(impl)
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)
        run_retreat(module, work)
        out[impl] = work
    return out


def test_the_artifacts_have_the_same_fingerprint(retreat_runs: dict[str, pathlib.Path]) -> None:
    """手数別に「どの局面がどの手数か」まで一致すること。"""
    a = fingerprint_dat.fingerprint(retreat_runs[PREV] / "dat")
    b = fingerprint_dat.fingerprint(retreat_runs[CUR] / "dat")
    assert a, "後退解析が何も確定していない (テストが空振り)"
    assert len(a) > 2, f"深さが1段しか進んでいない: {sorted(a)}"
    assert len(list((retreat_runs[CUR] / "dat").glob("unknown*.pickle"))) > 1, (
        "未知盤面が1チャンクしかない (テストが空振り)"
    )
    assert fingerprint_dat.compare(a, b) == []


def test_the_draws_are_written_back_as_artifacts(
    retreat_runs: dict[str, pathlib.Path],
) -> None:
    """最後まで未知だった盤面が成果物に残っていること。

    impl/04 は処理中ずっとメモリに置くので、最後に書き出さないと
    tools/fingerprint_dat.py が全局面を照合できなくなる。
    """
    a = load_pickles(retreat_runs[PREV] / "dat", "unknown*.pickle")
    b = load_pickles(retreat_runs[CUR] / "dat", "unknown*.pickle")
    assert a, "未知盤面が1つも残っていない (テストが空振り)"
    assert a == b


def test_the_main_log_agrees(retreat_runs: dict[str, pathlib.Path]) -> None:
    """手数別局面数の行が一致すること。オラクル検証が見るのはこの行。"""

    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    assert totals(retreat_runs[PREV]) == totals(retreat_runs[CUR])
    assert totals(retreat_runs[CUR]), "手数別局面数の行が出ていない"


def test_loading_the_unknown_boards_removes_the_files(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """読み込んだら消す。古い未知盤面が残っていると再開できそうに見えて中身が古い。"""
    work = tmp_path / "remove"
    module: types.ModuleType = load_impl(CUR, work, shared_library)
    run_forward(module, work, 7, SMALL_BOARD_NUM_MAX)
    dat = work / "dat"
    before = load_pickles(dat, "unknown*.pickle")
    assert len(list(dat.glob("unknown*.pickle"))) > 1, "未知盤面が1チャンクしかない (空振り)"

    with chdir(work):
        chunks = module.loadAllUnknownBoards()

    assert not list(dat.glob("unknown*.pickle")), "未知盤面ファイルが残っている"
    assert {b for chunk in chunks for b in chunk} == before
    assert all(isinstance(chunk, list) for chunk in chunks), "集合で持っている (リストで足りる)"
