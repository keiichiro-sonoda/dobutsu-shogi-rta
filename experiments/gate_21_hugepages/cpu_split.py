#!/usr/bin/python3
"""段ごとのユーザー時間とカーネル時間の new − old を出す (門番 #21)。

    python3 experiments/gate_21_hugepages/cpu_split.py

全探索は forward_summary.tsv の段ごとの合計 (utime_F1 など、ラウンドをまたいで足したもの)、
後退解析は retreat_summary.tsv の境界の累積値 (utime_P1 など) の差を段にする。

⚠️ ユーザーとカーネルへの配分は、タイマー割り込みの標本から比で割り振られる
   (この計測機は CONFIG_HZ=1000 で nohz_full なし)。合計は正確だが、配分は標本なので、
   短い段の配分は荒い。段ごとの合計で読む。
数字は gate_stats.py と同じ Welch の計算 (比較は1対1)。
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import arms, console, samples, welch  # noqa: E402

LOGS = HERE / "logs"
FORWARD = ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "release", "forward_total")
# (段, 始めの境界, 終わりの境界)。RETREAT_SPANS と同じ区切り
RETREAT = (
    ("P0", "R_start", "P0"),
    ("P1", "P0", "P1"),
    ("P2", "P1", "P2"),
    ("P2_free", "P2", "P2_free"),
    ("P4_count", "P2_free", "P4_count"),
    ("P4_scatter", "P4_count", "P4"),
    ("R_dtm", "P4", "R_dtm"),
    ("loop174", "R_dtm", "R_loop"),
    ("R_draw", "R_loop", "R_draw"),
    ("R_uk", "R_draw", "R_uk"),
    ("retreat_total", "R_start", "R_uk"),
)


def tsv(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def row(name: str, by_label: dict[str, str], values: dict[str, float]) -> str:
    old = samples(values, by_label, "old")
    new = samples(values, by_label, "new")
    d, _t, _df, _p, lo, hi = welch(old, new)
    return (
        f"{sum(old) / len(old):.2f} | {sum(new) / len(new):.2f} | {d:+.2f}（{lo:+.2f} … {hi:+.2f}）"
    )


def main() -> int:
    for mode in ("forward", "retreat"):
        by_label = arms(console(LOGS, mode))
        print(f"### {'全探索' if mode == 'forward' else '後退解析'}")
        print()
        print("| 段 | 種類 | `old` 平均 | `new` 平均 | `new` − `old`（95% 区間） |")
        print("|---|---|---|---|---|")
        if mode == "forward":
            data = {lb: tsv(LOGS / f"{lb}_forward_summary.tsv") for lb in by_label}
            for stage in FORWARD:
                for kind in ("utime", "stime"):
                    values = {lb: float(d[f"{kind}_{stage}"]) for lb, d in data.items()}
                    print(f"| {stage} | {kind} | {row(stage, by_label, values)} |")
        else:
            data = {lb: tsv(LOGS / f"{lb}_retreat_summary.tsv") for lb in by_label}
            for stage, a, b in RETREAT:
                for kind in ("utime", "stime"):
                    values = {
                        lb: float(d[f"{kind}_{b}"]) - float(d[f"{kind}_{a}"])
                        for lb, d in data.items()
                    }
                    print(f"| {stage} | {kind} | {row(stage, by_label, values)} |")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
