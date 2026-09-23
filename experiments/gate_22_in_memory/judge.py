#!/usr/bin/python3
"""判定の量と、中間ファイルに関わる量を3腕で比べる (門番 #22)。

    python3 experiments/gate_22_in_memory/judge.py

判定の量は **J ＝ forward_total ＋ P0**（秒）。old と chunk・whole でコードが違うのは、
ここに入る段だけ（全探索の F0・F2・F5 と、後退解析の P0）。

採る腕の規則（門番を回す前に README に書いた）:
  whole − chunk の 95% 区間が 0 をまたがずに上（whole が遅い）ときだけ chunk を採る。
  0 を含むときと、0 をまたがずに下（whole が速い）ときは whole を採る。

比較は3本（chunk − old、whole − old、whole − chunk）。p 値と 95% 区間はどれも
個々の比較についての値で、**多重比較は補正していない**。
数字は gate_stats.py と同じ Welch の計算。

CPU の外の時間は「壁時計 − ユーザー時間 − カーネル時間」。
⚠️ ユーザーとカーネルへの配分はタイマー割り込みの標本 (CONFIG_HZ=1000) なので、
   段ごとの合計で読む（和は正確）。
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import arms, console, p_text, samples, sd, welch  # noqa: E402

LOGS = HERE / "logs"
ARMS = ("old", "chunk", "whole")
# (差の名前, 引かれる腕, 引く腕)。差は「後 − 前」
PAIRS = (("chunk − old", "old", "chunk"), ("whole − old", "old", "whole"),
         ("whole − chunk", "chunk", "whole"))  # fmt: skip
J = "J ＝ forward_total ＋ P0"
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)")
MAXRSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")


def tsv(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def elapsed(text: str) -> float:
    m = ELAPSED.search(text)
    if not m:
        raise SystemExit("time.txt に Elapsed の行が無い")
    sec = 0.0
    for part in m.group(1).split(":"):
        sec = sec * 60 + float(part)
    return sec


def quantities(label: str) -> dict[str, float]:
    """1本ぶんの量。どれも要約ファイルと time.txt の生値から計算する。"""
    f = tsv(LOGS / f"{label}_forward_summary.tsv")
    r = tsv(LOGS / f"{label}_retreat_summary.tsv")
    time_txt = (LOGS / f"{label}_time.txt").read_text(encoding="utf-8")

    def fw(k: str) -> float:
        return float(f[k])

    def off(a: str, b: str) -> float:
        """後退解析の境界 a → b の、CPU の外の時間。"""
        wall = float(r["t_" + b]) - float(r["t_" + a])
        cpu = sum(float(r[f"{kind}_{b}"]) - float(r[f"{kind}_{a}"]) for kind in ("utime", "stime"))
        return wall - cpu

    maxrss = MAXRSS.search(time_txt)
    if not maxrss:
        raise SystemExit(f"{label}_time.txt に Maximum resident の行が無い")
    return {
        J: fw("forward_total") + float(r["P0"]),
        "forward_total": fw("forward_total"),
        "P0": float(r["P0"]),
        "F0 ＋ F2 ＋ F5": fw("F0") + fw("F2") + fw("F5"),
        "F1": fw("F1"),
        "F6": fw("F6"),
        "全探索のカーネル時間": fw("stime_forward_total"),
        "全探索の CPU の外": fw("forward_total")
        - fw("utime_forward_total")
        - fw("stime_forward_total"),
        "F6 の CPU の外": fw("F6") - fw("utime_F6") - fw("stime_F6"),
        "174段ループの CPU の外": off("R_dtm", "R_loop"),
        "R_uk の CPU の外": off("R_draw", "R_uk"),
        "後退解析の CPU の外": off("R_start", "R_uk"),
        "retreat_total": float(r["retreat_total"]),
        "全探索のピーク RSS (GiB)": int(f["hwm_release_seen"]) / 2**30,
        "全体のピーク RSS (GiB)": int(maxrss.group(1)) * 1024 / 2**30,
        "ラウンド数": fw("rounds"),
        "完走 (秒)": elapsed(time_txt),
    }


def collect() -> tuple[dict[str, str], dict[str, dict[str, float]]]:
    """(ラベル → 腕, 量の名前 → (ラベル → 値))。"""
    by_label = arms(console(LOGS, "forward"))
    per_label = {lb: quantities(lb) for lb in by_label}
    names = list(next(iter(per_label.values())))
    return by_label, {n: {lb: per_label[lb][n] for lb in by_label} for n in names}


def decide(
    by_label: dict[str, str], values: dict[str, float]
) -> tuple[str, tuple[float, float, float, float, float, float]]:
    """採る腕と、whole − chunk の (差, t, 自由度, p, 下限, 上限)。"""
    w = welch(samples(values, by_label, "chunk"), samples(values, by_label, "whole"))
    return ("chunk" if w[4] > 0 else "whole"), w


def main() -> int:
    by_label, table = collect()
    counts = {a: sum(1 for x in by_label.values() if x == a) for a in ARMS}
    print("### 腕ごとの平均（sd）")
    print()
    print("| 量 | " + " | ".join(f"`{a}` {counts[a]}本" for a in ARMS) + " |")
    print("|---|" + "---|" * len(ARMS))
    for name, values in table.items():
        cells = []
        for a in ARMS:
            xs = samples(values, by_label, a)
            cells.append(f"{sum(xs) / len(xs):.2f}（sd {sd(xs):.2f}）")
        print(f"| {name} | " + " | ".join(cells) + " |")
    print()
    print("### 差（95% 区間、p）。3本とも多重比較未補正")
    print()
    print("| 量 | " + " | ".join(name for name, _a, _b in PAIRS) + " |")
    print("|---|" + "---|" * len(PAIRS))
    for name, values in table.items():
        if name == "ラウンド数":
            continue
        cells = []
        for _pair, a, b in PAIRS:
            d, _t, _df, p, lo, hi = welch(
                samples(values, by_label, a), samples(values, by_label, b)
            )
            cells.append(f"{d:+.2f}（{lo:+.2f} … {hi:+.2f}、p {p_text(p)}）")
        print(f"| {name} | " + " | ".join(cells) + " |")
    print()
    adopted, (d, t, df, p, lo, hi) = decide(by_label, table[J])
    print(f"### 判定: {J} の whole − chunk")
    print()
    print(
        f"差 {d:+.2f} 秒（区間 {lo:+.2f} … {hi:+.2f}、t {t:.2f}、自由度 {df:.2f}、p {p_text(p)}）"
    )
    if lo > 0:
        reason = "区間が 0 をまたがずに上（whole が遅い）"
    elif hi < 0:
        reason = "区間が 0 をまたがずに下（whole が速い）"
    else:
        reason = "区間が 0 を含む"
    print(f"=> {reason}ので **{adopted}** を採る")
    return 0


if __name__ == "__main__":
    sys.exit(main())
