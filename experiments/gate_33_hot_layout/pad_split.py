#!/usr/bin/python3
"""詰め物の本 (run_pad.sh) で, 置き場所の振れの大きさを出す (門番 #33。判定には使わない)。

    python3 experiments/gate_33_hot_layout/pad_split.py

詰め物の大きさ (24・40・1000 バイト) ごとに各3本。#32 の配置 (old_pad<N>) では詰め物の大きさに
応じて熱い関数がずれ, #33 の配置 (new_pad<N>) ではずれない。
同じ配置の中で詰め物の大きさを変えたときの差を, 段ごとに出す:

1. 腕ごとの平均（sd）
2. 同じ配置の中の詰め物どうしの差 (3組) と 95% 区間。⚠️ 段ごと・組ごとに比べるので多重比較は未補正
3. 同じ配置の中の, 3つの平均の幅 (最大 − 最小)

#32 の配置で差が出て, #33 の配置で出なければ, その差が置き場所の振れの大きさの目安になる。
判定の門番の本 (console.log の old / new) は別の時間帯に回したので, ここでは混ぜない。
数字は gate_stats.py と同じ Welch の計算。
"""

from __future__ import annotations

import itertools
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from f1p2_split import quantities  # noqa: E402
from gate_stats import arms, p_text, samples, sd, welch  # noqa: E402

LOGS = HERE / "logs"
PADS = (24, 40, 1000)
LAYOUTS = (("old", "#32 の配置（熱い関数がずれる）"), ("new", "#33 の配置（ずれない）"))
NAMES = (
    "F1",
    "F1 のユーザー時間",
    "P2",
    "P2 のユーザー時間",
    "P1",
    "P4",
    "loop174",
    "完走 (秒、参考)",
)


def main() -> int:
    by_label = arms(LOGS / "pad_console.log")
    per = {lb: quantities(lb) for lb in by_label}
    values = {name: {lb: per[lb][name] for lb in by_label} for name in NAMES}

    def arm_samples(name: str, arm: str) -> list[float]:
        return samples(values[name], by_label, arm)

    print("### 腕ごとの平均（sd）")
    print()
    heads = [f"`{lay}_pad{n}`" for lay, _ in LAYOUTS for n in PADS]
    print("| 量 | " + " | ".join(heads) + " |")
    print("|---|" + "---|" * len(heads))
    for name in NAMES:
        cells = []
        for lay, _ in LAYOUTS:
            for n in PADS:
                xs = arm_samples(name, f"{lay}_pad{n}")
                cells.append(f"{sum(xs) / len(xs):.2f}（{sd(xs):.2f}）")
        print(f"| {name} | " + " | ".join(cells) + " |")
    for lay, title in LAYOUTS:
        print()
        print(f"### {title}: 詰め物どうしの差（後 − 前、95% 区間）と、平均の幅")
        print()
        pairs = list(itertools.combinations(PADS, 2))
        print("| 量 | " + " | ".join(f"{b} − {a}" for a, b in pairs) + " | 平均の幅 |")
        print("|---|" + "---|" * (len(pairs) + 1))
        for name in NAMES:
            cells = []
            for a, b in pairs:
                x, y = arm_samples(name, f"{lay}_pad{a}"), arm_samples(name, f"{lay}_pad{b}")
                d, _t, _df, p, lo, hi = welch(x, y)
                cells.append(f"{d:+.2f}（{lo:+.2f} … {hi:+.2f}、p {p_text(p)}）")
            means = [
                sum(xs) / len(xs) for xs in (arm_samples(name, f"{lay}_pad{n}") for n in PADS)
            ]
            print(f"| {name} | " + " | ".join(cells) + f" | {max(means) - min(means):.2f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
