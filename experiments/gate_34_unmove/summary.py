#!/usr/bin/python3
"""判定の量の脇に並べる量 (門番 #34。記録試行ではない)。

    python3 experiments/gate_34_unmove/summary.py > experiments/gate_34_unmove/logs/summary.txt

判定は stop_rule.py (完走の秒) で行う。ここでは腕ごとの平均と範囲 (最小〜最大) と,
平均の差 (new − old) を並べる:
- 完走の秒・ユーザー時間・カーネル時間・minor fault・ピーク RSS (/usr/bin/time -v)
- 全探索の合計・F1・F5・F1 の minor fault (forward_summary.tsv)
- 後退解析の合計と, 腕ごとの段 (retreat_summary.tsv。old は P0〜R_uk, new は U_init〜U_uk)
"""

from __future__ import annotations

import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>[^\s:)]+)[:\s)]")
TIME = {
    "elapsed": re.compile(
        r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)"
    ),
    "user": re.compile(r"User time \(seconds\): ([\d.]+)"),
    "system": re.compile(r"System time \(seconds\): ([\d.]+)"),
    "minflt": re.compile(r"Minor \(reclaiming a frame\) page faults: (\d+)"),
    "rss_gb": re.compile(r"Maximum resident set size \(kbytes\): (\d+)"),
}
FORWARD = ("forward_total", "F1", "F5", "minflt_F1")
RETREAT = {
    "old": ("retreat_total", "P0", "P1", "P2", "P4", "R_dtm", "loop174", "R_draw", "R_uk"),
    "new": ("retreat_total", "U_init", "U_loop", "U_draw", "U_uk"),
}


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def row(label: str) -> dict[str, float]:
    text = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for key, pat in TIME.items():
        m = pat.search(text)
        if not m:
            raise SystemExit(f"{label}_time.txt に {key} が無い")
        if key == "elapsed":
            out[key] = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        elif key == "rss_gb":
            out[key] = int(m.group(1)) * 1024 / 1e9
        else:
            out[key] = float(m.group(1))
    out.update(tsv(LOGS / f"{label}_forward_summary.tsv"))
    out.update(tsv(LOGS / f"{label}_retreat_summary.tsv"))
    return out


def span(xs: list[float], fmt: str) -> str:
    return f"{statistics.mean(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def main() -> int:
    started: dict[str, str] = {}
    for line in (LOGS / "console.log").read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            started[m.group("label")] = m.group("arm")
    rows = {a: [row(lb) for lb, x in started.items() if x == a] for a in ("old", "new")}
    print(f"本数: old {len(rows['old'])} / new {len(rows['new'])}")
    print()
    print("| 量 | `old`（平均と範囲） | `new`（平均と範囲） | new − old |")
    print("|---|---|---|---|")
    for key in ("elapsed", "user", "system", "minflt", "rss_gb", *FORWARD, "retreat_total"):
        fmt = ".0f" if "minflt" in key else ".3f" if key == "rss_gb" else ".2f"
        a, b = [r[key] for r in rows["old"]], [r[key] for r in rows["new"]]
        d = statistics.mean(b) - statistics.mean(a)
        print(f"| {key} | {span(a, fmt)} | {span(b, fmt)} | {d:+{fmt}} |")
    for arm in ("old", "new"):
        print()
        print(f"### `{arm}` の後退解析の段（秒）")
        print()
        for key in RETREAT[arm]:
            print(f"- {key}: {span([r[key] for r in rows[arm]], '.2f')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
