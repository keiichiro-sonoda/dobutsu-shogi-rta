#!/usr/bin/env python3
"""array("I") の積み方だけを変えて、ピーク RSS が動くかを見る。

記録 #15 の門番で、後退解析のピーク RSS が 13.8268 → 13.8430 GiB (+16.6 MiB) と
上がり、旧8本と新8本が完全に分離した。#15 が P2 で余分に持つ中継バッファは
256 KiB しかなく、1.5% にしかならない。残る違いは succ の積み方
(1回あたり 9 要素 → 65,536 要素) と、succ_off / cnt を先に確保したことだけ。

  probe.py succ_small   #14 相当: 9 要素ずつ frombytes
  probe.py succ_big     #15 相当: 65,536 要素ずつ frombytes
  probe.py off_grow     #14 相当: succ_off を append, cnt を bytearray.append
  probe.py off_prealloc #15 相当: どちらも先に確保
  probe.py p2_old       #14 の P2 と同じ順序で3本を交互に伸ばす
  probe.py p2_new       #15 の P2 と同じ順序 (succ_off/cnt を先に確保してから succ)
  probe.py full_old     p2_old に索引 8.59 GB と packed 1.97 GB を先に置いたもの
  probe.py full_new     p2_new に同じものを先に置いたもの

⚠️ 1回の起動で1つだけ測る (ru_maxrss は取り消せない高水位なので混ぜられない)。
"""

import resource
import sys
from array import array

N_EDGES = 938671869   # 本走の辺の総数
N_UK = 99485568       # 本走の未知局面数


def peak_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def build_succ(chunk: int) -> int:
    src = memoryview(bytearray(4 * chunk))
    succ = array("I")
    frombytes = succ.frombytes
    left = N_EDGES
    while left > 0:
        n = chunk if left >= chunk else left
        frombytes(src[: 4 * n])
        left -= n
    return len(succ)


def build_off(prealloc: bool) -> int:
    if prealloc:
        succ_off = array("I", bytes(4)) * (N_UK + 1)
        cnt = bytearray(N_UK)
    else:
        succ_off = array("I", bytes(4))
        cnt = bytearray()
        append_off = succ_off.append
        append_cnt = cnt.append
        for i in range(N_UK):
            append_off(i)
            append_cnt(9)
    return len(succ_off) + len(cnt)


def build_p2(new: bool) -> int:
    """P2 の終わりと同じ顔ぶれ・同じ作り方でメモリを作る。

    ⚠️ 単独では差が出なかったので、割り付けの順序が効いているかを見る。
    確保済みのページに書き戻してもピークは動かないので、新版は cnt[i] /
    succ_off[i+1] への書き込みを省いている (メモリの状態は同じ)。
    """
    base, rem = divmod(N_EDGES, N_UK)
    src = memoryview(bytearray(4 * 65536))
    succ = array("I")
    frombytes = succ.frombytes
    if new:
        succ_off = array("I", bytes(4)) * (N_UK + 1)
        cnt = bytearray(N_UK)
        stage = array("I", bytes(4)) * 65536        # 中継バッファ 256 KiB
        left = N_EDGES
        while left > 0:
            n = 65536 if left >= 65536 else left
            frombytes(src[: 4 * n])
            left -= n
        keep = (succ_off, cnt, stage)
    else:
        succ_off = array("I", bytes(4))
        cnt = bytearray()
        append_off = succ_off.append
        append_cnt = cnt.append
        total = 0
        for i in range(N_UK):
            n = base + 1 if i < rem else base
            frombytes(src[: 4 * n])
            append_cnt(n)
            total += n
            append_off(total)
        keep = (succ_off, cnt)
    assert len(succ) == N_EDGES, len(succ)
    return len(succ) + sum(len(x) for x in keep)


def build_full(new: bool) -> int:
    """P2 の末尾をまるごと再現する。索引と packed が先に居る状態で測る。

    ⚠️ p2_old / p2_new で差が出なかったので、先に 10.5 GB が居ることで
    アロケータの振る舞いが変わるかを見る。索引は本物では C の malloc だが、
    CPython も 512 バイト超は malloc に回すので同じ経路に乗る。
    """
    index = bytearray(1 << 29 << 4)          # g_index 2^29 * 16 B = 8.59 GB
    packed = array("Q", bytes(8)) * 246803167  # 1.97 GB
    size = build_p2(new)
    return size + len(index) + len(packed)


MODES = {
    "succ_small": lambda: build_succ(9),
    "succ_big": lambda: build_succ(65536),
    "off_grow": lambda: build_off(False),
    "off_prealloc": lambda: build_off(True),
    "p2_old": lambda: build_p2(False),
    "p2_new": lambda: build_p2(True),
    "full_old": lambda: build_full(False),
    "full_new": lambda: build_full(True),
}

if __name__ == "__main__":
    mode = sys.argv[1]
    base = peak_mib()
    size = MODES[mode]()
    print("%-13s 要素 %12d  起動時のピーク %8.1f MiB  最終のピーク %10.1f MiB  差 %9.1f MiB"
          % (mode, size, base, peak_mib(), peak_mib() - base))
