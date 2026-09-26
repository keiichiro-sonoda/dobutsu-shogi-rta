#!/usr/bin/python3
"""README に貼る表を生ログから組み立てる (実験 lever_scan_2。記録試行ではない)。

    python3 experiments/lever_scan_2/summary.py > experiments/lever_scan_2/logs/summary.txt

⚠️ 表を手で書かない (CLAUDE.md「段ごとの揺れの標本と統計値は手で書かない」)。
数字は gate_stats.py と同じ Welch の計算。比較は6本 (base に対して5本と, pf3 − pf2 の1本) で,
p 値と 95% 区間はどれも個々の比較についての値 (多重比較未補正)。

  狙う段   測る前に「下がる」と登録した段 (README の事前登録の表)
  内訳     狙う段のユーザー時間・カーネル時間 (と F1 の minor fault)。タイマー割り込みの標本なので
           段ごとの合計で読む (CONFIG_HZ=1000)
  対照     「触らないはずの段」。区間が 0 をまたがないものは名指しで出す
  巨大ページ  174段ループの配列が生きているうち (R_uk のあと) の AnonHugePages と, vmstat の前後差
  参考     完走の壁時計 (判定には使わない)
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections.abc import Callable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from gate_stats import collect, p_text, samples, sd, welch  # noqa: E402

GATE = "lever_scan_2"
LOGS = HERE / "logs"
FWD = "forward"
RET = "spans"
ARMS = ("base", "pf2", "pf3", "hugeR", "reuse", "all")
# (腕, 引かれる腕)。base に対して5本と, pf3 − pf2
PAIRS = (("pf2", "base"), ("pf3", "base"), ("hugeR", "base"), ("reuse", "base"),
         ("all", "base"), ("pf3", "pf2"))  # fmt: skip
TARGETS = {
    "pf2": [(RET, "loop174")],
    "pf3": [(RET, "loop174")],
    "hugeR": [(RET, "loop174"), (RET, "P4"), (RET, "P4_count"), (RET, "P4_scatter")],
    "reuse": [(FWD, "F1 展開")],
    "all": [(RET, "loop174"), (FWD, "F1 展開")],
}
FWD_ALL = [
    "F0 未探索の読み込み",
    "F1 展開",
    "F2 未知の書き出し",
    "F5 未探索の書き出し",
    "F6 終端の書き出し",
]
CONTROLS = {
    "pf2": [(FWD, s) for s in FWD_ALL] + [(RET, s) for s in ("P0", "P1", "P2", "P4")],
    "pf3": [(FWD, s) for s in FWD_ALL] + [(RET, s) for s in ("P0", "P1", "P2", "P4")],
    "hugeR": [(FWD, s) for s in FWD_ALL] + [(RET, "P2_loop")],
    "reuse": [(RET, s) for s in ("P0", "P1", "P2", "P4", "loop174")],
}
# 向きを登録しなかった段 (動いてもよい。差を出すだけ)
UNREGISTERED = {
    "hugeR": [(RET, "P2_alloc"), (RET, "R_dtm")],
    "reuse": [(FWD, "F2 未知の書き出し"), (FWD, "F6 終端の書き出し")],
}
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)")


def tsv(path: pathlib.Path) -> dict[str, str]:
    return dict(ln.split("\t", 1) for ln in path.read_text(encoding="utf-8").splitlines())


def span_cpu(kind: str, a: str, b: str) -> Callable[[str], float]:
    """後退解析の境界 a → b の utime / stime。"""

    def f(label: str) -> float:
        r = tsv(LOGS / f"{label}_retreat_summary.tsv")
        return float(r[f"{kind}_{b}"]) - float(r[f"{kind}_{a}"])

    return f


def fwd_key(key: str) -> Callable[[str], float]:
    def f(label: str) -> float:
        return float(tsv(LOGS / f"{label}_forward_summary.tsv")[key])

    return f


def elapsed(label: str) -> float:
    m = ELAPSED.search((LOGS / f"{label}_time.txt").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"{label}_time.txt に Elapsed が無い")
    sec = 0.0
    for part in m.group(1).split(":"):
        sec = sec * 60 + float(part)
    return sec


# 内訳 (名前, 取り出し方, 見る腕)
DETAIL = [
    (
        "loop174 のユーザー時間",
        span_cpu("utime", "R_dtm", "R_loop"),
        ("pf2", "pf3", "hugeR", "all"),
    ),
    (
        "loop174 のカーネル時間",
        span_cpu("stime", "R_dtm", "R_loop"),
        ("pf2", "pf3", "hugeR", "all"),
    ),
    ("P4 のユーザー時間", span_cpu("utime", "P2_free", "P4"), ("hugeR", "all")),
    ("P4 のカーネル時間", span_cpu("stime", "P2_free", "P4"), ("hugeR", "all")),
    ("F1 のユーザー時間", fwd_key("utime_F1"), ("reuse", "all")),
    ("F1 のカーネル時間", fwd_key("stime_F1"), ("reuse", "all")),
    ("F1 の minor fault", fwd_key("minflt_F1"), ("reuse", "all")),
]


def load() -> tuple[dict[str, str], dict[str, dict[str, dict[str, float]]]]:
    out = {}
    by_label: dict[str, str] = {}
    for mode in (FWD, RET):
        by_label, _order, rows = collect(GATE, mode)
        out[mode] = dict(rows)
    return by_label, out


def cmp(values: dict[str, float], by_label: dict[str, str], arm: str, ref: str) -> str:
    d, _t, _df, p, lo, hi = welch(samples(values, by_label, ref), samples(values, by_label, arm))
    verdict = "またぐ" if lo <= 0 <= hi else ("下がる" if hi < 0 else "上がる")
    return f"{d:+.2f}（{lo:+.2f} … {hi:+.2f}） | {p_text(p)} | {verdict}"


def mean_sd(values: dict[str, float], by_label: dict[str, str], arm: str) -> str:
    xs = samples(values, by_label, arm)
    return f"{sum(xs) / len(xs):.2f}（sd {sd(xs):.2f}）"


def label_of(mode: str, stage: str) -> str:
    if mode == FWD:
        return stage if stage.startswith("全探索") else "全探索 " + stage
    return "後退解析 " + stage


def vmstat_delta(label: str, key: str) -> int:
    rows = [ln.split("\t") for ln in (LOGS / f"{label}_vmstat.tsv").read_text().splitlines()]
    i = rows[0].index(key)
    return int(rows[2][i]) - int(rows[1][i])


def main() -> int:
    by_label, data = load()
    n = {a: sum(1 for x in by_label.values() if x == a) for a in ARMS}
    print(f"本数: {n}。比較は6本で、p 値と 95% 区間は多重比較未補正")
    print()
    print("### 狙う段")
    print()
    print("| 腕 | 狙う段 | 基準の腕 | 基準の平均 | 差（95% 区間） | p | 判定 |")
    print("|---|---|---|---|---|---|---|")
    for arm, targets in TARGETS.items():
        for mode, stage in targets:
            values = data[mode][stage]
            ref = mean_sd(values, by_label, "base")
            print(f"| `{arm}` | {label_of(mode, stage)} | `base` | {ref} | ", end="")
            print(cmp(values, by_label, arm, "base") + " |")
    values = data[RET]["loop174"]
    ref = mean_sd(values, by_label, "pf2")
    print(f"| `pf3` | 後退解析 loop174 | `pf2` | {ref} | {cmp(values, by_label, 'pf3', 'pf2')} |")
    print()
    print("### 内訳（ユーザー時間・カーネル時間・minor fault）")
    print()
    print("| 量 | 腕 | 基準の平均 | 差（95% 区間） | p | 判定 |")
    print("|---|---|---|---|---|---|")
    for name, get, arms_ in DETAIL:
        values = {lb: get(lb) for lb in by_label}
        for arm in arms_:
            print(f"| {name} | `{arm}` − `base` | {mean_sd(values, by_label, 'base')} | "
                  f"{cmp(values, by_label, arm, 'base')} |")  # fmt: skip
        if name.startswith("loop174"):
            print(f"| {name} | `pf3` − `pf2` | {mean_sd(values, by_label, 'pf2')} | "
                  f"{cmp(values, by_label, 'pf3', 'pf2')} |")  # fmt: skip
    print()
    print("### 対照の段（触らないはずの段）")
    print()
    print("| 腕 | 対照の段 | 区間が 0 をまたがなかった段 | 差の絶対値の最大 |")
    print("|---|---|---|---|")
    for arm, ctrls in CONTROLS.items():
        moved = []
        worst = 0.0
        for mode, stage in ctrls:
            values = data[mode][stage]
            d, _t, _df, _p, lo, hi = welch(
                samples(values, by_label, "base"), samples(values, by_label, arm)
            )
            worst = max(worst, abs(d))
            if not lo <= 0 <= hi:
                moved.append(f"{label_of(mode, stage)} {d:+.2f}（{lo:+.2f} … {hi:+.2f}）")
        names = "・".join(stage.split(" ")[0] for _m, stage in ctrls)
        print(f"| `{arm}` | {names} | {'、'.join(moved) or 'なし'} | {worst:.2f} |")
    print()
    print("### 向きを登録しなかった段")
    print()
    print("| 腕 | 段 | 基準の平均 | 差（95% 区間） | p | 判定 |")
    print("|---|---|---|---|---|---|")
    for arm, stages in UNREGISTERED.items():
        for mode, stage in stages:
            values = data[mode][stage]
            print(f"| `{arm}` | {label_of(mode, stage)} | {mean_sd(values, by_label, 'base')} | "
                  f"{cmp(values, by_label, arm, 'base')} |")  # fmt: skip
    print()
    print("### 巨大ページ（R_uk のあとの AnonHugePages と、/proc/vmstat の前後差）")
    print()
    print("| 腕 | `anonhuge_loop_kB`（最小〜最大） | 索引・発見済み表が全部 | "
          "`thp_fault_fallback` の和 | `compact_stall`（最小〜最大） |")  # fmt: skip
    print("|---|---|---|---|---|")
    for arm in ARMS:
        labels = [lb for lb, a in by_label.items() if a == arm]
        loop = [int(tsv(LOGS / f"{lb}_retreat_summary.tsv")["anonhuge_loop_kB"]) for lb in labels]
        full = all(
            int(tsv(LOGS / f"{lb}_retreat_summary.tsv")["anonhuge_index_kB"]) >= 8_388_608
            and int(tsv(LOGS / f"{lb}_forward_summary.tsv")["anonhuge_seen_kB"]) >= 4_194_304
            for lb in labels
        )
        fb = sum(vmstat_delta(lb, "thp_fault_fallback") for lb in labels)
        cs = [vmstat_delta(lb, "compact_stall") for lb in labels]
        print(f"| `{arm}` | {min(loop):,}〜{max(loop):,} | {'はい' if full else '**いいえ**'} | "
              f"{fb} | {min(cs)}〜{max(cs)} |")  # fmt: skip
    print()
    print("### 参考: 完走の壁時計（判定には使わない）")
    print()
    values = {lb: elapsed(lb) for lb in by_label}
    print("| 腕 | 平均 | 差（95% 区間） | p | 判定 |")
    print("|---|---|---|---|---|")
    for arm in ARMS:
        if arm == "base":
            print(f"| `base` | {mean_sd(values, by_label, 'base')} | — | — | — |")
        else:
            mine = mean_sd(values, by_label, arm)
            print(f"| `{arm}` | {mine} | {cmp(values, by_label, arm, 'base')} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
