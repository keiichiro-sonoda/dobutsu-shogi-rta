#!/usr/bin/python3
"""集計と換算 (実験 unmove_catch。記録試行ではない)。

    python3 experiments/unmove_catch/summary.py > experiments/unmove_catch/logs/summary.txt

A. 試作の後退解析 (logs/retreat_<ラベル>.txt の RESULT 行。run_retreat.sh)
   - 版ごと (keep / drop) の初期化とループの秒の中央値と範囲 (各3本)
   - drop − keep を、並び (keep drop drop keep keep drop) の隣どうしの組 (1-2, 4-3, 5-6) で取り、
     中央値と範囲
   - 展開した局面・候補・残った前任・ふるいで捨てた理由 (到達しない / キャッチ / トライ負け)
B. B1・B2 (logs/timing.tsv。run_time.sh). ns/局面の中央値と範囲,
   同じ周どうしの差 (b1 − gen, b2 − gen)
換算 (秒):
   - B1: (b1 − gen) の未知の値 × 未知局面
     (全探索で後続を作るのは未知局面だけ. キャッチ局面は途中で打ち切る)
   - B2: b2 の未知の値 × 未知局面 (全探索のあとで, 生成器ごと回し直す)
   - 外す版 ＋ B1 と, #33 本走の P1 ＋ P2 ＋ P4 ＋ 174段ループ
     (results/33_hot_layout/retreat_summary.tsv の生値)
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
N_UNKNOWN = 99_485_568
PAIRS = ((1, 2), (4, 3), (5, 6))
STAGES = ("P1", "P2", "P4", "loop174")
SAMPLES = ("unknown", "catch", "try", "mixed")
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


def mid(xs: list[float], fmt: str = ".2f") -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def retreat_results() -> dict[int, tuple[str, dict[str, float]]]:
    out: dict[int, tuple[str, dict[str, float]]] = {}
    for path in sorted(LOGS.glob("retreat_a*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RESULT\t"):
                parts = line.split("\t")
                ver, label = parts[1], parts[2]
                out[int(label[1 : label.index("_")])] = (
                    ver,
                    dict(zip(FIELDS, map(float, parts[3:]), strict=True)),
                )
    return out


def main() -> int:
    res = retreat_results()
    print("## A. 試作の後退解析")
    print()
    head = ("本", "版", "初期化（秒）", "ループ（秒）", "段")
    head += ("展開した局面", "候補", "残った前任", "食い違い")
    print("| " + " | ".join(head) + " |")
    print("|---|---|---|---|---|---|---|---|---|")
    for i in sorted(res):
        v, r = res[i]
        print(
            f"| {i} | `{v}` | {r['init_sec']:.2f} | {r['loop_sec']:.2f} | {r['steps']:.0f} | "
            f"{r['expanded']:,.0f} | {r['candidates']:,.0f} | {r['kept']:,.0f} | "
            f"{r['mismatch']:.0f} |"
        )
    print()
    for v in ("keep", "drop"):
        rs = [r for ver, r in res.values() if ver == v]
        if not rs:
            continue
        print(
            f"- `{v}`: 初期化 {mid([r['init_sec'] for r in rs])} 秒、"
            f"ループ {mid([r['loop_sec'] for r in rs])} 秒（{len(rs)} 本）"
        )
        r = rs[0]
        print(
            f"  ふるいで捨てた候補: 到達しない {r['drop_none']:,.0f} / "
            f"キャッチ {r['drop_catch']:,.0f} / "
            f"トライ負け {r['drop_try']:,.0f}（候補 {r['candidates']:,.0f} のうち）。"
            f"キャッチ抜きの数が 0 で先に決めた局面 {r['zero_first']:,.0f}"
        )
    pairs = [(res[a], res[b]) for a, b in PAIRS if a in res and b in res]
    if pairs:
        d_loop = [d[1]["loop_sec"] - k[1]["loop_sec"] for k, d in pairs]
        d_init = [d[1]["init_sec"] - k[1]["init_sec"] for k, d in pairs]
        ratio = [d[1]["loop_sec"] / k[1]["loop_sec"] for k, d in pairs]
        print(f"- `drop` − `keep`（隣どうしの組 {len(pairs)} つ）: ループ {mid(d_loop)} 秒、"
              f"初期化 {mid(d_init)} 秒、ループの比 {mid(ratio, '.3f')}")  # fmt: skip

    tsv = LOGS / "timing.tsv"
    if not tsv.exists():
        return 0
    data: dict[tuple[str, str], dict[int, float]] = {}
    with tsv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            data.setdefault((row["version"], row["sample"]), {})[int(row["round"])] = float(
                row["ns_per_q"]
            )
    rounds = sorted({r for v in data.values() for r in v})
    print()
    print("## B. キャッチ抜きの数の数え方（ns/局面。中央値と範囲）")
    print()
    print("| 版 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in ("gen", "b1", "b2"):
        cells = [mid([data[(v, s)][r] for r in rounds], ".1f") for s in SAMPLES]
        print(f"| `{v}` | " + " | ".join(cells) + " |")
    print()
    print("| 差 | " + " | ".join(SAMPLES) + " |")
    print("|---|" + "---|" * len(SAMPLES))
    for v in ("b1", "b2"):
        cells = [
            mid([data[(v, s)][r] - data[("gen", s)][r] for r in rounds], ".1f") for s in SAMPLES
        ]
        print(f"| `{v}` − `gen` | " + " | ".join(cells) + " |")
    gen_u, b1_u = data[("gen", "unknown")], data[("b1", "unknown")]
    b1 = [(b1_u[r] - gen_u[r]) * N_UNKNOWN / 1e9 for r in rounds]
    b2 = [data[("b2", "unknown")][r] * N_UNKNOWN / 1e9 for r in rounds]
    stages = dict(
        ln.split("\t", 1)
        for ln in (ROOT / "results" / "33_hot_layout" / "retreat_summary.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    now = sum(float(stages[s]) for s in STAGES)
    print()
    print("## 換算（秒）")
    print()
    print(f"- B1（全探索で見分ける。増分 × 未知局面 {N_UNKNOWN:,}）: {mid(b1)}")
    print(f"- B2（全探索のあとで数え直す。b2 × 未知局面）: {mid(b2)}")
    drops = [r["loop_sec"] for v, r in res.values() if v == "drop"]
    if drops:
        d = statistics.median(drops)
        tot = [d + x for x in b1]
        print(f"- 外す版のループ（中央値 {d:.2f}）＋ B1: {mid(tot)}、"
              f"いまの4段 {now:.2f} との差 {mid([x - now for x in tot])}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
