#!/usr/bin/python3
"""集計と換算 (実験 unmove_flip。記録試行ではない)。

    python3 experiments/unmove_flip/summary.py > experiments/unmove_flip/logs/summary.txt

1. 生成器だけ (logs/timing.tsv。run_time.sh)
   - 版 × 列 (unknown / try / expand) の ns/局面と1局面あたりの出力の数. 5周の中央値と範囲
   - 反転を1回にした版 − 絞った版を, 段階 (cand / sieve / visit) ごとに同じ周どうしで取る
2. 試作の後退解析 (logs/retreat_<ラベル>.txt の RESULT 行。run_retreat.sh)
   - 版ごと (pruned / flip) のループの秒の中央値と範囲 (各3本)
   - flip − pruned を, 並び (pruned flip flip pruned pruned flip) の隣どうしの組
     (1-2, 4-3, 5-6) で取る
   - 書き出しの費用 (手数ごと・引き分けを拾う・引き分けを書く. 全探索の側は別) と,
     成果物の確かめ (logs/out_<ラベル>.txt) の結果
換算 (秒。各本で計算して中央値と範囲):
   作り替えた後退解析の見積もり = ループ ＋ B1′ の費用 ＋ 種類と残りの数を書く費用 ＋ 書き出しの費用
   - B1′ と書く費用は unmove_prune の summary.py と同じ出どころ
     (attack_count・unmove_bench の timing.tsv)
   - 比べる相手: いまの P1 ＋ P2 ＋ P4 ＋ 174段ループ ＋ R_draw ＋ R_uk
     (results/33_hot_layout/retreat_summary.tsv の生値. 手数ごとの書き出しは 174段ループの中にある)
   - 成果物の確かめが1本でも FAIL なら, 書き出しの費用を入れない換算だけを出す
   - 絞った版でも同じ換算を出し, unmove_prune の 74.79 秒 (書き出しを入れない形) とのずれも出す
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
PRUNE_EST = 74.79  # unmove_prune の換算 (experiments/unmove_prune/logs/summary.txt)
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
    "w_fwd_sec",
    "w_ret_sec",
    "draw_sec",
    "w_uk_sec",
    "draws",
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
    for p in ("p", "f"):
        for st in STEPS:
            v = p + st
            row(f"`{v}`", [mid([data[(v, s)][r] for r in rounds]) for s in SAMPLES])
    print()
    print("### 1局面あたりの出力の数（候補・前任。周で変わらない）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for p in ("p", "f"):
        for st in STEPS:
            v = p + st
            row(f"`{v}`", [f"{out[(v, s)][rounds[0]]:.3f}" for s in SAMPLES])
    print()
    print("### 反転を1回にした版 − 絞った版（ns/局面。同じ周どうしの差の中央値と範囲）")
    print()
    print("| 段階 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for st in STEPS:
        row(f"`f{st}` − `p{st}`", [diff(data, "f" + st, "p" + st, s, rounds) for s in SAMPLES])
    print()
    print("### 段階どうしの差（ns/局面）")
    print()
    print("| 差 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for p in ("p", "f"):
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
    head = ("本", "版", "ループ（秒）", "候補", "残った前任", "捨てた: 到達しない", "食い違い",
            "書く: 手数ごと", "引き分けを拾う", "書く: 引き分け", "書く: 全探索の側",
            "成果物")  # fmt: skip
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    checks = out_checks()
    for i in sorted(res):
        v, r = res[i]
        print(
            f"| {i} | `{v}` | {r['loop_sec']:.2f} | {r['candidates']:,.0f} | {r['kept']:,.0f} | "
            f"{r['drop_none']:,.0f} | {r['mismatch']:.0f} | {r['w_ret_sec']:.3f} | "
            f"{r['draw_sec']:.3f} | {r['w_uk_sec']:.3f} | {r['w_fwd_sec']:.3f} | "
            f"{checks.get(i, '-')} |"
        )
    print()
    by = {v: [r for ver, r in res.values() if ver == v] for v in ("pruned", "flip")}
    for v, rs in by.items():
        if rs:
            print(f"- `{v}`: ループ {mid([r['loop_sec'] for r in rs], '.2f')} 秒（{len(rs)} 本）、"
                  f"書き出し（手数ごと ＋ 引き分けを拾う ＋ 引き分けを書く）"
                  f" {mid([write_cost(r) for r in rs], '.2f')} 秒")  # fmt: skip
    pairs = [(res[a][1], res[b][1]) for a, b in PAIRS if a in res and b in res]
    if pairs:
        d = [f["loop_sec"] - p["loop_sec"] for p, f in pairs]
        ratio = [f["loop_sec"] / p["loop_sec"] for p, f in pairs]
        print(f"- `flip` − `pruned`（隣どうしの組 {len(pairs)} つ）: "
              f"ループ {mid(d, '.2f')} 秒、比 {mid(ratio, '.3f')}")  # fmt: skip
    if not by["flip"] or not by["pruned"]:
        return 0
    stages = dict(
        ln.split("\t", 1)
        for ln in (ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    now4 = sum(float(stages[s]) for s in STAGES)
    now_w = float(stages["R_draw"]) + float(stages["R_uk"])
    b1x, degw = b1x_cost(), degw_cost()
    use_w = len(checks) == len(res) and all(c == "PASS" for c in checks.values())
    print()
    print("## 換算（秒）")
    print()
    print(f"- B1′ の費用: {b1x:.2f} / 種類と残りの数を書く費用: {degw:.2f}")
    print(f"- いまの4段 {now4:.2f} ＋ R_draw ＋ R_uk {now_w:.2f} = {now4 + now_w:.2f}"
          "（手数ごとの書き出しは 174段ループの中にあって分けられない）")  # fmt: skip
    verdict = "全本 PASS。書き出しの費用を換算に入れる" if use_w else "外れた本がある。入れない"
    print(f"- 成果物の確かめ: {verdict}")
    for v, rs in by.items():
        base = [r["loop_sec"] + b1x + degw for r in rs]
        print(f"- `{v}`: 書き出しを入れない見積もり {mid(base, '.2f')}、いまの4段との差 "
              f"{mid([t - now4 for t in base], '.2f')}")  # fmt: skip
        if use_w:
            tot = [r["loop_sec"] + b1x + degw + write_cost(r) for r in rs]
            print(f"  書き出しを入れた見積もり {mid(tot, '.2f')}、"
                  "いまの4段 ＋ R_draw ＋ R_uk との差 "
                  f"{mid([t - now4 - now_w for t in tot], '.2f')}")  # fmt: skip
    base = [r["loop_sec"] + b1x + degw for r in by["pruned"]]
    print(f"- 絞った版の書き出しを入れない見積もりと unmove_prune の {PRUNE_EST} とのずれ: "
          f"{mid([t - PRUNE_EST for t in base], '.2f')}")  # fmt: skip
    return 0


def write_cost(r: dict[str, float]) -> float:
    return r["w_ret_sec"] + r["draw_sec"] + r["w_uk_sec"]


def out_checks() -> dict[int, str]:
    got: dict[int, str] = {}
    for path in sorted(LOGS.glob("out_a*.txt")):
        label = path.stem[len("out_") :]
        last = path.read_text(encoding="utf-8").strip().splitlines()[-1:]
        ok = last == ["成果物の確かめ: PASS"]
        got[int(label[1 : label.index("_")])] = "PASS" if ok else "FAIL"
    return got


if __name__ == "__main__":
    sys.exit(main())
