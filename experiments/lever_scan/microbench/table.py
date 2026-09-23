#!/usr/bin/python3
"""マイクロベンチ4条件の中央値 (ns/辺) を表にする (実験 lever_scan)。

    python3 experiments/lever_scan/microbench/table.py

判定の規則 (測る前に決めたもの): 1条件目 (uniform 30 plain) で scatter ÷ count が 5 倍を超えたら,
模型が本番の症状を再現しているとみなし, 残り3条件で先読みと巨大ページの効き目を読む。
"""

from __future__ import annotations

import pathlib
import sys

LOGS = pathlib.Path(__file__).resolve().parent / "logs"
CONDS = ("uniform_30_plain", "uniform_30_hp", "local_30_plain", "local_30_hp")
KERNELS = ("count", "scatter", "store_indep", "pf2_32")


def medians(name: str) -> tuple[dict[str, float], int]:
    med: dict[str, float] = {}
    huge = -1
    for line in (LOGS / f"{name}.txt").read_text(encoding="utf-8").splitlines():
        f = line.split()
        if f and f[0] in KERNELS:
            med[f[0]] = float(f[2])
        if line.startswith("AnonHugePages:"):
            huge = int(f[1])
    return med, huge


def main() -> int:
    print("| 条件 | `AnonHugePages` | count | scatter | scatter ÷ count "
          "| store_indep | pf2_32 | pf2_32 ÷ scatter |")
    print("|---|---|---|---|---|---|---|---|")
    for name in CONDS:
        m, huge = medians(name)
        print(
            f"| `{name.replace('_', ' ')}` | {huge / 1048576:.2f} GiB "
            f"| {m['count']:.2f} | {m['scatter']:.2f} "
            f"| {m['scatter'] / m['count']:.2f} 倍 | {m['store_indep']:.2f} | {m['pf2_32']:.2f} "
            f"| {m['pf2_32'] / m['scatter']:.2f} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
