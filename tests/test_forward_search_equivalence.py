"""前向き探索が本当に同じ答えを出すかを、小さく実際に走らせて確かめる。

impl/03 は searchNext() の重複排除をメモリ常駐に置き換えた。静的なテストでは
「読み直しのループが消えた」までしか言えないので、ここでは .so をビルドして
本物の探索を数ラウンド回し、直前の実装と成果物が一致することを見る。

impl/04 は全探索を1バイトも触っていないので、ここが一致することが
「後退解析しか変えていない」＝対照群が成立することの担保になる。
"""

from __future__ import annotations

import pathlib

import pytest
from conftest import families, load_impl, run_forward

# 記録 #2 の実測では、最初のチャンク分割はラウンド11 の書き出しで起きる。
# そこまでは結果が一意に決まるので、直接比較できる。9ラウンドなら約2秒。
ROUNDS_BEFORE_SPLIT = 9

# 分割を小さく起こすための上限。本番は 5,000,000。
SMALL_BOARD_NUM_MAX = 3000

# (前の実装, 次の実装)。全探索を変えたのは #3 だけで、#4 は無変更。
PAIRS = [
    ("02_resident_wins", "03_resident_seen"),
    ("03_resident_seen", "04_resident_unknown"),
    ("04_resident_unknown", "05_batch_wl_write"),
    ("05_batch_wl_write", "06_csr_counter"),
]


@pytest.mark.parametrize(("prev", "cur"), PAIRS)
def test_the_forward_search_is_unchanged_from_the_previous_impl(
    prev: str, cur: str, shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """分割が起きる前の範囲では、成果物もログも一致しなければならない。"""
    works: dict[str, pathlib.Path] = {}
    for impl in (prev, cur):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS_BEFORE_SPLIT)
        works[impl] = work

    fam_a, fam_b = families(works[prev] / "dat"), families(works[cur] / "dat")
    assert sum(len(v) for v in fam_a.values()) > 100_000, "探索が進んでいない (テストが空振り)"
    for key in fam_a:
        assert fam_a[key] == fam_b[key], f"{key} の盤面集合が impl/{prev} と違う"

    def sublog(work: pathlib.Path) -> str:
        return (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")

    assert sublog(works[prev]) == sublog(works[cur]), f"サブログが impl/{prev} と食い違う"


@pytest.fixture
def split_run(shared_library: pathlib.Path, tmp_path: pathlib.Path) -> tuple[object, pathlib.Path]:
    """チャンク分割が何度も起きる状態まで impl/04 (＝最新) を進める。"""
    work = tmp_path / "split"
    module = load_impl(PAIRS[-1][1], work, shared_library)
    run_forward(module, work, rounds=40, board_num_max=SMALL_BOARD_NUM_MAX)
    return module, work


def test_the_resident_set_equals_the_files_on_disk(
    split_run: tuple[object, pathlib.Path],
) -> None:
    """常駐集合は「発見済み盤面の全体」＝4系統の和集合であり続けること。

    ここが崩れると、すでに見た盤面をもう一度未探索に積んでしまう (＝答えが壊れる)。
    順序に依存しないので、チャンクの分かれ方が変わっても成立する。
    """
    module, work = split_run
    fam = families(work / "dat")
    assert len(fam["unexplored"]) > SMALL_BOARD_NUM_MAX, "分割が起きていない (テストが空振り)"

    union: set[int] = set()
    for boards in fam.values():
        assert not (union & boards), "4系統が互いに素でない"
        union |= boards
    assert vars(module)["seen_boards"] == union


def test_the_totals_match_what_is_on_disk(split_run: tuple[object, pathlib.Path]) -> None:
    """main.log の総未知/総勝ち/総負けは、いまカウンタから出ている。

    記録 #3 は 99485568 / 140298614 / 7018985。ここがずれたら完走ログもずれる。
    """
    module, work = split_run
    fam = families(work / "dat")
    assert vars(module)["tbn_uk"] == len(fam["unknown"])
    assert vars(module)["tbn_win"] == len(fam["win"])
    assert vars(module)["tbn_lose"] == len(fam["lose"])
