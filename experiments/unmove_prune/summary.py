#!/usr/bin/python3
"""集計と換算 (実験 unmove_prune。記録試行ではない)。

    python3 experiments/unmove_prune/summary.py > experiments/unmove_prune/logs/summary.txt

1. 生成器だけ (logs/timing.tsv。run_time.sh)
   - 版 × 列 (unknown / try / expand) の ns/局面と1局面あたりの出力の数. 5周の中央値と範囲
   - 絞った版 − 素朴な版を, 段階 (cand / sieve / visit) ごとに同じ周どうしで取り, 中央値と範囲
2. 試作の後退解析 (logs/retreat_<ラベル>.txt の RESULT 行。run_retreat.sh)
   - 版ごと (naive / pruned) のループの秒の中央値と範囲 (各3本)
   - pruned − naive を, 並び (naive pruned pruned naive naive pruned) の隣どうしの組
     (1-2, 4-3, 5-6) で取る
   - 候補の減り (naive − pruned) と, naive がキャッチ局面を理由に捨てた候補の数
   - 絞った版の候補のうち, 到達しない局面で捨てた割合
換算 (秒):
   作り替えた後退解析の見積もり = pruned のループ (各本) ＋ B1′ の費用
   ＋ 全局面の種類と残りの数を書く費用
   - B1′ の費用: experiments/attack_count/logs/timing.tsv から, attack_count の summary.py と
     同じ計算 ((b1x − gen) × 種類ごとの局面数を周ごとに足す) の中央値
   - 書く費用: experiments/unmove_bench/logs/timing.tsv の degw (mixed) の中央値 × 246,803,167
   - いまの P1 ＋ P2 ＋ P4 ＋ 174段ループ (results/33_hot_layout/retreat_summary.tsv の生値) との差
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
N_ALL = 246_803_167
COUNTS = {"unknown": 99_485_568, "catch": 140_298_614, "try": 7_018_985}
PAIRS = ((1, 2), (4, 3), (5, 6))
STAGES = ("P1", "P2", "P4", "loop174")
SAMPLES = ("unknown", "try", "expand")
STEPS = ("cand", "sieve", "visit")
FIELDS = (
    "init_sec",
    "loop_sec",
    "steps",
    "expanded",
    "candidates",
    "kept",
    "drop_none",
    "drop_catch",
    "drop_try",
    "zero_first",
    "mismatch",
)


def mid(xs: list[float], fmt: str = ".1f") -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


Table = dict[tuple[str, str], dict[int, float]]


def read_timing(path: pathlib.Path) -> tuple[Table, Table]:
    ns: Table = {}
    out: Table = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            key = (row["version"], row["sample"])
            ns.setdefault(key, {})[int(row["round"])] = float(row["ns_per_q"])
            out.setdefault(key, {})[int(row["round"])] = float(row["out_per_q"])
    return ns, out


def row(label: str, cells: list[str]) -> None:
    print(f"| {label} | " + " | ".join(cells) + " |")


def diff(data: Table, a: str, b: str, s: str, rounds: list[int]) -> str:
    return mid([data[(a, s)][r] - data[(b, s)][r] for r in rounds])


def retreat_results() -> dict[int, tuple[str, dict[str, float]]]:
    res: dict[int, tuple[str, dict[str, float]]] = {}
    for path in sorted(LOGS.glob("retreat_a*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RESULT\t"):
                parts = line.split("\t")
                ver, label = parts[1], parts[2]
                res[int(label[1 : label.index("_")])] = (
                    ver,
                    dict(zip(FIELDS, map(float, parts[3:]), strict=True)),
                )
    return res


def b1x_cost() -> float:
    data, _ = read_timing(ROOT / "experiments" / "attack_count" / "logs" / "timing.tsv")
    rounds = sorted({r for v in data.values() for r in v})
    costs = [
        sum((data[("b1x", s)][r] - data[("gen", s)][r]) * n for s, n in COUNTS.items()) / 1e9
        for r in rounds
    ]
    return statistics.median(costs)


def degw_cost() -> float:
    data, _ = read_timing(ROOT / "experiments" / "unmove_bench" / "logs" / "timing.tsv")
    return statistics.median(data[("degw", "mixed")].values()) * N_ALL / 1e9


def timing_section() -> None:
    tsv = LOGS / "timing.tsv"
    if not tsv.exists():
        return
    data, out = read_timing(tsv)
    rounds = sorted({r for v in data.values() for r in v})
    print(f"## 1. 生成器だけ（周: {len(rounds)}）")
    print()
    print("### ns/局面（中央値と範囲）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for p in ("n", "p"):
        for st in STEPS:
            v = p + st
            row(f"`{v}`", [mid([data[(v, s)][r] for r in rounds]) for s in SAMPLES])
    print()
    print("### 1局面あたりの出力の数（候補・前任。周で変わらない）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for p in ("n", "p"):
        for st in STEPS:
            v = p + st
            row(f"`{v}`", [f"{out[(v, s)][rounds[0]]:.3f}" for s in SAMPLES])
    print()
    print("### 絞った版 − 素朴な版（ns/局面。同じ周どうしの差の中央値と範囲）")
    print()
    print("| 段階 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for st in STEPS:
        row(f"`p{st}` − `n{st}`", [diff(data, "p" + st, "n" + st, s, rounds) for s in SAMPLES])
    print()
    print("### 段階どうしの差（ns/局面）")
    print()
    print("| 差 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for p in ("n", "p"):
        for a, b in (("sieve", "cand"), ("visit", "sieve")):
            row(f"`{p}{a}` − `{p}{b}`", [diff(data, p + a, p + b, s, rounds) for s in SAMPLES])
    print()


def main() -> int:
    timing_section()
    res = retreat_results()
    if not res:
        return 0
    print("## 2. 試作の後退解析（drop）")
    print()
    head = ("本", "版", "初期化（秒）", "ループ（秒）", "段", "展開した局面", "候補", "残った前任",
            "捨てた: 到達しない", "捨てた: キャッチ", "食い違い")  # fmt: skip
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for i in sorted(res):
        v, r = res[i]
        print(
            f"| {i} | `{v}` | {r['init_sec']:.2f} | {r['loop_sec']:.2f} | {r['steps']:.0f} | "
            f"{r['expanded']:,.0f} | {r['candidates']:,.0f} | {r['kept']:,.0f} | "
            f"{r['drop_none']:,.0f} | {r['drop_catch']:,.0f} | {r['mismatch']:.0f} |"
        )
    print()
    by = {v: [r for ver, r in res.values() if ver == v] for v in ("naive", "pruned")}
    for v, rs in by.items():
        if rs:
            print(f"- `{v}`: ループ {mid([r['loop_sec'] for r in rs], '.2f')} 秒（{len(rs)} 本）")
    pairs = [(res[a][1], res[b][1]) for a, b in PAIRS if a in res and b in res]
    if pairs:
        d = [p["loop_sec"] - n["loop_sec"] for n, p in pairs]
        ratio = [p["loop_sec"] / n["loop_sec"] for n, p in pairs]
        print(f"- `pruned` − `naive`（隣どうしの組 {len(pairs)} つ）: "
              f"ループ {mid(d, '.2f')} 秒、比 {mid(ratio, '.3f')}")  # fmt: skip
    if by["naive"] and by["pruned"]:
        n, p = by["naive"][0], by["pruned"][0]
        cut = n["candidates"] - p["candidates"]
        print(
            f"- 候補の減り（naive − pruned）: {cut:,.0f}。naive でキャッチ局面を理由に捨てた候補 "
            f"{n['drop_catch']:,.0f}（{'一致' if cut == n['drop_catch'] else '不一致'}）。"
            f"pruned でキャッチ局面を理由に捨てた候補 {p['drop_catch']:,.0f}"
        )
        print(
            f"- 絞った版の候補のうち到達しない局面で捨てた割合: "
            f"{p['drop_none']:,.0f} / {p['candidates']:,.0f} = "
            f"{p['drop_none'] / p['candidates'] * 100:.1f}%"
            f"（素朴な版では {n['drop_none'] / n['candidates'] * 100:.1f}%）"
        )
    if not by["pruned"]:
        return 0
    stages = dict(
        ln.split("\t", 1)
        for ln in (ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    now4 = sum(float(stages[s]) for s in STAGES)
    b1x, degw = b1x_cost(), degw_cost()
    tot = [r["loop_sec"] + b1x + degw for r in by["pruned"]]
    print()
    print("## 換算（秒）")
    print()
    print(f"- B1′ の費用（attack_count の timing.tsv から。周ごとの合計の中央値）: {b1x:.2f}")
    print(f"- 種類と残りの数をランクの配列に書く（unmove_bench の degw mixed の中央値 "
          f"× {N_ALL:,}）: {degw:.2f}")  # fmt: skip
    print(f"- 作り替えた後退解析の見積もり（pruned のループ ＋ 上の2行。各本）: {mid(tot, '.2f')}")
    print(f"- いまの4段 {now4:.2f} との差: {mid([t - now4 for t in tot], '.2f')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
