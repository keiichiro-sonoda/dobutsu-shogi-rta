#!/usr/bin/python3
"""門番 #17 の生ログから、段ごとの平均・標準偏差と Welch 検定の表を組み立てる。

    python3 experiments/gate_17_no_set/stats.py retreat
    python3 experiments/gate_17_no_set/stats.py forward

⚠️ 表を手で書かない。CLAUDE.md の「段ごとの揺れの標本と統計値は手で書かない」と
「統計値は生値から計算する。表示のために丸めた値から計算し直さない」を守るため、
README に貼る表はこのスクリプトの出力をそのまま使う。

後退解析側 (retreat) は experiments/gate_17_no_set/logs/ を、
全探索側 (forward) は experiments/gate_17_forward/logs/ を読む。
どちらの腕かは console.log の「=== 開始 <ラベル> (<腕> ...」から取る。

段の出どころ:
  retreat  <ラベル>_main.log の P0/P1/P2/P4 (全角コロン, 時分秒) と、
           console.log の「後退解析の所要時間：X 秒」。
           174段＋残差 = 合計 − 測った4段。
  forward  <ラベル>_forward_summary.tsv (秒の生値)。
           ⚠️ main.log の F 行は s2hms が秒未満を切り捨てた表示値なので使わない。

scipy を入れずに t 分布の分位点を出す。正則化不完全ベータ関数を連分数で
評価し、二分法で反転する (記録 #7 の Welch 検定と同じやり方)。
"""

from __future__ import annotations

import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

HMS = re.compile(r"(\d+)時間(\d+)分(\d+)秒")
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>old|new) ")
RETREAT_TOTAL = re.compile(r"^後退解析の所要時間：(?P<sec>[\d.]+) 秒")
FORWARD_TOTAL = re.compile(r"^全探索の所要時間：(?P<sec>[\d.]+) 秒")

RETREAT_PHASES = (
    ("P0 読み込み", "P0 読み込み"),
    ("P1 索引", "P1 索引"),
    ("P2 後続生成", "P2 後続生成"),
    ("P4 前任リスト", "P4 前任リスト"),
)
FORWARD_PHASES = (
    ("F0 未探索の読み込み", "F0"),
    ("F1 展開", "F1"),
    ("F2 未知の書き出し", "F2"),
    ("F5 未探索の書き出し", "F5"),
    ("F6 終端の書き出し", "F6"),
)


# --------------------------------------------------------------------------
# t 分布 (scipy なし)
# --------------------------------------------------------------------------


def betacf(a: float, b: float, x: float) -> float:
    """連分数 (Lentz の方法)。"""
    tiny = 1e-300
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """正則化不完全ベータ関数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * betacf(a, b, x) / a
    return 1.0 - front * betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """上側確率 P(T > t)。"""
    return 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t)) if t >= 0 else 1.0 - t_sf(-t, df)


def t_ppf975(df: float) -> float:
    """両側 95% の臨界値 (上側 2.5% 点)。二分法で反転する。"""
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_sf(mid, df) > 0.025:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def welch(a: list[float], b: list[float]) -> tuple[float, float, float, float, float, float]:
    """(差, t, 自由度, p, 区間下限, 区間上限)。差は b の平均 − a の平均。"""
    na, nb = len(a), len(b)
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1) if na > 1 else 0.0
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1) if nb > 1 else 0.0
    se2 = va / na + vb / nb
    diff = mb - ma
    if se2 == 0.0:
        return diff, 0.0, float(na + nb - 2), 1.0, diff, diff
    se = math.sqrt(se2)
    df = se2**2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    t = diff / se
    crit = t_ppf975(df)
    return diff, t, df, 2.0 * t_sf(abs(t), df), diff - crit * se, diff + crit * se


def sd(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# --------------------------------------------------------------------------
# ログを読む
# --------------------------------------------------------------------------


def arms(logs: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in (logs / "console.log").read_text(encoding="utf-8").splitlines():
        m = START.match(line)
        if m:
            out[m.group("label")] = m.group("arm")
    return out


def totals(logs: pathlib.Path, pattern: re.Pattern[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    label = None
    for line in (logs / "console.log").read_text(encoding="utf-8").splitlines():
        m = START.match(line)
        if m:
            label = m.group("label")
            continue
        m2 = pattern.match(line)
        if m2 and label:
            out[label] = float(m2.group("sec"))
    return out


def retreat_phase(logs: pathlib.Path, label: str, head: str) -> float:
    for line in (logs / f"{label}_main.log").read_text(encoding="utf-8").splitlines():
        if line.startswith(head + "："):
            h, m, s = (int(g) for g in HMS.search(line).groups())
            return h * 3600 + m * 60 + s
    raise SystemExit(f"{label}_main.log に「{head}」の行が無い")


def forward_phase(logs: pathlib.Path, label: str, key: str) -> float:
    for line in (logs / f"{label}_forward_summary.tsv").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("\t")
        if name == key:
            return float(value)
    raise SystemExit(f"{label}_forward_summary.tsv に {key} が無い")


def collect(mode: str) -> tuple[dict[str, str], list[tuple[str, dict[str, float]]]]:
    if mode == "retreat":
        logs = ROOT / "experiments" / "gate_17_no_set" / "logs"
        by_label = arms(logs)
        total = totals(logs, RETREAT_TOTAL)
        rows = []
        for name, head in RETREAT_PHASES:
            rows.append((name, {lb: retreat_phase(logs, lb, head) for lb in by_label}))
        measured = {
            lb: sum(retreat_phase(logs, lb, head) for _, head in RETREAT_PHASES) for lb in by_label
        }
        rows.append(("**174段＋残差**", {lb: total[lb] - measured[lb] for lb in by_label}))
        rows.append(("後退解析 合計", total))
        return by_label, rows
    logs = ROOT / "experiments" / "gate_17_forward" / "logs"
    by_label = arms(logs)
    rows = []
    for name, key in FORWARD_PHASES:
        rows.append((name, {lb: forward_phase(logs, lb, key) for lb in by_label}))
    rows.append(("全探索 合計", totals(logs, FORWARD_TOTAL)))
    return by_label, rows


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("retreat", "forward"):
        print(__doc__, file=sys.stderr)
        return 2
    by_label, rows = collect(argv[1])
    n_old = sum(1 for a in by_label.values() if a == "old")
    n_new = sum(1 for a in by_label.values() if a == "new")
    print(f"| 段 | `old` {n_old}本 | `new` {n_new}本 | 差 | t | 自由度 | p | 95% 区間 |")
    print("|---|---|---|---|---|---|---|---|")
    for name, values in rows:
        old = [values[lb] for lb, a in by_label.items() if a == "old"]
        new = [values[lb] for lb, a in by_label.items() if a == "new"]
        diff, t, df, p, lo, hi = welch(old, new)
        p_text = "< 0.0001" if p < 0.0001 else f"{p:.4f}"
        print(
            f"| {name} | {sum(old) / len(old):.2f}（sd {sd(old):.2f}） "
            f"| {sum(new) / len(new):.2f}（sd {sd(new):.2f}） | {diff:+.2f} "
            f"| {t:.2f} | {df:.2f} | {p_text} | {lo:+.2f} … {hi:+.2f} |"
        )
    print()
    print("生値:")
    for name, values in rows:
        old = ", ".join(f"{values[lb]:.2f}" for lb in sorted(by_label) if by_label[lb] == "old")
        new = ", ".join(f"{values[lb]:.2f}" for lb in sorted(by_label) if by_label[lb] == "new")
        print(f"  {name}: old [{old}] / new [{new}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
