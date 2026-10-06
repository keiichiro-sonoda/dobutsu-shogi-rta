#!/usr/bin/python3
"""計時の集計と換算 (実験 attack_count。記録試行ではない)。

    python3 experiments/attack_count/summary.py > experiments/attack_count/logs/summary.txt

logs/timing.tsv (run_time.sh) の ns/局面を, 版 × 列ごとに中央値と範囲 (5周の最小〜最大) で出す。
版どうしの差は, 同じ周どうしの差を周ごとに取ってから中央値と範囲を出す (gen_bench と同じ)。
b1 と b2 は unmove_catch の値 (logs/summary.txt) と並べ, ずれの割合を出す
(10% 以上なら測り方を調べる)。

換算 (秒。周ごとに計算して中央値と範囲):
- B1′ の費用 = (b1x − gen) の種類ごとの値 × 種類ごとの局面数 (全探索では全局面が生成器を通る)
- 作り替えた後退解析の見積もり = unmove_catch の drop のループ 80.21 秒 ＋ B1′ の費用
  ＋ 全局面の種類と残りの数をランクの配列に書く費用 (unmove_bench の degw 36.3 ns × 246,803,167)
- いまの P1 ＋ P2 ＋ P4 ＋ 174段ループ (results/33_hot_layout/retreat_summary.tsv の生値) との差
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SAMPLES = ("unknown", "catch", "try", "mixed")
COUNTS = {"unknown": 99_485_568, "catch": 140_298_614, "try": 7_018_985}
N_ALL = 246_803_167
# unmove_catch の drop のループの中央値 (experiments/unmove_catch/logs/summary.txt)
DROP_LOOP = 80.21
DEGW_NS = 36.3  # unmove_bench の degw (mixed) の中央値 (experiments/unmove_bench/logs/summary.txt)
# unmove_catch の b1 / b2 の中央値 (experiments/unmove_catch/logs/summary.txt)
BEFORE = {
    ("b1", "unknown"): 617.3,
    ("b1", "catch"): 243.8,
    ("b1", "try"): 507.0,
    ("b1", "mixed"): 409.2,
    ("b2", "unknown"): 461.7,
    ("b2", "catch"): 111.9,
    ("b2", "try"): 197.9,
    ("b2", "mixed"): 262.4,
}
STAGES = ("P1", "P2", "P4", "loop174")


def mid(xs: list[float], fmt: str = ".1f") -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def main() -> int:
    data: dict[tuple[str, str], dict[int, float]] = {}
    with (HERE / "logs" / "timing.tsv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            key = (row["version"], row["sample"])
            data.setdefault(key, {})[int(row["round"])] = float(row["ns_per_q"])
    rounds = sorted({r for v in data.values() for r in v})
    print(f"周: {len(rounds)}")
    print()
    print("### ns/局面（中央値と範囲）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in ("gen", "b1", "b1x", "b2"):
        cells = [mid([data[(v, s)][r] for r in rounds]) for s in SAMPLES]
        print(f"| `{v}` | " + " | ".join(cells) + " |")
    print()
    print("### 差（同じ周どうしの差の中央値と範囲）")
    print()
    print("| 差 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in ("b1x", "b1", "b2"):
        cells = [mid([data[(v, s)][r] - data[("gen", s)][r] for r in rounds]) for s in SAMPLES]
        print(f"| `{v}` − `gen` | " + " | ".join(cells) + " |")
    print()
    print("### b1 と b2 の測り直し（unmove_catch の中央値とのずれ）")
    print()
    worst = 0.0
    for (v, s), before in BEFORE.items():
        now = statistics.median(data[(v, s)][r] for r in rounds)
        shift = (now - before) / before * 100
        worst = max(worst, abs(shift))
        print(f"- `{v}` {s}: 前回 {before:.1f} / 今回 {now:.1f}（{shift:+.1f}%）")
    print(f"- ずれの最大 {worst:.1f}%（10% 以上なら測り方の違いを調べる）")

    def cost(r: int) -> float:
        return sum((data[("b1x", s)][r] - data[("gen", s)][r]) * n for s, n in COUNTS.items()) / 1e9

    stages = dict(
        ln.split("\t", 1)
        for ln in (ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    now4 = sum(float(stages[s]) for s in STAGES)
    degw = DEGW_NS * N_ALL / 1e9
    b1x = [cost(r) for r in rounds]
    total = [DROP_LOOP + c + degw for c in b1x]
    print()
    print("### 換算（秒）")
    print()
    for s, n in COUNTS.items():
        part = [(data[("b1x", s)][r] - data[("gen", s)][r]) * n / 1e9 for r in rounds]
        print(f"- B1′ の費用のうち {s}（× {n:,}）: {mid(part, '.2f')}")
    print(f"- B1′ の費用（3種類の合計）: {mid(b1x, '.2f')}")
    print(f"- 種類と残りの数をランクの配列に書く（degw {DEGW_NS} ns × {N_ALL:,}）: {degw:.2f}")
    head = f"drop のループ {DROP_LOOP} ＋ B1′ ＋ 書く費用"
    print(f"- 作り替えた後退解析の見積もり（{head}）: {mid(total, '.2f')}")
    print(f"- いまの4段 {now4:.2f} との差: {mid([t - now4 for t in total], '.2f')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
