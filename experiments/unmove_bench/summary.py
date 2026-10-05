#!/usr/bin/python3
"""計時の集計と本走への換算 (実験 unmove_bench。記録試行ではない)。

    python3 experiments/unmove_bench/summary.py > experiments/unmove_bench/logs/summary.txt

logs/timing.tsv (run_time.sh) を読み, 版 × 列ごとに ns/局面の中央値と範囲
(周をまたいだ最小〜最大) を出す。
版どうしの差は, 同じ周どうしの差を周ごとに取ってから中央値と範囲を出す (gen_bench と同じ)。

換算は, 作り替えたあとの後退解析を次の和として見積もる (秒)。件数は #33 本走のもの。
1. 前任をたどる: visit の ns × 展開する局面 (勝ちか負けに決まる局面。種類ごとに重み付け)
2. 残りの後続の数を数える: (A) 全探索で数えて持ち越す = degw (mixed) × 全到達局面
   (種類と出次数を 1 バイトにまとめ, F1 で局面ごとに1回書く) /
   (B) 後退解析の初めに数える = A ＋ gen (未知) × 未知局面 (前向きの生成器をもう一度回す)
3. 成果物の形に戻す: 測っていない (README に書いた見積もり)
比べる相手は #33 本走の P1 ＋ P2 ＋ P4 ＋ 174段ループ
(results/33_hot_layout/retreat_summary.tsv の生値)。
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
VERSIONS = ("gen", "cand", "sieve", "visit", "degw")
SAMPLES = ("unknown", "catch", "try", "mixed")
N_ALL = 246_803_167
N_UNKNOWN = 99_485_568
# 展開する局面: キャッチ・トライ負けの全部と, 決まる未知局面 (手数別局面数の合計)
EXPAND = {"catch": 140_298_614, "try": 7_018_985, "unknown": 96_802_868}
STAGES = ("P1", "P2", "P4", "loop174")


def load() -> dict[tuple[str, str], dict[int, tuple[float, float]]]:
    out: dict[tuple[str, str], dict[int, tuple[float, float]]] = {}
    with (HERE / "logs" / "timing.tsv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            key = (row["version"], row["sample"])
            out.setdefault(key, {})[int(row["round"])] = (
                float(row["ns_per_q"]),
                float(row["out_per_q"]),
            )
    return out


def mid(xs: list[float]) -> str:
    return f"{statistics.median(xs):.1f}（{min(xs):.1f}〜{max(xs):.1f}）"


def main() -> int:
    data = load()
    rounds = sorted({r for v in data.values() for r in v})
    print(f"周: {len(rounds)}（{rounds[0]}〜{rounds[-1]}）")
    print()
    print("### ns/局面（中央値と範囲）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in VERSIONS:
        cells = [mid([data[(v, s)][r][0] for r in rounds]) for s in SAMPLES]
        print(f"| `{v}` | " + " | ".join(cells) + " |")
    print()
    print("### 1局面あたりの出力の数（候補・前任・後続。周で変わらない）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in ("gen", "cand", "sieve", "visit"):
        cells = [f"{data[(v, s)][rounds[0]][1]:.3f}" for s in SAMPLES]
        print(f"| `{v}` | " + " | ".join(cells) + " |")
    print()
    print("### 版どうしの差（ns/局面。同じ周どうしの差の中央値と範囲）")
    print()
    print("| 差 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for a, b in (("cand", "gen"), ("sieve", "cand"), ("visit", "sieve")):
        cells = [mid([data[(a, s)][r][0] - data[(b, s)][r][0] for r in rounds]) for s in SAMPLES]
        print(f"| `{a}` − `{b}` | " + " | ".join(cells) + " |")

    def med(v: str, s: str) -> float:
        return statistics.median(data[(v, s)][r][0] for r in rounds)

    def per_round(v: str, s: str) -> list[float]:
        return [data[(v, s)][r][0] for r in rounds]

    stages = dict(
        ln.split("\t", 1)
        for ln in (ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    now = sum(float(stages[s]) for s in STAGES)
    visit = {s: per_round("visit", s) for s in EXPAND}
    trav = [sum(visit[s][i] * n for s, n in EXPAND.items()) / 1e9 for i in range(len(rounds))]
    deg_a = [x * N_ALL / 1e9 for x in per_round("degw", "mixed")]
    gen_u = [x * N_UNKNOWN / 1e9 for x in per_round("gen", "unknown")]
    print()
    print("### 本走への換算（秒。周ごとに計算して中央値と範囲）")
    print()
    print(f"- いま: P1 ＋ P2 ＋ P4 ＋ 174段ループ ＝ {now:.2f}（#33 本走の生値）")
    print(f"- 1. 前任をたどる（visit × 展開する {sum(EXPAND.values()):,} 局面）: {mid(trav)}")
    print(f"- 2A. 出次数を全探索で数えて持ち越す（degw の mixed × {N_ALL:,}）: {mid(deg_a)}")
    print(f"- 2B. 後退解析の初めに数える（2A ＋ gen の未知 × {N_UNKNOWN:,}）: "
          f"{mid([a + g for a, g in zip(deg_a, gen_u, strict=True)])}")  # fmt: skip
    tot_a = [t + a for t, a in zip(trav, deg_a, strict=True)]
    print(f"- 1 ＋ 2A（3 は含まない）: {mid(tot_a)}、いまとの差 {mid([x - now for x in tot_a])}")
    print()
    print(f"参考: visit の未知・キャッチ・トライ負けの中央値 {med('visit', 'unknown'):.1f} / "
          f"{med('visit', 'catch'):.1f} / {med('visit', 'try'):.1f} ns")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
