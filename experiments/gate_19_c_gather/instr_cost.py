#!/usr/bin/python3
"""計装の直接コストを実測する (記録 #19)。

    python3 experiments/gate_19_c_gather/instr_cost.py [繰り返し回数] [組数]

CLAUDE.md は全探索の計装について「オーバーヘッドは実測 0.06 秒」と書いている。
記録 #19 で後退解析側にも境界を置いたので、**同じことをこちらについても出す**。

測るのは4つ:

  ① `_profMark()` 1回 (impl/19)        … 時計 + /proc/self/statm + /proc/self/status
                                          + getrusage
  ② `_profMark()` 1回 (impl/18)        … getrusage を足す前
  ③ `getrusage(RUSAGE_SELF)` 1回       … #19 が足した呼び出しそのもの
  ④ `_retreatWriteSummary()` 1回       … 74 行の TSV を書く

⚠️ **①−② で「足したぶん」を出さない。** `_profMark` の費用はほぼ全部が
`/proc/self/status` の読みで、その揺れが getrusage 1回より大きい。
足したぶんは ③ を直に測って出す。

各量は `reps` 回の平均を `rounds` 組とって、**最小値**を採る (他の仕事が
割り込んだ組は上に外れるだけなので、下限のほうが真の費用に近い)。

⚠️ ここで測れるのは直接コストだけ。間接的な影響 (キャッシュの動きなど) は
1本の比較では判定できない (`experiments/forward_profile/README.md` の同じ留保)。
"""

from __future__ import annotations

import _ctypes
import importlib.util
import os
import pathlib
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import types
from collections.abc import Callable

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
IMPLS = ("18_optimized", "19_c_gather")
DEFAULT_REPS = 20000
DEFAULT_ROUNDS = 5
# 後退解析に置いた境界の数と、全探索が1ラウンドで呼ぶ回数
RETREAT_MARK_NUM = 12
FORWARD_MARKS_PER_ROUND = 14


def load(impl: str, work: pathlib.Path) -> types.ModuleType:
    """実装を作業ディレクトリに展開して import する。

    ⚠️ 実装は `CDLL("./animal_shogi.so")` と `./kaiseki_log/` をカレント相対で
    見るので、chdir してから読む。読み終わったら `unload()` すること
    (glibc の dlopen は名前の文字列で引き当てるので、閉じないと2つめが
    1つめの .so を掴む。`tests/conftest.py` の `unload_previous()` と同じ罠)。
    """
    (work / "kaiseki_log").mkdir(parents=True)
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile", "animal_shogi.py"):
        shutil.copy(ROOT / "impl" / impl / name, work / name)
    subprocess.run(["make", "animal_shogi.so"], cwd=work, check=True, capture_output=True)
    os.chdir(work)
    spec = importlib.util.spec_from_file_location(f"cost_{impl}", work / "animal_shogi.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unload(module: types.ModuleType) -> None:
    lib = module.lib
    module.lib = None
    _ctypes.dlclose(lib._handle)


def per_call(fn: Callable[[], object], reps: int, rounds: int) -> float:
    """1回あたりの秒。組ごとの平均のうち最小を返す。"""
    best = float("inf")
    for _ in range(rounds):
        t = time.perf_counter()
        for _ in range(reps):
            fn()
        best = min(best, (time.perf_counter() - t) / reps)
    return best


def main(argv: list[str]) -> int:
    reps = int(argv[1]) if len(argv) > 1 else DEFAULT_REPS
    rounds = int(argv[2]) if len(argv) > 2 else DEFAULT_ROUNDS
    base = pathlib.Path.cwd()
    mark: dict[str, float] = {}
    summary = 0.0
    try:
        for impl in IMPLS:
            work = pathlib.Path(tempfile.mkdtemp(prefix=f"instr_{impl}_"))
            module = load(impl, work)
            per_call(lambda: module._profMark("x"), 100, 1)  # /proc のページを踏ませる
            mark[impl] = per_call(lambda: module._profMark("x"), reps, rounds)
            if impl == IMPLS[-1]:
                for name in module.RETREAT_MARKS:
                    module._profMark(name)
                summary = per_call(module._retreatWriteSummary, 200, rounds)
            unload(module)
            os.chdir(base)
            shutil.rmtree(work, ignore_errors=True)
    finally:
        os.chdir(base)
    rusage = per_call(lambda: resource.getrusage(resource.RUSAGE_SELF), reps, rounds)

    new = mark[IMPLS[1]]
    total = new * RETREAT_MARK_NUM + summary
    print(f"繰り返し {reps} 回 × {rounds} 組 の最小、python3 {sys.version.split()[0]}")
    print()
    print("| | 1回 | 回数 | 合計 |")
    print("|---|---|---|---|")
    print(f"| `_profMark` (impl/19) | {new * 1e6:.2f} µs | 後退解析 {RETREAT_MARK_NUM} か所 "
          f"| {new * RETREAT_MARK_NUM * 1e3:.2f} ミリ秒 |")
    print(f"| `_retreatWriteSummary` | {summary * 1e6:.2f} µs | 1 | {summary * 1e3:.2f} ミリ秒 |")
    print(f"| **後退解析の計装 合計** | | | **{total * 1e3:.2f} ミリ秒** |")
    print()
    print("前向き探索が新しく払うぶん (`_profMark` に getrusage が1回増えた):")
    print()
    print("| | 1回 | 回数 | 合計 |")
    print("|---|---|---|---|")
    print(f"| `getrusage(RUSAGE_SELF)` | {rusage * 1e6:.2f} µs "
          f"| 1ラウンド {FORWARD_MARKS_PER_ROUND} 回 "
          f"| 1ラウンドあたり {rusage * FORWARD_MARKS_PER_ROUND * 1e6:.1f} µs |")
    print()
    print(f"参考: `_profMark` は impl/18 が {mark[IMPLS[0]] * 1e6:.2f} µs、"
          f"impl/19 が {new * 1e6:.2f} µs。")
    print(f"⚠️ この差 ({(new - mark[IMPLS[0]]) * 1e6:+.2f} µs) を「足したぶん」として読まない。"
          "費用のほぼ全部が")
    print("   `/proc/self/status` の読みで、その揺れが getrusage 1回より大きい。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
