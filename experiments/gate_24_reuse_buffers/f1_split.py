#!/usr/bin/python3
"""判定の量 (F1) の内訳と, 予測に登録した量の new − old を出す (門番 #24)。

    python3 experiments/gate_24_reuse_buffers/f1_split.py

F1 とそのユーザー時間・カーネル時間は forward_summary.tsv の F1 / utime_F1 / stime_F1 の生値。
⚠️ ユーザーとカーネルへの配分はタイマー割り込みの標本 (CONFIG_HZ=1000) なので, 段ごとの合計で読む。
minor fault と全体のピーク RSS は time.txt の値 (プロセス全体。段ごとの minor fault の計装は入れていない)。
全探索のピーク RSS は forward_summary.tsv の hwm_F6 (F6 を終えた時点のピーク)。
完走は参考で, 判定には使わない。数字は gate_stats.py と同じ Welch の計算。比較は old 対 new の1本だけ。
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
    f = tsv(LOGS / f"{label}_forward_summary.tsv")
    r = tsv(LOGS / f"{label}_retreat_summary.tsv")
    time_txt = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")
    found = [ELAPSED.search(time_txt), MAXRSS.search(time_txt), MINFLT.search(time_txt)]
    if not all(found):
        raise SystemExit(f"{label}_time.txt に Elapsed / Maximum resident / Minor の行が無い")
    elapsed_m, maxrss_m, minflt_m = found
    assert elapsed_m and maxrss_m and minflt_m
    sec = 0.0
    for part in elapsed_m.group(1).split(":"):
        sec = sec * 60 + float(part)
    return {
        "F1": float(f["F1"]),
        "F1 のユーザー時間": float(f["utime_F1"]),
        "F1 のカーネル時間": float(f["stime_F1"]),
        "F2": float(f["F2"]),
        "F6": float(f["F6"]),
        "F6 のカーネル時間": float(f["stime_F6"]),
        "forward_total": float(f["forward_total"]),
        "retreat_total": float(r["retreat_total"]),
        "minor fault (万)": int(minflt_m.group(1)) / 1e4,
        "全探索のピーク RSS (GiB)": int(f["hwm_F6"]) / 2**30,
        "全体のピーク RSS (GiB)": int(maxrss_m.group(1)) * 1024 / 2**30,
        "完走 (秒、参考)": sec,
    }


def main() -> int:
    by_label = arms(console(LOGS, "forward"))
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
