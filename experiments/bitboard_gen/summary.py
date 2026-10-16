#!/usr/bin/python3
"""実験 bitboard_gen の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/bitboard_gen/summary.py > experiments/bitboard_gen/logs/summary.txt

- 一致の検査 (logs/verify_<腕>.txt の最後の行) と静的な確かめ (logs/asm_<腕>.txt の頭)
- ベンチ (logs/bench.tsv): 1局面あたり ＝ (値 − 固定の分の中央値) ÷ (2 × 局面数)
  (温める周と測る周). order はラウンドの局面数 (blocks_index.tsv), catch / other はさらに
  ブロックの中の割合 (split_index.tsv) で重みを付けて平均する. 腕どうしの差は同じ周の base との差を
  周ごとに取ってから, 7周の中央値と範囲
- 選び方 (回す前に決めた): order の cycles で bb_* − base の範囲が 0 をまたがずに下なら門番の候補.
  bb_pext − bb_nibble の範囲が 0 をまたぐなら bb_nibble
- F1 の秒への換算 ＝ cycles の差 × F1 の局面数 ÷ 周波数. 周波数は perf_branch_34 の換算と同じ式
  (perf_34 の T1 の cycles の中央値 × 局面数 ÷ perf_branch_34 の base の F1 の秒).
  見込みであって効果量ではない
- 束ごとの帰属 (logs/attr_<腕>_r<回>.tsv): 予測ミスの標本 (周期 211) を, base は perf_branch_34 の
  categories.tsv, bb_* は categories_<腕>.tsv で束ねる. 標本は間引かれたので割合だけを使い,
  1局面あたり ＝ 束の割合 × その腕のベンチの order の予測ミス (回したあとで決めた)
"""

from __future__ import annotations

import csv
import pathlib
import statistics
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
P34 = HERE.parent / "perf_34" / "logs"
P34B = HERE.parent / "perf_branch_34"
ARMS = ("base", "bb_nibble", "bb_pext")
INPUTS = ("order", "random", "catch", "other")
EVS = ("cycles_u", "instructions_u", "br_inst_u", "br_misp_u")
N_F1 = 246_803_167


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"))


def freq_ghz() -> float:
    cyc = []
    for r in ("r1", "r2", "r3"):
        for ln in (P34 / f"{r}_T1_stat_F1.csv").read_text(encoding="utf-8").splitlines():
            c = ln.split(",")
            if len(c) > 2 and c[2] == "cycles":
                cyc.append(float(c[0]))
    sec = 0.0
    for ln in (P34B / "logs" / "base_forward_summary.tsv").read_text(encoding="utf-8").splitlines():
        k, _, v = ln.partition("\t")
        if k == "F1":
            sec = float(v)
    return statistics.median(cyc) / sec / 1e9


def weights() -> tuple[dict[str, int], dict[str, tuple[int, int, int]]]:
    total = {}
    for ln in (LOGS / "blocks_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, _ = ln.split("\t")
        total[name] = int(n)
    split = {}
    for ln in (LOGS / "split_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, c, o = ln.split("\t")
        split[name] = (int(n), int(c), int(o))
    return total, split


def per_position(
    rows: list[dict[str, str]], oh: dict[str, dict[str, float]]
) -> dict[tuple[str, str, str], dict[str, float]]:
    """(周, 腕, 入力) → 量 → 1局面あたり。"""
    total, split = weights()
    acc: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        stem = r["file"][:-4]
        inp = r["input"]
        if inp == "order":
            w = float(total[stem])
        elif inp == "catch":
            w = total[stem] * split[stem][1] / split[stem][0]
        elif inp == "other":
            w = total[stem] * split[stem][2] / split[stem][0]
        else:
            w = 1.0
        key = (r["rep"], r["arm"], inp)
        for e in EVS:
            v = (float(r[e]) - oh[r["arm"]][e]) / (2 * int(r["n"]))
            acc[key][e].append(v * w)
        acc[key]["_w"].append(w)
    out = {}
    for key, d in acc.items():
        wsum = sum(d["_w"])
        out[key] = {e: sum(d[e]) / wsum for e in EVS}
    return out


def categories(arm: str) -> dict[int, str]:
    path = P34B / "categories.tsv" if arm == "base" else HERE / f"categories_{arm}.tsv"
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln[:1].isdigit():
            line, bundle, _ = ln.split("\t")
            out[int(line)] = bundle
    return out


def main() -> int:
    print("## 静的な確かめと一致の検査")
    print()
    for a in ARMS:
        head = (LOGS / f"asm_{a}.txt").read_text(encoding="utf-8").splitlines()
        print(f"- {a}: {head[1]}（{head[2]}）")
    for a in ARMS[1:]:
        last = (LOGS / f"verify_{a}.txt").read_text(encoding="utf-8").splitlines()[-1]
        print(f"- 一致の検査 {a}: {last}")
    print()

    rows = table(LOGS / "bench.tsv")
    arms = [a for a in ARMS if any(r["arm"] == a for r in rows)]
    ohr = table(LOGS / "bench_overhead.tsv")
    oh = {
        a: {e: statistics.median(float(r[e]) for r in ohr if r["arm"] == a) for e in EVS}
        for a in arms
    }
    pp = per_position(rows, oh)
    reps = sorted({r["rep"] for r in rows}, key=int)
    pct = min(float(r["min_pct"]) for r in rows)
    print(f"## ベンチ（{len(reps)} 周。多重化: 最小の比率 {pct:.2f}%）")
    print()
    print("### 1局面あたり（周の中央値と範囲）")
    print()
    print("| 腕 | 入力 | cycles | instructions | 分岐 | 予測ミス |")
    print("|---|---|---|---|---|---|")
    for a in arms:
        for inp in INPUTS:
            v = {e: [pp[(r, a, inp)][e] for r in reps] for e in EVS}
            print(
                f"| {a} | {inp} | {mid(v['cycles_u'], '.1f')} | {mid(v['instructions_u'], '.1f')} "
                f"| {mid(v['br_inst_u'], '.1f')} | {mid(v['br_misp_u'], '.2f')} |"
            )
    print()
    print("### 腕どうしの差（同じ周の差の中央値と範囲）")
    print()
    print("| 差 | 入力 | cycles | instructions | 分岐 | 予測ミス |")
    print("|---|---|---|---|---|---|")
    pairs = [(a, "base") for a in arms if a != "base"]
    if "bb_nibble" in arms and "bb_pext" in arms:
        pairs.append(("bb_pext", "bb_nibble"))
    diffs: dict[tuple[str, str, str], dict[str, list[float]]] = {}
    for a, b in pairs:
        for inp in INPUTS:
            d = {e: [pp[(r, a, inp)][e] - pp[(r, b, inp)][e] for r in reps] for e in EVS}
            diffs[(a, b, inp)] = d
            print(
                f"| {a} − {b} | {inp} | {mid(d['cycles_u'], '+.1f')} "
                f"| {mid(d['instructions_u'], '+.1f')} | {mid(d['br_inst_u'], '+.1f')} "
                f"| {mid(d['br_misp_u'], '+.2f')} |"
            )
    print()
    f = freq_ghz()
    print(
        f"### F1 の秒への換算（order の cycles の差 × {N_F1:,} ÷ {f:.3f} GHz。"
        "見込みで, 効果量ではない）"
    )
    print()
    for a, b in pairs:
        s = [x * N_F1 / (f * 1e9) for x in diffs[(a, b, "order")]["cycles_u"]]
        print(f"- {a} − {b}: {mid(s, '+.2f')} 秒")
    print()
    print("### 選び方（回す前に決めた。判定の量は order の1局面あたり cycles）")
    print()
    for a in arms[1:]:
        c = diffs[(a, "base", "order")]["cycles_u"]
        verdict = "0 をまたがずに下 → 門番の候補" if max(c) < 0 else "0 をまたぐか上 → 候補にしない"
        print(f"- {a} − base: 範囲 {min(c):+.1f}〜{max(c):+.1f} → {verdict}")
    if ("bb_pext", "bb_nibble", "order") in diffs:
        c = diffs[("bb_pext", "bb_nibble", "order")]["cycles_u"]
        if min(c) <= 0 <= max(c):
            v = "0 をまたぐ → bb_nibble"
        elif max(c) < 0:
            v = "0 をまたがずに下 (bb_pext が軽い)"
        else:
            v = "0 をまたがずに上 (bb_nibble が軽い)"
        print(f"- bb_pext − bb_nibble: 範囲 {min(c):+.1f}〜{max(c):+.1f} → {v}")
    print()

    # キャッチの先行判定をこの上に足したときに消しうる分の上限: キャッチ局面1つあたりの予測ミス
    # (catch 入力, 7周の中央値) × キャッチ局面の数 (perf_branch_34 の base の forward.tsv の
    # n_win の合計) × 15〜20 サイクル
    with (P34B / "logs" / "base_forward.tsv").open(encoding="utf-8") as fh:
        n_catch = sum(int(r["n_win"]) for r in csv.DictReader(fh, delimiter="\t"))
    print(f"### キャッチ局面で生成器が出している予測ミス（キャッチ局面 {n_catch:,}）")
    print()
    for a in arms:
        cm = statistics.median(pp[(r, a, "catch")]["br_misp_u"] for r in reps)
        cc = statistics.median(pp[(r, a, "catch")]["cycles_u"] for r in reps)
        print(
            f"- {a}: {cm:.2f} / 局面 × {n_catch:,} ＝ {cm * n_catch / 1e9:.3f}×10^9。"
            f"1回 15〜20 サイクルで {cm * n_catch * 15 / (f * 1e9):.2f}〜"
            f"{cm * n_catch * 20 / (f * 1e9):.2f} 秒（予測ミスを全部消せた場合の上限）。"
            f"キャッチ局面の cycles は {cc:.1f} / 局面 ＝ {cc * n_catch / (f * 1e9):.2f} 秒"
        )
    print()

    # 帰属: 標本の割合だけを使う. 周期 211 では標本が毎秒 25,000 の上限
    # (kernel.perf_event_max_sample_rate) に当たって間引かれた
    # (perf report --stats の THROTTLE) ので,
    # 標本 × 211 は予測ミスの数にならない. 1局面あたりは「束の割合 × その腕のベンチの order の
    # 予測ミス (7周の中央値)」で出す (回したあとで決めた)
    print("## 束ごとの帰属（予測ミスの標本の割合。3回の中央値と範囲）")
    print()
    print(
        "1局面あたりは、割合 × その腕のベンチの order の予測ミス（7周の中央値）。"
        "標本は間引かれたので、標本の数からは出さない"
    )
    print()
    for a in arms:
        cats = categories(a)
        misp_order = statistics.median(pp[(r, a, "order")]["br_misp_u"] for r in reps)
        per: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        tot = []
        for i in range(3):
            t = 0
            for row in table(LOGS / f"attr_{a}_r{i + 1}.tsv"):
                n = int(row["samples"])
                t += n
                if row["where"] != "animal_shogi.so":
                    b = "段の外"
                elif row["inline"] == "benchFwd" or row["func"] == "benchFwd":
                    b = "ベンチの外枠 (benchFwd)"
                else:
                    b = cats.get(int(row["line"]), "対応表に無い行")
                per[b][i] += n
            tot.append(t)
        samples = ", ".join(f"{x:,}" for x in tot)
        print(f"### {a}（標本 {samples}。order の予測ミス {misp_order:.2f} / 局面）")
        print()
        print("| 束 | 割合 | 予測ミス / 局面 |")
        print("|---|---|---|")
        for b in sorted(per, key=lambda k: -statistics.median(per[k])):
            sh = [per[b][i] / tot[i] for i in range(3)]
            pm = [x * misp_order for x in sh]
            print(f"| {b} | {mid(sh, '.1%')} | {mid(pm, '.2f')} |")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
