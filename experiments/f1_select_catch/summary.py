#!/usr/bin/python3
"""実験 f1_select_catch の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/f1_select_catch/summary.py > experiments/f1_select_catch/logs/summary.txt

experiments/bitboard_gen/summary.py を4腕に広げたもの. 1局面あたりの出し方・周波数・帰属の読み方は同じ.
- 一致の検査 (logs/verify_<腕>.txt の最後の行) と静的な確かめ (logs/asm_<腕>.txt の頭)
- ベンチ (logs/bench.tsv): 1局面あたり ＝ (値 − 固定の分の中央値) ÷ (2 × 局面数) (温める周と測る周).
  order はラウンドの局面数 (blocks_index.tsv), catch / other はさらにブロックの中の割合 (split_index.tsv) で
  重みを付けて平均する. 腕どうしの差は同じ周の base との差を周ごとに取ってから, 7周の中央値と範囲
- 重なり ＝ (both − base) − (select − base) − (precheck − base). 周ごとに取ってから中央値と範囲
- 推し方 (回す前に決めた): order の cycles で 腕 − base の範囲が 0 をまたがずに下なら門番の候補.
  両方推せるときは, order の換算が大きい (負に大きい) ほうを先に記録にする候補とし, もう1つの取り分を
  both − 先の腕 で見積もる
- F1 の秒への換算 (見込みで, 効果量ではない):
  主: order の cycles の差 × F1 の局面数 ÷ 周波数 (周波数は bitboard_gen と同じ式で perf_34 / perf_branch_34 から)
  precheck と both はもう1つ: (catch の差 × キャッチ局面の数 ＋ other の差 × それ以外の局面の数) ÷ 周波数
- 束ごとの帰属 (logs/attr_<腕>_r<回>.tsv): 予測ミスの標本 (周期 211) を categories_<腕>.tsv で束ねる.
  標本は間引かれるので割合だけを使い, 1局面あたり ＝ 束の割合 × その腕のベンチの order の予測ミス (bitboard_gen と同じ)
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
ARMS = ("base", "select", "precheck", "both")
INPUTS = ("order", "random", "catch", "other")
EVS = ("cycles_u", "instructions_u", "br_inst_u", "br_misp_u")
N_F1 = 246_803_167
N_CATCH = 140_298_614
N_OTHER = N_F1 - N_CATCH  # トライ負け 7,018,985 ＋ 未知 99,485,568
GEN_BENCH_MISS_NS = (33.8, 44.8)  # gen_bench の候補 A − base (トライ負け・未知, ns/局面)


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"))


def freq_ghz() -> float:
    """bitboard_gen の summary.py と同じ式 (perf_34 の T1 の cycles の中央値 × 局面数 ÷ perf_branch_34 の base の F1 の秒)。"""
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
    """(周, 腕, 入力) → 量 → 1局面あたり。bitboard_gen と同じ。"""
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
    out = {}
    for ln in (HERE / f"categories_{arm}.tsv").read_text(encoding="utf-8").splitlines():
        if ln[:1].isdigit():
            line, bundle, _ = ln.split("\t")
            out[int(line)] = bundle
    return out


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    print("## 静的な確かめと一致の検査")
    print()
    for a in ARMS:
        head = (LOGS / f"asm_{a}.txt").read_text(encoding="utf-8").splitlines()
        print(f"- {a}: {head[1]}（{head[2]}）")
    for a in ARMS[1:]:
        p = LOGS / f"verify_{a}.txt"
        last = p.read_text(encoding="utf-8").splitlines()[-1] if p.exists() else "(無い)"
        print(f"- 一致の検査 {a}: {last}")
    print()

    rows = table(LOGS / "bench.tsv")
    arms = [a for a in ARMS if any(r["arm"] == a for r in rows)]
    ohr = table(LOGS / "bench_overhead.tsv")
    oh = {a: {e: statistics.median(float(r[e]) for r in ohr if r["arm"] == a) for e in EVS} for a in arms}
    pp = per_position(rows, oh)
    reps = sorted({r["rep"] for r in rows}, key=int)
    pct = min(float(r["min_pct"]) for r in rows)
    n_rows = {a: sum(1 for r in rows if r["arm"] == a) for a in arms}
    print(f"## ベンチ（{len(reps)} 周。多重化: 最小の比率 {pct:.2f}%。本数（腕ごと）: {n_rows}）")
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

    def diff(a: str, b: str, inp: str, e: str) -> list[float]:
        return [pp[(r, a, inp)][e] - pp[(r, b, inp)][e] for r in reps]

    print("### 腕どうしの差（同じ周の差の中央値と範囲）")
    print()
    print("| 差 | 入力 | cycles | instructions | 分岐 | 予測ミス |")
    print("|---|---|---|---|---|---|")
    pairs = [(a, "base") for a in arms if a != "base"]
    for a, b in pairs:
        for inp in INPUTS:
            d = {e: diff(a, b, inp, e) for e in EVS}
            print(
                f"| {a} − {b} | {inp} | {mid(d['cycles_u'], '+.1f')} | {mid(d['instructions_u'], '+.1f')} "
                f"| {mid(d['br_inst_u'], '+.1f')} | {mid(d['br_misp_u'], '+.2f')} |"
            )
    print()
    have_all = all(a in arms for a in ARMS)
    if have_all:
        print("### 重なり ＝ (both − base) − (select − base) − (precheck − base)（周ごとに取ってから中央値と範囲。足し算なら 0、重なれば正）")
        print()
        print("| 入力 | cycles | instructions | 分岐 | 予測ミス |")
        print("|---|---|---|---|---|")
        for inp in INPUTS:
            o = {
                e: [
                    (pp[(r, "both", inp)][e] - pp[(r, "base", inp)][e])
                    - (pp[(r, "select", inp)][e] - pp[(r, "base", inp)][e])
                    - (pp[(r, "precheck", inp)][e] - pp[(r, "base", inp)][e])
                    for r in reps
                ]
                for e in EVS
            }
            print(
                f"| {inp} | {mid(o['cycles_u'], '+.1f')} | {mid(o['instructions_u'], '+.1f')} "
                f"| {mid(o['br_inst_u'], '+.1f')} | {mid(o['br_misp_u'], '+.2f')} |"
            )
        print()
        print("### 先の腕の上に足したときの取り分（both − 先の腕。同じ周の差）")
        print()
        print("| 差 | 入力 | cycles | 予測ミス |")
        print("|---|---|---|---|")
        for first in ("select", "precheck"):
            for inp in INPUTS:
                c = diff("both", first, inp, "cycles_u")
                m = diff("both", first, inp, "br_misp_u")
                print(f"| both − {first} | {inp} | {mid(c, '+.1f')} | {mid(m, '+.2f')} |")
        print()

    f = freq_ghz()
    print(f"### F1 の秒への換算（周波数 {f:.3f} GHz。見込みで, 効果量ではない）")
    print()
    print(f"主: order の cycles の差 × {N_F1:,} ÷ 周波数。precheck を含む差はもう1つ: "
          f"(catch の差 × {N_CATCH:,} ＋ other の差 × {N_OTHER:,}) ÷ 周波数")  # fmt: skip
    print()
    conv: dict[tuple[str, str], list[float]] = {}
    cmp_pairs = list(pairs)
    if have_all:
        cmp_pairs += [("both", "select"), ("both", "precheck")]
    for a, b in cmp_pairs:
        s = [x * N_F1 / (f * 1e9) for x in diff(a, b, "order", "cycles_u")]
        conv[(a, b)] = s
        line = f"- {a} − {b}: order {mid(s, '+.2f')} 秒"
        if "precheck" in (a, b) or a == "both":
            cc, co = diff(a, b, "catch", "cycles_u"), diff(a, b, "other", "cycles_u")
            s2 = [(x * N_CATCH + y * N_OTHER) / (f * 1e9) for x, y in zip(cc, co, strict=True)]
            line += f" / catch・other {mid(s2, '+.2f')} 秒"
        print(line)
    print()

    if "precheck" in arms:
        print("### precheck の catch で浮いた分と other で払った分（cycles と ns。ns ＝ cycles ÷ 周波数）")
        print()
        for a in ("precheck", "both"):
            if a not in arms:
                continue
            ref = "base" if a == "precheck" else "select"
            if ref not in arms:
                continue
            cc, co = diff(a, ref, "catch", "cycles_u"), diff(a, ref, "other", "cycles_u")
            print(
                f"- {a} − {ref}: catch {mid(cc, '+.1f')} cycles ＝ {mid([x / f for x in cc], '+.1f')} ns / "
                f"other {mid(co, '+.1f')} cycles ＝ {mid([x / f for x in co], '+.1f')} ns"
            )
        lo, hi = GEN_BENCH_MISS_NS
        print(f"- 比べる相手: gen_bench の候補 A の外れたときの費用（トライ負け・未知）{lo:+.1f}〜{hi:+.1f} ns")
        print()

    print("### 推し方（回す前に決めた。判定の量は order の1局面あたり cycles の base との差）")
    print()
    rec = []
    for a in ("select", "precheck"):
        if a not in arms:
            print(f"- {a}: 計時していない")
            continue
        c = diff(a, "base", "order", "cycles_u")
        ok = max(c) < 0
        if ok:
            rec.append(a)
        verdict = "0 をまたがずに下 → 門番にかける候補として推す" if ok else "0 をまたぐか上 → 推さない"
        print(f"- {a} − base: 範囲 {min(c):+.1f}〜{max(c):+.1f} → {verdict}")
    if len(rec) == 2 and have_all:
        first = min(rec, key=lambda x: statistics.median(conv[(x, "base")]))
        second = "select" if first == "precheck" else "precheck"
        print(
            f"- 両方推せる: order の換算が大きいのは {first}（{statistics.median(conv[(first, 'base')]):+.2f} 秒。"
            f"{second} は {statistics.median(conv[(second, 'base')]):+.2f} 秒）→ {first} を先に記録にする候補。"
            f"{second} の取り分 ＝ both − {first}: order {mid(diff('both', first, 'order', 'cycles_u'), '+.1f')} cycles"
            f" ＝ {mid(conv[('both', first)], '+.2f')} 秒"
        )
    print()

    print("## 束ごとの帰属（予測ミスの標本の割合。3回の中央値と範囲）")
    print()
    print("1局面あたりは、割合 × その腕のベンチの order の予測ミス（7周の中央値）。標本は間引かれるので、標本の数からは出さない")
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
