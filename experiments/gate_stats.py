#!/usr/bin/python3
"""門番の生ログから、段ごとの平均・標準偏差と Welch 検定の表を組み立てる。

    python3 experiments/gate_stats.py <門番> <retreat|forward|spans> [基準腕] [比較 ...]

    python3 experiments/gate_stats.py gate_17_no_set retreat
    python3 experiments/gate_stats.py gate_17_forward forward
    python3 experiments/gate_stats.py gate_18_opt forward o0 o3:o2
    python3 experiments/gate_stats.py gate_19_c_gather spans

⚠️ 表を手で書かない。CLAUDE.md の「段ごとの揺れの標本と統計値は手で書かない」と
「統計値は生値から計算する。表示のために丸めた値から計算し直さない」を守るため、
README に貼る表はこのスクリプトの出力をそのまま使う。

腕は進行ログ (`<門番>/logs/console.log`、全探索と後退解析の両方を測る門番なら
`console_forward.log` / `console_retreat.log`) の「=== 開始 <ラベル> (<腕> ...」から取り、
**最初に現れた順**に並べる。基準腕を省略すると先頭の腕を使う。
腕が2つなら1つの表にまとめ、3つ以上なら「腕ごとの平均」と「基準腕との差」の
2つの表に分ける。`o3:o2` のように書けば任意の対をもう1行足せる。

段の出どころ:
  retreat  <ラベル>_main.log の P0/P1/P2/P4 (全角コロン, 時分秒) と、
           進行ログの「後退解析の所要時間：X 秒」。
           174段＋残差 = 合計 − 測った4段。
  forward  <ラベル>_forward_summary.tsv (秒の生値)。
           ⚠️ main.log の F 行は s2hms が秒未満を切り捨てた表示値なので使わない。
  spans    <ラベル>_retreat_summary.tsv の区間 (秒の生値)。段の顔ぶれは
           ファイルに並んでいる順で、実装の RETREAT_SPANS がそのまま出る。
           ⚠️ main.log の P 行も s2hms の表示値なので、こちらが出る門番では
           retreat モードではなくこちらで判定する。

scipy を入れずに t 分布の分位点を出す。正則化不完全ベータ関数を連分数で
評価し、二分法で反転する (記録 #7 の Welch 検定と同じやり方)。
"""

from __future__ import annotations

import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

HMS = re.compile(r"(\d+)時間(\d+)分(\d+)秒")
# 腕の名前は空白・コロン・閉じ括弧の手前まで. 実験 lever_scan の開始行は
# 「(base: gcc「…」パッチ「…」)」と腕のあとにコロンが来る
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<arm>[^\s:)]+)[:\s)]")
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


def console(logs: pathlib.Path, mode: str) -> pathlib.Path:
    """進行ログの場所。

    ⚠️ 1つの門番が全探索と後退解析の両方を測ることがある (記録 #18)。その場合は
    `console_forward.log` / `console_retreat.log` に分ける。片方しか測らない門番は
    `console.log` のまま (記録 #17 までの門番がそう)。
    `spans` モードは後退解析の区間を読むので、`console_retreat.log` を見る
    (実験 lever_scan が最初。`console_spans.log` という名前は作らない)。
    """
    split = logs / f"console_{'retreat' if mode == 'spans' else mode}.log"
    return split if split.exists() else logs / "console.log"


def arms(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = START.match(line)
        if m:
            out[m.group("label")] = m.group("arm")
    return out


def arm_order(path: pathlib.Path) -> list[str]:
    """腕を進行ログに最初に現れた順で返す。"""
    seen: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = START.match(line)
        if m and m.group("arm") not in seen:
            seen.append(m.group("arm"))
    return seen


def totals(path: pathlib.Path, pattern: re.Pattern[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    label = None
    for line in path.read_text(encoding="utf-8").splitlines():
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


def retreat_spans(logs: pathlib.Path, label: str) -> dict[str, float]:
    """<ラベル>_retreat_summary.tsv の区間を、ファイルに並んでいる順で返す。

    ⚠️ 区間はファイルの先頭にまとまっていて、そのあとに境界ごとの絶対値
    (`t_` / `rss_` / `hwm_` / `min_` / `maj_`) が続く。境界のほうは引き算の
    材料なので、ここでは区間だけを取る。
    """
    out: dict[str, float] = {}
    for line in (logs / f"{label}_retreat_summary.tsv").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("\t")
        if name.startswith("t_"):
            break
        out[name] = float(value)
    if not out:
        raise SystemExit(f"{label}_retreat_summary.tsv に区間の行が無い")
    return out


def forward_phase(logs: pathlib.Path, label: str, key: str) -> float:
    for line in (logs / f"{label}_forward_summary.tsv").read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("\t")
        if name == key:
            return float(value)
    raise SystemExit(f"{label}_forward_summary.tsv に {key} が無い")


def collect(
    gate: str, mode: str
) -> tuple[dict[str, str], list[str], list[tuple[str, dict[str, float]]]]:
    logs = ROOT / "experiments" / gate / "logs"
    con = console(logs, mode)
    if not con.exists():
        raise SystemExit(f"{con} が無い")
    by_label = arms(con)
    order = arm_order(con)
    rows: list[tuple[str, dict[str, float]]] = []
    if mode == "retreat":
        total = totals(con, RETREAT_TOTAL)
        for name, head in RETREAT_PHASES:
            rows.append((name, {lb: retreat_phase(logs, lb, head) for lb in by_label}))
        measured = {
            lb: sum(retreat_phase(logs, lb, head) for _, head in RETREAT_PHASES) for lb in by_label
        }
        rows.append(("**174段＋残差**", {lb: total[lb] - measured[lb] for lb in by_label}))
        rows.append(("後退解析 合計", total))
    elif mode == "spans":
        spans = {lb: retreat_spans(logs, lb) for lb in by_label}
        names = list(next(iter(spans.values())))
        for lb, one in spans.items():
            if list(one) != names:
                raise SystemExit(f"{lb} の区間の顔ぶれが他と違う: {list(one)}")
        for name in names:
            rows.append((name, {lb: spans[lb][name] for lb in by_label}))
    else:
        for name, key in FORWARD_PHASES:
            rows.append((name, {lb: forward_phase(logs, lb, key) for lb in by_label}))
        rows.append(("全探索 合計", totals(con, FORWARD_TOTAL)))
    return by_label, order, rows


# --------------------------------------------------------------------------
# 表を組む
# --------------------------------------------------------------------------


def samples(values: dict[str, float], by_label: dict[str, str], arm: str) -> list[float]:
    return [values[lb] for lb, a in by_label.items() if a == arm]


def p_text(p: float) -> str:
    return "< 0.0001" if p < 0.0001 else f"{p:.4f}"


def two_arm_table(
    by_label: dict[str, str], order: list[str], rows: list[tuple[str, dict[str, float]]]
) -> None:
    """腕が2つのときの1枚の表 (記録 #17 の門番と同じ書式)。"""
    a0, a1 = order
    n0 = sum(1 for a in by_label.values() if a == a0)
    n1 = sum(1 for a in by_label.values() if a == a1)
    print(f"| 段 | `{a0}` {n0}本 | `{a1}` {n1}本 | 差 | t | 自由度 | p | 95% 区間 |")
    print("|---|---|---|---|---|---|---|---|")
    for name, values in rows:
        old = samples(values, by_label, a0)
        new = samples(values, by_label, a1)
        diff, t, df, p, lo, hi = welch(old, new)
        print(
            f"| {name} | {sum(old) / len(old):.2f}（sd {sd(old):.2f}） "
            f"| {sum(new) / len(new):.2f}（sd {sd(new):.2f}） | {diff:+.2f} "
            f"| {t:.2f} | {df:.2f} | {p_text(p)} | {lo:+.2f} … {hi:+.2f} |"
        )
    print()
    print("生値:")
    for name, values in rows:
        old = ", ".join(f"{values[lb]:.2f}" for lb in sorted(by_label) if by_label[lb] == a0)
        new = ", ".join(f"{values[lb]:.2f}" for lb in sorted(by_label) if by_label[lb] == a1)
        print(f"  {name}: {a0} [{old}] / {a1} [{new}]")


def many_arm_tables(
    by_label: dict[str, str],
    order: list[str],
    rows: list[tuple[str, dict[str, float]]],
    base: str,
    extra: list[tuple[str, str]],
) -> None:
    """腕が3つ以上のとき。腕ごとの平均と、対ごとの検定を分けて出す。"""
    counts = {a: sum(1 for x in by_label.values() if x == a) for a in order}
    print("| 段 | " + " | ".join(f"`{a}` {counts[a]}本" for a in order) + " |")
    print("|---|" + "---|" * len(order))
    for name, values in rows:
        cells = []
        for a in order:
            xs = samples(values, by_label, a)
            cells.append(f"{sum(xs) / len(xs):.2f}（sd {sd(xs):.2f}）")
        print(f"| {name} | " + " | ".join(cells) + " |")
    print()
    pairs = [(base, a) for a in order if a != base] + extra
    print("| 段 | 比較 | 差 | t | 自由度 | p | 95% 区間 |")
    print("|---|---|---|---|---|---|---|")
    for name, values in rows:
        for lhs, rhs in pairs:
            diff, t, df, p, lo, hi = welch(
                samples(values, by_label, lhs), samples(values, by_label, rhs)
            )
            print(
                f"| {name} | `{rhs}` − `{lhs}` | {diff:+.2f} | {t:.2f} | {df:.2f} "
                f"| {p_text(p)} | {lo:+.2f} … {hi:+.2f} |"
            )
    print()
    print(f"⚠️ 基準腕 `{base}` に対して {len(order) - 1} 本引いている。")
    print("   p 値・95%信頼区間は個々の比較についての値で、どちらも多重比較未補正。")
    print("   区間で判断しても多重比較の問題は解消しない。")
    print()
    print("生値:")
    for name, values in rows:
        parts = []
        for a in order:
            xs = ", ".join(
                f"{values[lb]:.2f}" for lb in sorted(by_label) if by_label[lb] == a
            )
            parts.append(f"{a} [{xs}]")
        print(f"  {name}: " + " / ".join(parts))


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[2] not in ("retreat", "forward", "spans"):
        print(__doc__, file=sys.stderr)
        return 2
    gate, mode = argv[1], argv[2]
    by_label, order, rows = collect(gate, mode)
    base = order[0]
    extra: list[tuple[str, str]] = []
    for arg in argv[3:]:
        if ":" in arg:
            rhs, lhs = arg.split(":", 1)
            extra.append((lhs, rhs))
        else:
            base = arg
    for a in [base] + [x for pair in extra for x in pair]:
        if a not in order:
            print(f"腕 {a} がログに無い。ある腕: {' '.join(order)}", file=sys.stderr)
            return 2
    if len(order) == 2 and not extra and base == order[0]:
        two_arm_table(by_label, order, rows)
    else:
        many_arm_tables(by_label, order, rows, base, extra)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
