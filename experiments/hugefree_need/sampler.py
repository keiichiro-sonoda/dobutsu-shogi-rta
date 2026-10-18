#!/usr/bin/python3
"""0.2 秒おきに 2 MiB 以上の空きと, 解析のプロセスの巨大ページを読む (実験 hugefree_need。記録試行ではない)。

    python3 sampler.py <見張る PID> <出力の tsv> [間隔の秒 (既定 0.2)]

読むだけで, 計測される側には手を入れない。見張る PID (run_one.sh が起動した /usr/bin/time) が
終わるまで, 間隔ごとに1行書く:

    t          見張りを始めてからの秒 (time.monotonic の差)
    node0_gib  ノード0の /proc/buddyinfo の order 9 以上 (2 MiB 以上) の空きブロックの合計 (GiB)
    node1_gib  ノード1の同じ値
    anonhuge_kB  解析の Python のプロセス (見張る PID の子孫で, 名前が python3) の
               /proc/<pid>/smaps_rollup の AnonHugePages. プロセスがまだ・もう無いときは空
    rss_kB     同じプロセスの smaps_rollup の Rss

数え方は tools/run.sh の hugefree_gib と同じ (zone ごとの order 9 以上の個数 × 4 KiB × 2^order を足す)。
"""

from __future__ import annotations

import pathlib
import sys
import time

PAGE_KIB = 4


def hugefree() -> dict[str, float]:
    out: dict[str, float] = {}
    for ln in pathlib.Path("/proc/buddyinfo").read_text().splitlines():
        c = ln.split()
        if not c or c[0] != "Node":
            continue
        node = c[1].rstrip(",")
        counts = [int(x) for x in c[4:]]
        kib = sum(n * PAGE_KIB * 2**order for order, n in enumerate(counts) if order >= 9)
        out[node] = out.get(node, 0.0) + kib / 1048576
    return out


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
        f.write("t\tnode0_gib\tnode1_gib\tanonhuge_kB\trss_kB\n")
        while pathlib.Path(f"/proc/{watch}").exists():
            t = time.monotonic() - t0
            hf = hugefree()
            if py is None or not pathlib.Path(f"/proc/{py}").exists():
                py = find_python(watch)
            ah, rss = rollup(py) if py is not None else ("", "")
            f.write(f"{t:.3f}\t{hf.get('0', 0):.3f}\t{hf.get('1', 0):.3f}\t{ah}\t{rss}\n")
            f.flush()
            nxt = t0 + (int(t / step) + 1) * step
            time.sleep(max(0.0, nxt - time.monotonic()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
