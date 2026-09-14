"""前向き探索が本当に同じ答えを出すか、小さく実際に走らせて確かめる。

impl/03 は searchNext() の重複排除を「毎ラウンド全チャンクを読み直す」から
「常駐集合を1回引く」へ置き換えている。静的なテストでは「ループが消えた」までしか
言えないので、ここでは .so をビルドして本物の探索を数ラウンド回す。

チャンクの分かれ方は集合の反復順に依存するので、分割が起きる前の範囲でだけ
impl/02 と直接比較し、その先は順序に依存しない不変量で押さえる。
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import pickle
import shutil
import subprocess
import types
from collections.abc import Iterator

import pytest
from conftest import BASELINE_DIR, ROOT

# 分割が起きる前のラウンド数。記録 #2 の実測では最初のチャンク分割はラウンド11の書き出しで、
# そこまでは結果が一意に決まる。9ラウンドなら約2秒で済む。
ROUNDS_BEFORE_SPLIT = 9

# 分割を小さく起こすための上限。本番は 5,000,000。
SMALL_BOARD_NUM_MAX = 3000


@pytest.fixture(scope="session")
def shared_library(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """ベースラインの C を共有ライブラリにする。実装はどれも同じ .so を使う。"""
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    build = tmp_path_factory.mktemp("so")
    for name in ("animal_shogi.c", "animal_shogi.h"):
        shutil.copy(BASELINE_DIR / name, build / name)
    subprocess.run(
        ["gcc", "animal_shogi.c", "-o", "animal_shogi.so", "-Wall", "-fPIC", "-shared"],
        cwd=build,
        check=True,
        capture_output=True,
    )
    return build / "animal_shogi.so"


def load_impl(impl: str, work: pathlib.Path, so: pathlib.Path) -> types.ModuleType:
    """作業ディレクトリを作って実装を import する。

    実装は `./dat/` と `./kaiseki_log/` をカレント相対で使い、
    `CDLL("./animal_shogi.so")` も import 時のカレントを見るので、chdir してから読む。
    """
    (work / "dat").mkdir(parents=True)
    (work / "kaiseki_log").mkdir(parents=True)
    shutil.copy(so, work / "animal_shogi.so")
    shutil.copy(ROOT / "impl" / impl / "animal_shogi.py", work / "animal_shogi.py")

    spec = importlib.util.spec_from_file_location(f"impl_{impl}", work / "animal_shogi.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    cwd = pathlib.Path.cwd()
    os.chdir(work)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
    return module


def run_forward(
    module: types.ModuleType, work: pathlib.Path, rounds: int, board_num_max: int | None = None
) -> None:
    """searchNext() を rounds 回まわす。searchAll() ではなくこちらを使うのは、

    ログに時刻と経過秒が混ざると2つの実装を突き合わせられないため。
    """
    if board_num_max is not None:
        # モジュールの定数を差し替える (実行時に読まれるので後からで効く)
        vars(module)["BOARD_NUM_MAX"] = board_num_max
    cwd = pathlib.Path.cwd()
    os.chdir(work)
    try:
        for _ in range(rounds):
            if module.searchNext():
                break
    finally:
        os.chdir(cwd)


def families(dat: pathlib.Path) -> dict[str, frozenset[int]]:
    """dat/ の4系統を、系統ごとの盤面集合にして返す。チャンクの分かれ方は潰れる。"""
    prefixes = {
        "unknown": "unknown",
        "win": "win001te_",
        "lose": "lose000te_",
        "unexplored": "unexplored",
    }
    out: dict[str, frozenset[int]] = {}
    for key, prefix in prefixes.items():
        boards: set[int] = set()
        for path in sorted(dat.glob(f"{prefix}*.pickle")):
            with path.open("rb") as f:
                boards |= set(pickle.load(f))
        out[key] = frozenset(boards)
    return out


def sublog(work: pathlib.Path) -> str:
    return (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")


def test_impl_03_gives_the_same_forward_search_as_impl_02(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """分割が起きる前の範囲では、成果物もログも一致しなければならない。"""
    runs: dict[str, pathlib.Path] = {}
    for impl in ("02_resident_wins", "03_resident_seen"):
        work = tmp_path / impl
        module = load_impl(impl, work, shared_library)
        run_forward(module, work, ROUNDS_BEFORE_SPLIT)
        runs[impl] = work

    a, b = runs["02_resident_wins"], runs["03_resident_seen"]
    fam_a, fam_b = families(a / "dat"), families(b / "dat")
    assert sum(len(v) for v in fam_a.values()) > 100_000, "探索が進んでいない (テストが空振り)"
    for key in fam_a:
        assert fam_a[key] == fam_b[key], f"{key} の盤面集合が impl/02 と違う"
    assert sublog(a) == sublog(b), "サブログが impl/02 と食い違う"


@pytest.fixture
def split_run(
    shared_library: pathlib.Path, tmp_path: pathlib.Path
) -> Iterator[tuple[types.ModuleType, pathlib.Path]]:
    """チャンク分割が何度も起きる状態まで impl/03 を進める。"""
    work = tmp_path / "split"
    module = load_impl("03_resident_seen", work, shared_library)
    run_forward(module, work, rounds=40, board_num_max=SMALL_BOARD_NUM_MAX)
    yield module, work


def test_the_resident_set_equals_the_files_on_disk(
    split_run: tuple[types.ModuleType, pathlib.Path],
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
    assert module.seen_boards == union


def test_the_totals_match_what_is_on_disk(
    split_run: tuple[types.ModuleType, pathlib.Path],
) -> None:
    """main.log の総未知/総勝ち/総負けは、いまカウンタから出ている。

    記録 #2 は 99485568 / 140298614 / 7018985。ここがずれたら完走ログもずれる。
    """
    module, work = split_run
    fam = families(work / "dat")
    assert module.tbn_uk == len(fam["unknown"])
    assert module.tbn_win == len(fam["win"])
    assert module.tbn_lose == len(fam["lose"])
