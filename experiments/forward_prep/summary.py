#!/usr/bin/python3
"""集計と換算 (実験 forward_prep。記録試行ではない)。

    python3 experiments/forward_prep/summary.py > experiments/forward_prep/logs/summary.txt

計時の門番 (run_all.sh) の18本の生ログから, 腕ごと (old / recalc / carry) に出す:
- forward_summary.tsv の F1・全探索の合計 (forward_total)・F1 のユーザー時間とカーネル時間・
  F1 の minor fault
- time.txt のピーク RSS (Maximum resident set size)
各腕の平均と範囲 (最小〜最大) と, 腕ごとの平均 − old の平均. 検定の表は
experiments/gate_stats.py が出す (logs/gate_stats.txt. 2つの腕をそれぞれ old と比べるので
多重比較は未補正).

換算 (秒):
   作り替えた後退解析の見積もり = 試作のループ 60.98 ＋ 書き出し 2.36
   (unmove_flip の pruned の中央値) ＋ 全探索の F1 の差 (腕の平均 − old の平均)
   比べる相手: いまの P1 ＋ P2 ＋ P4 ＋ 174段ループ ＋ R_draw ＋ R_uk
   (results/33_hot_layout/retreat_summary.tsv の生値)
   外挿 14.04 秒 (B1′ 5.08 ＋ degw 8.96. unmove_prune・unmove_flip の換算) に対する倍率も出す
"""

from __future__ import annotations

import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
ARMS = ("old", "recalc", "carry")
LOOP = 60.98  # unmove_flip の pruned のループの中央値 (experiments/unmove_flip/logs/summary.txt)
WRITE = 2.36  # unmove_flip の pruned の書き出しの中央値 (同上)
EXTRAP = 14.04  # B1′ 5.08 ＋ degw 8.96 (experiments/unmove_flip/logs/summary.txt の換算)
STAGES = ("P1", "P2", "P4", "loop174", "R_draw", "R_uk")
LABEL = re.compile(r"^t\d\d_(?P<arm>[a-z]+)$")
KEYS = (
    ("F1", "F1（秒）"),
    ("forward_total", "全探索の合計（秒）"),
    ("utime_F1", "F1 のユーザー時間"),
    ("stime_F1", "F1 のカーネル時間"),
    ("minflt_F1", "F1 の minor fault"),
    ("peak_rss_gb", "ピーク RSS（GB）"),
)


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def runs() -> dict[str, list[dict[str, float]]]:
    got: dict[str, list[dict[str, float]]] = {a: [] for a in ARMS}
    for path in sorted(LOGS.glob("t*_forward_summary.tsv")):
        label = path.name[: -len("_forward_summary.tsv")]
        m = LABEL.match(label)
        if not m:
            continue
        row = tsv(path)
        for line in (LOGS / f"{label}_time.txt").read_text(encoding="utf-8").splitlines():
            if "Maximum resident set size" in line:
                row["peak_rss_gb"] = int(line.rsplit(":", 1)[1]) * 1024 / 1e9
        got[m.group("arm")].append(row)
    return got


def span(xs: list[float], fmt: str) -> str:
    return f"{statistics.mean(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def main() -> int:
    data = runs()
    if not all(data.values()):
        print("腕の本がそろっていない")
        return 1
    print(f"本数: {', '.join(f'{a} {len(data[a])}' for a in ARMS)}")
    print()
    head = [f"`{a}`（平均と範囲）" for a in ARMS] + [f"`{a}` − `old`" for a in ARMS[1:]]
    print("| 量 | " + " | ".join(head) + " |")
    print("|---|" + "---|" * (len(ARMS) + 2))
    for key, name in KEYS:
        fmt = ".0f" if key == "minflt_F1" else ".3f" if key == "peak_rss_gb" else ".2f"
        cells = [span([r[key] for r in data[a]], fmt) for a in ARMS]
        base = statistics.mean(r[key] for r in data["old"])
        diffs = [f"{statistics.mean(r[key] for r in data[a]) - base:+{fmt}}" for a in ARMS[1:]]
        print(f"| {name} | " + " | ".join(cells + diffs) + " |")
    stages = tsv(ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
    now = sum(stages[s] for s in STAGES)
    base = statistics.mean(r["F1"] for r in data["old"])
    print()
    print("## 換算（秒）")
    print()
    print(f"- いまの作りの対応する段（{' ＋ '.join(STAGES)}）: {now:.2f}")
    for a in ARMS[1:]:
        d = statistics.mean(r["F1"] for r in data[a]) - base
        est = LOOP + WRITE + d
        print(f"- `{a}`: F1 の差 {d:+.2f}（外挿 {EXTRAP} の {d / EXTRAP:.2f} 倍）。"
              f"見積もり {LOOP} ＋ {WRITE} ＋ {d:.2f} ＝ {est:.2f}、"
              f"いまの作りとの差 {est - now:+.2f}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
