"""後退解析が本当に同じ答えを出すかを、小さく実際に走らせて確かめる。

実装を1つ進めるたびに、直前の実装と成果物を突き合わせる。チャンクの分かれ方は
実装ごとに変わる（#4 は `set.pop()` → `list.pop()`、#5 は書き出しが深さ単位になる）ので、
`tools/fingerprint_dat.py` の指紋（深さごとの 件数・総和・XOR）で比較する。
要素の順序に依存しないので、分割が変わっても「どの局面がどの手数か」まで照合できる。

全探索を途中で切った `dat/` を使う。局面の意味づけは本物の完全解析ではないが、
**同じ入力から同じ出力が出るか**の検査としてはこれで足り、数秒で終わる。
終端で「4手負け 0件」に到達するので、**0件の深さでもファイルを作る**分岐も通る。
"""

from __future__ import annotations

import itertools
import pathlib
import shutil
import types

import fingerprint_dat
import pytest
from conftest import chdir, load_impl, load_pickles, run_forward, run_retreat

FORWARD_ROUNDS = 7

# 未知盤面が複数チャンクに割れる大きさにしておく。1チャンクだけだと
# uk_chunks[i] = new_uk_boards の差し替えが1回しか通らない。本番は 5,000,000。
SMALL_BOARD_NUM_MAX = 2000

# 後退解析をメモリ常駐にしていった順。隣り合う2つを突き合わせる。
IMPLS = (
    "03_resident_seen",
    "04_resident_unknown",
    "05_batch_wl_write",
    "06_csr_counter",
    "07_batch_forward_write",
    "08_c_index",
    "09_no_reslice",
    "10_setdiff",
    "11_c_seen",
    "12_c_predecessors",
)
PAIRS = list(itertools.pairwise(IMPLS))

# 未知盤面を常駐させている実装 (loadAllUnknownBoards を持つ)
RESIDENT_UNKNOWN = IMPLS[1:]


@pytest.fixture(scope="module")
def retreat_runs(
    shared_library: pathlib.Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, pathlib.Path]:
    """打ち切った dat/ を1つだけ作り、それを配って各実装の後退解析を最後まで回す。

    ⚠️ 実装ごとに全探索を回してはいけない。打ち切った時点の盤面集合は、実装の
    集合の反復順に依存する。チャンクの分かれ方が変わると次のラウンドで取り出す
    盤面が変わるので、同じ7ラウンドでも**別の集合**になる（impl/10 で差集合の
    書き方を変えたときに実際にそうなった）。完走すれば同じ答えに行き着くが、
    途中で切ったものどうしは比べられない。

    見たいのは「**同じ入力から同じ出力が出るか**」なので、入力を1つに固定する。
    """
    src = tmp_path_factory.mktemp("fixture")
    module = load_impl(IMPLS[0], src, shared_library)
    run_forward(module, src, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)

    out: dict[str, pathlib.Path] = {}
    for impl in IMPLS:
        work = tmp_path_factory.mktemp(impl)
        module = load_impl(impl, work, shared_library)
        for path in (src / "dat").iterdir():
            shutil.copy(path, work / "dat" / path.name)
        # run_forward を通さないので、上限は自分で入れる (writeUnknownChunks が読む)
        vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
        run_retreat(module, work)
        out[impl] = work
    return out


@pytest.mark.parametrize(("prev", "cur"), PAIRS)
def test_the_artifacts_have_the_same_fingerprint(
    prev: str, cur: str, retreat_runs: dict[str, pathlib.Path]
) -> None:
    """手数別に「どの局面がどの手数か」まで一致すること。"""
    a = fingerprint_dat.fingerprint(retreat_runs[prev] / "dat")
    b = fingerprint_dat.fingerprint(retreat_runs[cur] / "dat")
    assert a, "後退解析が何も確定していない (テストが空振り)"
    assert len(a) > 2, f"深さが1段しか進んでいない: {sorted(a)}"
    assert len(list((retreat_runs[cur] / "dat").glob("unknown*.pickle"))) > 1, (
        "未知盤面が1チャンクしかない (テストが空振り)"
    )
    assert fingerprint_dat.compare(a, b) == []


@pytest.mark.parametrize(("prev", "cur"), PAIRS)
def test_the_draws_are_written_back_as_artifacts(
    prev: str, cur: str, retreat_runs: dict[str, pathlib.Path]
) -> None:
    """最後まで未知だった盤面が成果物に残っていること。"""
    a = load_pickles(retreat_runs[prev] / "dat", "unknown*.pickle")
    b = load_pickles(retreat_runs[cur] / "dat", "unknown*.pickle")
    assert a, "未知盤面が1つも残っていない (テストが空振り)"
    assert a == b


@pytest.mark.parametrize(("prev", "cur"), PAIRS)
def test_the_main_log_agrees(prev: str, cur: str, retreat_runs: dict[str, pathlib.Path]) -> None:
    """手数別局面数の行が一致すること。オラクル検証が見るのはこの行。"""

    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    assert totals(retreat_runs[prev]) == totals(retreat_runs[cur])
    assert totals(retreat_runs[cur]), "手数別局面数の行が出ていない"


def test_the_win_lose_files_are_numbered_from_zero_without_gaps(
    retreat_runs: dict[str, pathlib.Path],
) -> None:
    """副番号は 0 から連番。読み手は「最初に無い番号」で打ち切る。

    #5 は深さごとに新しい副番号へ書くので、ここが崩れると後続の深さが読めなくなる。
    """
    dat = retreat_runs[IMPLS[-1]] / "dat"
    depths: dict[tuple[str, int], set[int]] = {}
    for path in dat.glob("*te_*.pickle"):
        kind = "win" if path.name.startswith("win") else "lose"
        depth, sub = path.stem.removeprefix(kind).split("te_")
        depths.setdefault((kind, int(depth)), set()).add(int(sub))
    assert depths, "win/lose ファイルが無い (テストが空振り)"
    for key, subs in sorted(depths.items()):
        assert subs == set(range(len(subs))), f"{key} の副番号が連番でない: {sorted(subs)}"


@pytest.mark.parametrize("impl", RESIDENT_UNKNOWN)
def test_loading_the_unknown_boards_removes_the_files(
    impl: str, shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """読み込んだら消す。古い未知盤面が残っていると再開できそうに見えて中身が古い。"""
    work = tmp_path / impl
    module: types.ModuleType = load_impl(impl, work, shared_library)
    run_forward(module, work, 7, SMALL_BOARD_NUM_MAX)
    dat = work / "dat"
    before = load_pickles(dat, "unknown*.pickle")
    assert len(list(dat.glob("unknown*.pickle"))) > 1, "未知盤面が1チャンクしかない (空振り)"

    with chdir(work):
        chunks = module.loadAllUnknownBoards()

    assert not list(dat.glob("unknown*.pickle")), "未知盤面ファイルが残っている"
    assert {b for chunk in chunks for b in chunk} == before
    assert all(isinstance(chunk, list) for chunk in chunks), "集合で持っている (リストで足りる)"
