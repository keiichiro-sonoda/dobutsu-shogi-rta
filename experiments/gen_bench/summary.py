#!/usr/bin/python3
"""計時の生ログ (logs/timing.tsv) から表を作る (実験 gen_bench。記録試行ではない)。

    python3 experiments/gen_bench/summary.py

ns/局面 は各周の値の中央値と範囲。版どうしの差は, 同じ周の base との差を周ごとに取ってから
中央値と範囲を出す (周のあいだの揺れを打ち消すため)。
本走への換算は「種類ごとの差 × 本番の件数」。F1 は3種類とも、P2 は未知だけを通る。
A (キャッチの先行判定) は F1 の経路にだけ入れる想定なので, P2 には B のぶんだけを数える。
⚠️ 生成器だけの差で, F1 の発見済み表への挿入や P2 の索引引きとの重なりは入らない。
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys

LOGS = pathlib.Path(__file__).resolve().parent / "logs"
VARIANTS = ("base", "B", "A", "AB")
KINDS = ("catch", "try", "unknown", "mixed")
KIND_JA = {"catch": "キャッチ", "try": "トライ負け", "unknown": "未知", "mixed": "混ぜた列"}
# 本番の件数 (#25 本走. logs/sample.txt の「全体」と同じはず)
F1_COUNT = {"catch": 140_298_614, "try": 7_018_985, "unknown": 99_485_568}
P2_COUNT = {"catch": 0, "try": 0, "unknown": 99_485_568}
# P2 に入るのは B のぶんだけ (A は F1 の経路にだけ入れる想定)
P2_AS = {"base": "base", "B": "B", "A": "base", "AB": "B"}


def load() -> dict[tuple[str, str, str], dict[int, float]]:
    """(何を, 版, 種類) → {周: ns/局面}"""
    out: dict[tuple[str, str, str], dict[int, float]] = {}
    with (LOGS / "timing.tsv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rnd, variant = row["label"].split("_", 1)
            key = (row["what"], variant, row["kind"])
            out.setdefault(key, {})[int(rnd[1:])] = float(row["ns_per"])
    return out


def span(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}（{min(values):.1f}〜{max(values):.1f}）"


def paired(data: dict[int, float], base: dict[int, float]) -> list[float]:
    return [data[r] - base[r] for r in sorted(data) if r in base]


def main() -> int:
    t = load()
    rounds = sorted({r for v in t.values() for r in v})
    print(f"周: {len(rounds)}（{rounds[0]}〜{rounds[-1]}）\n")
    print("### 生成器の ns/局面（中央値と範囲）\n")
    print("| 版 | " + " | ".join(KIND_JA[k] for k in KINDS) + " |")
    print("|---|" + "---|" * len(KINDS))
    for v in VARIANTS:
        if ("gen", v, "catch") not in t:
            continue
        cells = [span(list(t[("gen", v, k)].values())) for k in KINDS]
        print(f"| `{v}` | " + " | ".join(cells) + " |")
    print("\n### base との差（ns/局面。同じ周どうしの差の中央値と範囲）\n")
    print("| 版 | " + " | ".join(KIND_JA[k] for k in KINDS) + " |")
    print("|---|" + "---|" * len(KINDS))
    diff: dict[tuple[str, str], float] = {}
    for v in VARIANTS[1:]:
        if ("gen", v, "catch") not in t:
            continue
        cells = []
        for k in KINDS:
            d = paired(t[("gen", v, k)], t[("gen", "base", k)])
            diff[(v, k)] = statistics.median(d)
            cells.append(span(d))
        print(f"| `{v}` − `base` | " + " | ".join(cells) + " |")
    print("\n### 種類ごとの時間を件数で重み付けした値と、混ぜた列の比（ns/局面。中央値）\n")
    total = sum(F1_COUNT.values())
    for v in VARIANTS:
        if ("gen", v, "catch") not in t:
            continue
        med = {k: statistics.median(t[("gen", v, k)].values()) for k in KINDS}
        weighted = sum(med[k] * F1_COUNT[k] for k in F1_COUNT) / total
        print(f"- `{v}`: 重み付け {weighted:.1f} / 混ぜた列 {med['mixed']:.1f}")
    if ("inv", "base", "mixed") in t:
        print("\n### invBoard 単体（混ぜた列。ns/回）\n")
        for v in ("base", "B"):
            if ("inv", v, "mixed") in t:
                print(f"- `{v}`: {span(list(t[('inv', v, 'mixed')].values()))}")
        d = paired(t[("inv", "B", "mixed")], t[("inv", "base", "mixed")])
        print(f"- `B` − `base`: {span(d)}")
    print("\n### 本走への換算（秒。種類ごとの差の中央値 × 本番の件数）\n")
    print("| 版 | F1 | P2 | 計 |")
    print("|---|---|---|---|")
    for v in VARIANTS[1:]:
        if (v, "catch") not in diff:
            continue
        f1 = sum(diff[(v, k)] * n for k, n in F1_COUNT.items()) / 1e9
        pv = P2_AS[v]
        p2 = sum(diff[(pv, k)] * n for k, n in P2_COUNT.items()) / 1e9 if pv != "base" else 0.0
        print(f"| `{v}` | {f1:+.2f} | {p2:+.2f} | {f1 + p2:+.2f} |")
    if ("gen", "AB", "catch") in t and ("gen", "B", "catch") in t:
        print("\n### A を B の上に重ねたとき（`AB` − `B`。ns/局面と F1 の秒）\n")
        cells, f1 = [], 0.0
        for k in KINDS:
            d = paired(t[("gen", "AB", k)], t[("gen", "B", k)])
            cells.append(f"{KIND_JA[k]} {span(d)}")
            f1 += statistics.median(d) * F1_COUNT.get(k, 0)
        print("- " + " / ".join(cells))
        print(f"- F1 の換算: {f1 / 1e9:+.2f} 秒（P2 には入れない想定なので 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
