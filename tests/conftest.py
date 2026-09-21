"""テスト共通の定数とフィクスチャ。"""

from __future__ import annotations

import _ctypes
import atexit
import importlib.util
import os
import pathlib
import pickle
import shutil
import subprocess
import tempfile
import types
from array import array

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


def build_library(src: pathlib.Path, build: pathlib.Path) -> pathlib.Path:
    """C を共有ライブラリにする。フラグは baseline の Makefile と同じ (-O0)。"""
    for name in ("animal_shogi.c", "animal_shogi.h"):
        shutil.copy(src / name, build / name)
    subprocess.run(
        ["gcc", "animal_shogi.c", "-o", "animal_shogi.so", "-Wall", "-fPIC", "-shared"],
        cwd=build,
        check=True,
        capture_output=True,
    )
    return build / "animal_shogi.so"


@pytest.fixture(scope="session")
def shared_library(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """ベースラインの C を共有ライブラリにする。

    C が baseline とバイト同一な実装 (#7 まで) はこれをそのまま使う。
    自前の C を持つ実装は load_impl() が別にビルドする。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    return build_library(BASELINE_DIR, tmp_path_factory.mktemp("so"))


# 自前の C を持つ実装の .so。同じ実装を何度も読むのでセッション内で使い回す
_impl_libraries: dict[str, pathlib.Path] = {}


def impl_library(impl: str) -> pathlib.Path:
    """実装ディレクトリの C を共有ライブラリにする。

    #8 で C 側に索引 (パック値 → 連番のハッシュ表) が入り、
    「実装はどれも同じ .so を使う」という前提が初めて崩れた。
    """
    if impl not in _impl_libraries:
        build = pathlib.Path(tempfile.mkdtemp(prefix=f"so_{impl}_"))
        atexit.register(shutil.rmtree, build, True)
        _impl_libraries[impl] = build_library(ROOT / "impl" / impl, build)
    return _impl_libraries[impl]


# 読み込み済みの実装。次の実装を読む前に .so を閉じるために持っておく
_loaded: list[types.ModuleType] = []


def unload_previous() -> None:
    """前に読んだ実装の .so を閉じる。

    ⚠️ glibc の dlopen は「名前の文字列」で読み込み済みを引き当てる。
    どの実装も `CDLL("./animal_shogi.so")` と書くので、作業ディレクトリが違っても
    2つめ以降は**1つめに読み込んだ .so** を受け取ってしまう。
    #7 までは C がどれもバイト同一だったので害が出なかったが、#8 で C 側に
    索引が入ったため、閉じないと impl/08 が baseline の .so を掴む。
    """
    while _loaded:
        module = _loaded.pop()
        lib = getattr(module, "lib", None)
        # 閉じたあとに C を呼ぶと落ちるので、黙って使えないようにしておく
        vars(module)["lib"] = None
        if lib is not None:
            _ctypes.dlclose(lib._handle)


def load_impl(impl: str, work: pathlib.Path, so: pathlib.Path) -> types.ModuleType:
    """作業ディレクトリを作って実装を import する。

    実装は `./dat/` と `./kaiseki_log/` をカレント相対で使い、
    `CDLL("./animal_shogi.so")` も import 時のカレントを見るので、chdir してから読む。

    `so` は baseline からビルドした共有ライブラリ。実装が自前の C を持つなら
    (#8 以降) そちらをビルドして使う。
    """
    (work / "dat").mkdir(parents=True)
    (work / "kaiseki_log").mkdir(parents=True)
    impl_dir = ROOT / "impl" / impl
    if any(
        (impl_dir / name).read_bytes() != (BASELINE_DIR / name).read_bytes()
        for name in ("animal_shogi.c", "animal_shogi.h")
    ):
        so = impl_library(impl)
    shutil.copy(so, work / "animal_shogi.so")
    shutil.copy(ROOT / "impl" / impl / "animal_shogi.py", work / "animal_shogi.py")

    spec = importlib.util.spec_from_file_location(
        f"impl_{impl}_{work.name}", work / "animal_shogi.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    unload_previous()
    with chdir(work):
        spec.loader.exec_module(module)
    _loaded.append(module)
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


# dat/ の系統。⚠️ unexplored は全探索の作業ファイルなので
# tools/fingerprint_dat.py の Format には無い (あちらは答えだけを数える)
FAMILY_PREFIXES = {
    "unknown": "unknown*",
    "win": "win001te_*",
    "lose": "lose000te_*",
    "unexplored": "unexplored*",
}

# 記録 #15 までが .pickle、#16 以降が生バイナリの .bin
DAT_SUFFIXES = (".pickle", ".bin")


def dat_suffix(dat: pathlib.Path) -> str:
    """dat/ に並んでいるファイルから拡張子を決める。

    ⚠️ 2つ混ざっていたら落とす。片方だけ数えると、件数が足りないまま
    集合が一致して通る経路ができる。
    """
    found = {p.suffix for p in dat.iterdir() if p.is_file() and p.suffix in DAT_SUFFIXES}
    assert len(found) == 1, f"dat/ の形式が決まらない ({sorted(found)}): {dat}"
    return found.pop()


def load_boards(dat: pathlib.Path, pattern: str) -> set[int]:
    """系統の接頭辞 (拡張子なし) を渡すと、その系統の盤面集合を返す。

    形式は dat/ から決めるので、呼ぶ側は .pickle か .bin かを知らなくてよい。
    """
    boards: set[int] = set()
    for path in sorted(dat.glob(pattern + dat_suffix(dat))):
        if path.suffix == ".bin":
            a = array("Q")
            a.frombytes(path.read_bytes())
            boards |= set(a)
        else:
            with path.open("rb") as f:
                boards |= set(pickle.load(f))
    return boards


def families(dat: pathlib.Path) -> dict[str, frozenset[int]]:
    """dat/ の4系統を、系統ごとの盤面集合にして返す。チャンクの分かれ方は潰れる。"""
    return {k: frozenset(load_boards(dat, v)) for k, v in FAMILY_PREFIXES.items()}
