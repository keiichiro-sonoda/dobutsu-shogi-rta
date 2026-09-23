#!/usr/bin/python3
"""本走に進むかを判定する (門番 #20)。

    python3 experiments/gate_20_prefetch/stop_rule.py

測る前に決めた止める条件は1つだけ: 先読みを入れた4つの段 (F1・P1・P2・P4_scatter) の
どれかで, new − old の 95% 区間が 0 をまたがずに上 (遅くなった) なら, 本走の前に止めて報告する。
区間が 0 をまたぐだけなら止めない (P2 で起こりうる)。先読みの場所を判定で外さない。

数字は gate_stats.py と同じ Welch の計算。比較は old 対 new の1本だけなので,
多重比較の補正は要らない。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gate_stats import collect, samples, welch

GATE = "gate_20_prefetch"
STAGES = (("forward", "F1 展開"), ("spans", "P1"), ("spans", "P2"), ("spans", "P4_scatter"))


def main() -> int:
    stop = False
    print("| 段 | `new` − `old`（95% 区間） | 判定 |")
    print("|---|---|---|")
    for mode, stage in STAGES:
        by_label, _order, rows = collect(GATE, mode)
        values = dict(rows)[stage]
        d, _t, _df, _p, lo, hi = welch(
            samples(values, by_label, "old"), samples(values, by_label, "new")
        )
        if lo > 0:
            verdict, stop = "**遅くなった（止める）**", True
        elif hi < 0:
            verdict = "下がった"
        else:
            verdict = "0 をまたぐ（止めない）"
        print(f"| {stage} | {d:+.2f}（{lo:+.2f} … {hi:+.2f}） | {verdict} |")
    print()
    print("=> 止める: 本走に進まず報告する" if stop else "=> 止める条件に掛からない: 本走に進む")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
