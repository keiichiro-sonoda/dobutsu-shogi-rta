#!/usr/bin/python3
"""本走に進むかを判定する (門番 #21)。

    python3 experiments/gate_21_hugepages/stop_rule.py

測る前に決めた止める条件は2つ。どちらかに掛かったら本走の前に止めて報告する。

  1. 巨大ページを入れた3段 (F1・P1・P2) のどれかで, new − old の 95% 区間が 0 をまたがずに上
     (遅くなった)。区間が 0 をまたぐだけなら止めない
  2. new のどれか1本で, 表を捨てる直前の AnonHugePages が表の全部
     (全探索 4,096 MiB ＝ 4,194,304 kB、後退解析 8,192 MiB ＝ 8,388,608 kB) に届かない。
     または /proc/vmstat の thp_fault_fallback の前後差が 0 でない。
     レバーが効いていないので, 測った差は巨大ページの効果ではない

数字は gate_stats.py と同じ Welch の計算。比較は old 対 new の1本だけなので,
多重比較の補正は要らない。
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import arms, collect, console, samples, welch  # noqa: E402

GATE = "gate_21_hugepages"
LOGS = HERE / "logs"
STAGES = (("forward", "F1 展開"), ("spans", "P1"), ("spans", "P2"))
FULL = {
    "forward": ("forward_summary", "anonhuge_seen_kB", 4_194_304),
    "retreat": ("retreat_summary", "anonhuge_index_kB", 8_388_608),
}


def tsv(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def fallback(label: str) -> int:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index("thp_fault_fallback")
    return int(rows[2][i]) - int(rows[1][i])


def main() -> int:
    stop = False
    print("### 1. 巨大ページを入れた3段")
    print()
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
    print("### 2. 巨大ページが付いたか（`new` は表の全部、`old` は 0 のはず）")
    print()
    print("| 本 | 腕 | `AnonHugePages`（kB） | 表の全部か | `thp_fault_fallback` の前後差 |")
    print("|---|---|---|---|---|")
    for mode, (stem, key, full) in FULL.items():
        for label, arm in arms(console(LOGS, mode)).items():
            huge = int(tsv(LOGS / f"{label}_{stem}.tsv")[key])
            fb = fallback(label)
            whole = "全部" if huge >= full else ("0" if huge == 0 else "**届かない**")
            if arm == "new" and (huge < full or fb != 0):
                stop = True
            print(f"| {label} | `{arm}` | {huge:,} | {whole} | {fb} |")
    print()
    print("=> 止める: 本走に進まず報告する" if stop else "=> 止める条件に掛からない: 本走に進む")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
