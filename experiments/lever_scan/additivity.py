#!/usr/bin/python3
"""足し算になるかの確認 (実験 lever_scan)。

    python3 experiments/lever_scan/additivity.py <forward|spans>

段ごとに次を並べる:

  「all − base」        Welch の差と 95% 区間 (gate_stats.py と同じ計算)
  「5腕の差の和」       fnsi / const / native / huge / pf それぞれの (腕 − base) の点推定の和
  「all − 和」          束ねたときのずれ. 負なら和より大きく効いた, 正なら取り合った

⚠️ 和のほうは点推定だけを出す. 5腕が同じ base の標本を共有しているので,
   5つの差は独立でなく, 区間を「独立な差の和」として組めない.
⚠️ ずれていても失敗ではない. huge と pf は同じ段 (P1・P2・F1) の同じ待ち時間を
   取り合うので, 和より小さく出ることがある. ずれ方を読む.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import collect, samples, welch  # noqa: E402

GATE = "lever_scan"
SINGLES = ("fnsi", "const", "native", "huge", "pf")


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("forward", "spans"):
        print(__doc__, file=sys.stderr)
        return 2
    by_label, order, rows = collect(GATE, argv[1])
    missing = [a for a in ("base", "all", *SINGLES) if a not in order]
    if missing:
        print(f"ログに無い腕: {' '.join(missing)}", file=sys.stderr)
        return 2
    print("| 段 | `base` | `all` − `base`（95% 区間） | 5腕の差の和 | `all` − 和 |")
    print("|---|---|---|---|---|")
    for name, values in rows:
        base = samples(values, by_label, "base")
        diff, _t, _df, _p, lo, hi = welch(base, samples(values, by_label, "all"))
        total = sum(mean(samples(values, by_label, a)) - mean(base) for a in SINGLES)
        print(
            f"| {name} | {mean(base):.2f} | {diff:+.2f}（{lo:+.2f} … {hi:+.2f}） "
            f"| {total:+.2f} | {diff - total:+.2f} |"
        )
    print()
    print("内訳 (腕 − base の点推定):")
    for name, values in rows:
        base = mean(samples(values, by_label, "base"))
        parts = " / ".join(
            f"{a} {mean(samples(values, by_label, a)) - base:+.2f}" for a in SINGLES
        )
        print(f"  {name}: {parts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
