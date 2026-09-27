#!/usr/bin/python3
"""判定の量 (loop174) の内訳と, 予測に登録した量の new − old を出す (門番 #23)。

    python3 experiments/gate_23_loop_prefetch/loop_split.py

loop174 のユーザー時間とカーネル時間は, retreat_summary.tsv の境界 R_dtm → R_loop の差。
⚠️ ユーザーとカーネルへの配分はタイマー割り込みの標本 (CONFIG_HZ=1000) なので, 段ごとの合計で読む。
minor fault とピーク RSS は time.txt の値 (プロセス全体)。完走は参考で, 判定には使わない。
数字は gate_stats.py と同じ Welch の計算。比較は old 対 new の1本だけ。
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import arms, console, p_text, samples, sd, welch  # noqa: E402

LOGS = HERE / "logs"
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)")
MAXRSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")
MINFLT = re.compile(r"Minor \(reclaiming a frame\) page faults: (\d+)")


def tsv(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def quantities(label: str) -> dict[str, float]:
    r = tsv(LOGS / f"{label}_retreat_summary.tsv")
    time_txt = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")

    def cpu(kind: str, a: str, b: str) -> float:
        return float(r[f"{kind}_{b}"]) - float(r[f"{kind}_{a}"])

    found = [ELAPSED.search(time_txt), MAXRSS.search(time_txt), MINFLT.search(time_txt)]
    if not all(found):
        raise SystemExit(f"{label}_time.txt に Elapsed / Maximum resident / Minor の行が無い")
    elapsed_m, maxrss_m, minflt_m = found
    assert elapsed_m and maxrss_m and minflt_m
    sec = 0.0
    for part in elapsed_m.group(1).split(":"):
        sec = sec * 60 + float(part)
    return {
        "loop174": float(r["loop174"]),
        "loop174 のユーザー時間": cpu("utime", "R_dtm", "R_loop"),
        "loop174 のカーネル時間": cpu("stime", "R_dtm", "R_loop"),
        "P2": float(r["P2"]),
        "retreat_total": float(r["retreat_total"]),
        "minor fault (万)": int(minflt_m.group(1)) / 1e4,
        "ピーク RSS (GiB)": int(maxrss_m.group(1)) * 1024 / 2**30,
        "完走 (秒、参考)": sec,
    }


def main() -> int:
    by_label = arms(console(LOGS, "spans"))
    per = {lb: quantities(lb) for lb in by_label}
    names = list(next(iter(per.values())))
    print("| 量 | `old` 平均（sd） | `new` 平均（sd） | `new` − `old`（95% 区間） | p |")
    print("|---|---|---|---|---|")
    for name in names:
        values = {lb: per[lb][name] for lb in by_label}
        old, new = samples(values, by_label, "old"), samples(values, by_label, "new")
        d, _t, _df, p, lo, hi = welch(old, new)
        print(
            f"| {name} | {sum(old) / len(old):.2f}（{sd(old):.2f}） | "
            f"{sum(new) / len(new):.2f}（{sd(new):.2f}） | {d:+.2f}（{lo:+.2f} … {hi:+.2f}） | "
            f"{p_text(p)} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
