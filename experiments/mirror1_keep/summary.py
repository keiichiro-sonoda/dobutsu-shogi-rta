#!/usr/bin/python3
"""実験 mirror1_keep のベンチの集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/mirror1_keep/summary.py > experiments/mirror1_keep/logs/summary.txt

experiments/unmove_gen/summary.py の写し (束ごとの帰属の部分は除いた)。
- 一致の検査 (logs/verify_<腕>.txt の最後の2行), 完走の答え合わせ (logs/full_<腕>_answer.txt の最後の行と,
  主ログの「前任の候補」の行)
- ベンチ (logs/bench.tsv): 1局面あたり ＝ (値 − 固定の分の中央値) ÷ (2 × 局面数)
  (温める周と測る周). order は段の局面数 (blocks_index.tsv) で重みを付けて平均する.
  腕どうしの差は同じ周の差を周ごとに取ってから, 7周の中央値と範囲.
  **並べ直しの費用 ＝ mirror1_keep − mirror1** (ベンチは局面を処理する順が腕で同じなので, 並びの効果は入らない)
- 戻した数 (logs/counts.tsv): 式で出した値を, 同じ重みで1局面あたりにする
- U_loop の秒への換算 ＝ cycles の差 × U_loop で展開した局面数 ÷ 周波数 (unmove_gen と同じ式).
  見込みであって効果量ではない
"""

from __future__ import annotations

import csv
import pathlib
import re
import statistics
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
P34 = HERE.parent / "perf_34" / "logs"
P34B = HERE.parent / "perf_branch_34" / "logs"
ARMS = ("base", "mirror1", "mirror1_keep")
INPUTS = ("order", "random")
EVS = ("cycles_u", "instructions_u", "br_inst_u", "br_misp_u")
N_ULOOP = 103_821_853


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"))


def freq_ghz() -> float:
    cyc = []
    for r in ("r1", "r2", "r3"):
        for ln in (P34 / f"{r}_T1_stat_U_loop.csv").read_text(encoding="utf-8").splitlines():
            c = ln.split(",")
            if len(c) > 2 and c[2] == "cycles":
                cyc.append(float(c[0]))
    sec = 0.0
    for ln in (P34B / "base_retreat_summary.tsv").read_text(encoding="utf-8").splitlines():
        k, _, v = ln.partition("\t")
        if k == "U_loop":
            sec = float(v)
    return statistics.median(cyc) / sec / 1e9


def weights() -> dict[str, tuple[int, int]]:
    """u_<段> → (段の局面数, ブロックの局面数)。"""
    out = {}
    for ln in (LOGS / "blocks_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, b = ln.split("\t")
        if name.startswith("u_"):
            out[name] = (int(n), int(b))
    return out


def per_position(
    rows: list[dict[str, str]], oh: dict[str, dict[str, float]]
) -> dict[tuple[str, str, str], dict[str, float]]:
    """(周, 腕, 入力) → 量 → 1局面あたり。"""
    total = weights()
    acc: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        stem = r["file"][:-4]
        w = float(total[stem][0]) if r["input"] == "order" else 1.0
        key = (r["rep"], r["arm"], r["input"])
        for e in EVS:
            v = (float(r[e]) - oh[r["arm"]][e]) / (2 * int(r["n"]))
            acc[key][e].append(v * w)
        acc[key]["cand"].append(float(r["cand"]) * w)
        acc[key]["_w"].append(w)
    out = {}
    for key, d in acc.items():
        wsum = sum(d["_w"])
        out[key] = {e: sum(d[e]) / wsum for e in (*EVS, "cand")}
    return out


def static_and_answers() -> None:
    print("## 静的な確かめ・一致の検査・完走の答え合わせ")
    print()
    for a in ARMS[1:]:
        p = LOGS / f"verify_{a}.txt"
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines()[-2:]:
                print(f"- 一致の検査 {a}: {ln}")
    for a in ARMS[1:]:
        p = LOGS / f"full_{a}_answer.txt"
        if not p.exists():
            continue
        last = p.read_text(encoding="utf-8").splitlines()[-1]
        main = (LOGS / f"full_{a}_main.log").read_text(encoding="utf-8")
        cand = re.findall(r"前任の候補[：:]\s*([0-9,]+)", main)
        oracle = next(
            ln
            for ln in (LOGS / f"full_{a}_oracle.txt").read_text(encoding="utf-8").splitlines()
            if "PASS" in ln or "FAIL" in ln
        )
        print(f"- 完走 {a}: {last} / オラクル: {oracle.strip()} / 前任の候補 {cand[-1] if cand else '?'}")
    print()


def counts() -> dict[tuple[str, str], float]:
    """(入力, 列) → 1局面あたり (order は段の局面数で重み)。"""
    p = LOGS / "counts.tsv"
    if not p.exists():
        return {}
    total = weights()
    acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in table(p):
        n = int(r["n"])
        w = total[r["file"][:-4]][0] / n if r["input"] == "order" else 1.0 / n
        for c in ("cand_base", "cand_mirror1", "raw_both", "raw_one", "sym_q"):
            acc[(r["input"], c)][0] += int(r[c]) * w
        acc[(r["input"], "_")][1] += n * w
    return {k: v[0] / acc[(k[0], "_")][1] for k, v in acc.items() if k[1] != "_"}


def main() -> int:
    static_and_answers()
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
    sums: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        sums[(r["input"], r["file"])].add(r["sum"])
    same_sum = all(len(v) == 1 for v in sums.values())
    print(f"## ベンチ（{len(reps)} 周。多重化: 最小の比率 {pct:.2f}%）")
    print()
    print(f"- 番号の和（候補の番号の総和。多重集合が同じなら同じ）: "
          f"{'全ファイル・全周・全腕で同じ' if same_sum else '腕か周で違うファイルがある'}")  # fmt: skip
    print()
    print("### 1局面あたり（周の中央値と範囲）")
    print()
    print("| 腕 | 入力 | cycles | instructions | 分岐 | 予測ミス | 候補 |")
    print("|---|---|---|---|---|---|---|")
    for a in arms:
        for inp in INPUTS:
            v = {e: [pp[(r, a, inp)][e] for r in reps] for e in (*EVS, "cand")}
            print(
                f"| {a} | {inp} | {mid(v['cycles_u'], '.1f')} | {mid(v['instructions_u'], '.1f')} "
                f"| {mid(v['br_inst_u'], '.1f')} | {mid(v['br_misp_u'], '.2f')} "
                f"| {statistics.median(v['cand']):.4f} |"
            )
    print()
    cn = counts()
    if cn:
        print("### 戻した数（正規形でないとして捨てる前。式で出した値。1局面あたり）")
        print()
        print("| 入力 | 候補（base / mirror1） | 戻した数 base | 戻した数 mirror1・mirror1_keep | q が左右対称な割合 |")
        print("|---|---|---|---|---|")
        for inp in INPUTS:
            print(
                f"| {inp} | {cn[(inp, 'cand_base')]:.4f} / {cn[(inp, 'cand_mirror1')]:.4f} "
                f"| {cn[(inp, 'raw_both')]:.4f} | {cn[(inp, 'raw_one')]:.4f} "
                f"| {cn[(inp, 'sym_q')]:.2%} |"
            )
        print()
    print("### 腕どうしの差（同じ周の差の中央値と範囲）")
    print()
    print("| 差 | 入力 | cycles | instructions | 分岐 | 予測ミス |")
    print("|---|---|---|---|---|---|")
    pairs = [(a, "base") for a in arms if a != "base"]
    if "mirror1" in arms and "mirror1_keep" in arms:
        pairs.append(("mirror1_keep", "mirror1"))
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
    print("### 比（腕 ÷ base。同じ周の比の中央値）")
    print()
    for a in arms[1:]:
        for e in EVS:
            ratio = [pp[(r, a, "order")][e] / pp[(r, "base", "order")][e] for r in reps]
            print(f"- {a} order {e}: {statistics.median(ratio):.3f}")
    print()
    f = freq_ghz()
    print(
        f"### U_loop の秒への換算（order の cycles の差 × {N_ULOOP:,} ÷ {f:.3f} GHz。"
        "見込みで, 効果量ではない）"
    )
    print()
    for a, b in pairs:
        s = [x * N_ULOOP / (f * 1e9) for x in diffs[(a, b, "order")]["cycles_u"]]
        print(f"- {a} − {b}: {mid(s, '+.2f')} 秒")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
