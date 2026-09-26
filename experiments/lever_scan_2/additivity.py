#!/usr/bin/python3
"""足し算になるかの確認 (実験 lever_scan_2。記録試行ではない)。

    python3 experiments/lever_scan_2/additivity.py > experiments/lever_scan_2/logs/additivity.txt

全探索と後退解析の段ごとに次を並べる:

  「all − base」     Welch の差と 95% 区間 (gate_stats.py と同じ計算)
  「3腕の差の和」    pf3 / hugeR / reuse それぞれの (腕 − base) の点推定の和
                     (all は pf3 → hugeR → reuse を重ねたもの。pf2 は入っていない)
  「all − 和」       束ねたときのずれ。負なら和より大きく効いた, 正なら取り合った

⚠️ 和のほうは点推定だけを出す。3腕が同じ base の標本を共有しているので,
   3つの差は独立でなく, 区間を「独立な差の和」として組めない。
⚠️ ずれていても失敗ではない。pf3 と hugeR は同じ段 (174段ループ) の同じ待ち時間を取り合いうる。
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import collect, samples, welch  # noqa: E402

GATE = "lever_scan_2"
SINGLES = ("pf3", "hugeR", "reuse")


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def main() -> int:
    head = [
        "段",
        "`base`",
        "`all` − `base`（95% 区間）",
        "3腕の差の和",
        "`all` − 和",
        "内訳（腕 − base）",
    ]
    print("| " + " | ".join(head) + " |")
    print("|---|---|---|---|---|---|")
    for mode in ("forward", "spans"):
        by_label, order, rows = collect(GATE, mode)
        missing = [a for a in ("base", "all", *SINGLES) if a not in order]
        if missing:
            print(f"ログに無い腕: {' '.join(missing)}", file=sys.stderr)
            return 2
        for name, values in rows:
            base = samples(values, by_label, "base")
            diff, _t, _df, _p, lo, hi = welch(base, samples(values, by_label, "all"))
            parts = {a: mean(samples(values, by_label, a)) - mean(base) for a in SINGLES}
            total = sum(parts.values())
            detail = " / ".join(f"{a} {v:+.2f}" for a, v in parts.items())
            print(
                f"| {name} | {mean(base):.2f} | {diff:+.2f}（{lo:+.2f} … {hi:+.2f}） "
                f"| {total:+.2f} | {diff - total:+.2f} | {detail} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
