#!/usr/bin/python3
"""0.2 秒おきに空きブロックと, 解析のプロセスの巨大ページを読む (実験 hugefree_need2。記録試行ではない)。

    python3 sampler.py <見張る PID> <出力の tsv> [間隔の秒 (既定 0.2)]

読むだけで, 計測される側には手を入れない。見張る PID (run_one.sh が起動した /usr/bin/time) が
終わるまで, 間隔ごとに1行書く:

    t          見張りを始めてからの秒 (time.monotonic の差)
    node0_gib  ノード0の /proc/buddyinfo の order 9 以上 (2 MiB 以上) の空きブロックの合計 (GiB)
    node1_gib  ノード1の同じ値
    node0_all_gib / node1_all_gib  そのノードの全部の大きさ (order 0〜10) の空きブロックの合計 (GiB). 2回目で足した.
               消費量の主はこれで測る (README の登録の節)
    node0_orders / node1_orders  そのノードの order 0〜10 の空きブロックの個数 (zone を足したもの, カンマ区切り)
    anonhuge_kB  解析の Python のプロセス (見張る PID の子孫で, 名前が python3) の
               /proc/<pid>/smaps_rollup の AnonHugePages. プロセスがまだ・もう無いときは空
    rss_kB     同じプロセスの smaps_rollup の Rss

2 MiB 以上の数え方は tools/run.sh の hugefree_gib と同じ (zone ごとの order 9 以上の個数 × 4 KiB × 2^order を足す)。
experiments/hugefree_need/sampler.py の写しに, 全部の大きさの合計と order ごとの個数を足した。
"""

from __future__ import annotations

import pathlib
import sys
import time

PAGE_KIB = 4


def orders() -> dict[str, list[int]]:
    """ノード → order 0〜10 の空きブロックの個数 (zone を足したもの)。"""
    out: dict[str, list[int]] = {}
    for ln in pathlib.Path("/proc/buddyinfo").read_text().splitlines():
        c = ln.split()
        if not c or c[0] != "Node":
            continue
        node = c[1].rstrip(",")
        counts = [int(x) for x in c[4:]]
        acc = out.setdefault(node, [0] * len(counts))
        for i, n in enumerate(counts):
            acc[i] += n
    return out


def gib(counts: list[int], lo: int) -> float:
    return sum(n * PAGE_KIB * 2**order for order, n in enumerate(counts) if order >= lo) / 1048576


def children(pid: int) -> list[int]:
    try:
        text = pathlib.Path(f"/proc/{pid}/task/{pid}/children").read_text()
    except OSError:
        return []
    return [int(x) for x in text.split()]


def find_python(root: int) -> int | None:
    stack = [root]
    while stack:
        p = stack.pop()
        try:
            name = pathlib.Path(f"/proc/{p}/comm").read_text().strip()
        except OSError:
            continue
        if name.startswith("python"):
            return p
        stack.extend(children(p))
    return None


def rollup(pid: int) -> tuple[str, str]:
    try:
        text = pathlib.Path(f"/proc/{pid}/smaps_rollup").read_text()
    except OSError:
        return "", ""
    vals = {}
    for ln in text.splitlines():
        c = ln.split()
        if len(c) >= 2 and c[0] in ("AnonHugePages:", "Rss:"):
            vals[c[0]] = c[1]
    return vals.get("AnonHugePages:", ""), vals.get("Rss:", "")


def main(argv: list[str]) -> int:
    watch, out = int(argv[1]), pathlib.Path(argv[2])
    step = float(argv[3]) if len(argv) > 3 else 0.2
    t0 = time.monotonic()
    py: int | None = None
    with out.open("w", encoding="utf-8") as f:
        f.write("t\tnode0_gib\tnode1_gib\tanonhuge_kB\trss_kB\tnode0_all_gib\tnode1_all_gib"
                "\tnode0_orders\tnode1_orders\n")
        while pathlib.Path(f"/proc/{watch}").exists():
            t = time.monotonic() - t0
            od = orders()
            z = [0] * 11
            o0, o1 = od.get("0", z), od.get("1", z)
            if py is None or not pathlib.Path(f"/proc/{py}").exists():
                py = find_python(watch)
            ah, rss = rollup(py) if py is not None else ("", "")
            f.write(
                f"{t:.3f}\t{gib(o0, 9):.3f}\t{gib(o1, 9):.3f}\t{ah}\t{rss}\t{gib(o0, 0):.3f}\t{gib(o1, 0):.3f}"
                f"\t{','.join(map(str, o0))}\t{','.join(map(str, o1))}\n"
            )
            f.flush()
            nxt = t0 + (int(t / step) + 1) * step
            time.sleep(max(0.0, nxt - time.monotonic()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
