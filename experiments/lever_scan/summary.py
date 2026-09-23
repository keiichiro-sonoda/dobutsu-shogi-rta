#!/usr/bin/python3
"""README に貼る2つの表を生ログから組み立てる (実験 lever_scan)。

    python3 experiments/lever_scan/summary.py

⚠️ 表を手で書かない (CLAUDE.md「段ごとの揺れの標本と統計値は手で書かない」)。
数字は gate_stats.py と同じ Welch の計算で、base に対する差。
base に対して6本引いているので、p 値・区間は多重比較未補正。

  狙う段   測る前に「下がる」「向きも未知」と登録した段 (README の事前登録の表)
  対照     同じく「触らないはずの段」。区間が 0 をまたげば「動いていない」と読める
           (0 をまたがないものは名指しで出す)
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gate_stats import collect, samples, welch

GATE = "lever_scan"
FWD = "forward"
RET = "spans"

# (腕, 門番, 段) — README の事前登録の表の「狙う段」
TARGETS = {
    "fnsi": [(FWD, "F1 展開"), (RET, "P2")],
    "const": [(FWD, "F1 展開"), (RET, "P2")],
    "native": [(FWD, "F1 展開"), (RET, "P2"), (FWD, "全探索 合計"), (RET, "retreat_total")],
    "huge": [(FWD, "F1 展開"), (RET, "P1"), (RET, "P2")],
    "pf": [(FWD, "F1 展開"), (RET, "P1"), (RET, "P2"), (RET, "P4_scatter")],
    "all": [(FWD, "全探索 合計"), (RET, "retreat_total")],
}
# README の事前登録の表の「触らないはずの段」
FWD_CTRL = ["F2 未知の書き出し", "F5 未探索の書き出し", "F6 終端の書き出し"]
CONTROLS = {
    "fnsi": [(FWD, s) for s in FWD_CTRL] + [(RET, "P0"), (RET, "P4"), (RET, "loop174")],
    "const": [(FWD, s) for s in FWD_CTRL] + [(RET, "P0"), (RET, "P4"), (RET, "loop174")],
    "native": [(RET, "P0")],
    "huge": [(RET, "P0"), (RET, "P4"), (RET, "loop174")],
    "pf": [(RET, "P0"), (RET, "P4_count"), (RET, "loop174")],
    "all": [(RET, "P0")],
}


def load() -> dict[str, tuple[dict[str, str], dict[str, dict[str, float]]]]:
    out = {}
    for mode in (FWD, RET):
        by_label, _order, rows = collect(GATE, mode)
        out[mode] = (by_label, dict(rows))
    return out


def diff(data, mode: str, stage: str, arm: str) -> tuple[float, float, float]:
    by_label, rows = data[mode]
    d, _t, _df, _p, lo, hi = welch(
        samples(rows[stage], by_label, "base"), samples(rows[stage], by_label, arm)
    )
    return d, lo, hi


def label(mode: str, stage: str) -> str:
    if mode == FWD:
        return stage if stage.startswith("全探索") else "全探索 " + stage
    return "後退解析 " + stage


def main() -> int:
    data = load()
    print("| 腕 | 狙う段 | `base` | 差（95% 区間） | 0 をまたぐか |")
    print("|---|---|---|---|---|")
    for arm, targets in TARGETS.items():
        for mode, stage in targets:
            by_label, rows = data[mode]
            base = samples(rows[stage], by_label, "base")
            d, lo, hi = diff(data, mode, stage, arm)
            cross = "またぐ" if lo <= 0 <= hi else ("下がる" if hi < 0 else "上がる")
            print(
                f"| `{arm}` | {label(mode, stage)} | {sum(base) / len(base):.2f} "
                f"| {d:+.2f}（{lo:+.2f} … {hi:+.2f}） | {cross} |"
            )
    print()
    print("| 腕 | 対照の段 | 区間が 0 をまたがなかった段 | 差の絶対値の最大 |")
    print("|---|---|---|---|")
    for arm, ctrls in CONTROLS.items():
        moved = []
        worst = 0.0
        for mode, stage in ctrls:
            d, lo, hi = diff(data, mode, stage, arm)
            worst = max(worst, abs(d))
            if not lo <= 0 <= hi:
                moved.append(f"{label(mode, stage)} {d:+.2f}（{lo:+.2f} … {hi:+.2f}）")
        names = "・".join(stage.split(" ")[0] for _m, stage in ctrls)
        print(f"| `{arm}` | {names} | {'、'.join(moved) or 'なし'} | {worst:.2f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
