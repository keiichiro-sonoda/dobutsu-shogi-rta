"""テスト共通の定数とフィクスチャ。"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import pickle
import shutil
import subprocess
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORACLE_DIR = ROOT / "oracle"
BASELINE_DIR = ROOT / "baseline"
RESULTS_DIR = ROOT / "results"

# (深さ, "win" | "lose", 局面数)
DistRow = tuple[int, str, int]


def load_distribution() -> list[DistRow]:
    rows: list[DistRow] = []
    text = (ORACLE_DIR / "distribution.tsv").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        depth, result, count = line.split("\t")
        rows.append((int(depth), result, int(count)))
    return rows


def load_totals() -> dict[str, int]:
    totals: dict[str, int] = {}
    text = (ORACLE_DIR / "totals.tsv").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("\t")[:2]
        totals[key] = int(value)
    return totals


@pytest.fixture(scope="session")
def distribution() -> list[DistRow]:
    return load_distribution()


@pytest.fixture(scope="session")
def totals() -> dict[str, int]:
    return load_totals()


# --------------------------------------------------------------------------
# 実装を実際に走らせるための道具
#
# 静的なテストでは「そう書いてある」までしか言えない。全探索も後退解析も、
# .so をビルドして本物を小さく動かし、実装どうしで成果物を突き合わせる。
# --------------------------------------------------------------------------


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

    spec = importlib.util.spec_from_file_location(
        f"impl_{impl}_{work.name}", work / "animal_shogi.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with chdir(work):
        spec.loader.exec_module(module)
    return module


class chdir:
    """カレントを一時的に移す。実装がカレント相対でファイルを読むため。"""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.saved = pathlib.Path.cwd()

    def __enter__(self) -> None:
        self.saved = pathlib.Path.cwd()
        os.chdir(self.path)

    def __exit__(self, *exc: object) -> None:
        os.chdir(self.saved)


def run_forward(
    module: types.ModuleType, work: pathlib.Path, rounds: int, board_num_max: int | None = None
) -> None:
    """searchNext() を rounds 回まわす。

    searchAll() ではなくこちらを使うのは、ログに時刻と経過秒が混ざると
    2つの実装を突き合わせられないため。

    impl/07 以降は終端盤面をメモリに貯めて searchAll() の最後に1回書くので、
    ラウンドを回しただけではディスクに出ない。searchAll() と同じ状態にするため、
    その書き出しだけ最後に呼ぶ (持っていない実装では何もしない)。
    """
    if board_num_max is not None:
        # モジュールの定数を差し替える (実行時に読まれるので後からで効く)
        vars(module)["BOARD_NUM_MAX"] = board_num_max
    with chdir(work):
        for _ in range(rounds):
            if module.searchNext():
                break
        flush = getattr(module, "flushTerminalBoards", None)
        if flush is not None:
            flush()


def run_retreat(module: types.ModuleType, work: pathlib.Path) -> None:
    """後退解析を最後まで回す。"""
    with chdir(work):
        module.retreatAnalysis()


def load_pickles(dat: pathlib.Path, pattern: str) -> set[int]:
    boards: set[int] = set()
    for path in sorted(dat.glob(pattern)):
        with path.open("rb") as f:
            boards |= set(pickle.load(f))
    return boards


def families(dat: pathlib.Path) -> dict[str, frozenset[int]]:
    """dat/ の4系統を、系統ごとの盤面集合にして返す。チャンクの分かれ方は潰れる。"""
    prefixes = {
        "unknown": "unknown*.pickle",
        "win": "win001te_*.pickle",
        "lose": "lose000te_*.pickle",
        "unexplored": "unexplored*.pickle",
    }
    return {k: frozenset(load_pickles(dat, v)) for k, v in prefixes.items()}
