#!/usr/bin/python3
"""実験 rank_fast の段2の集計 (記録試行ではない)。

logs/ の生ログから logs/summary_stage2.txt を作る。

    python3 summary2.py            # 標準出力へ
    python3 summary2.py --write    # logs/summary_stage2.txt に書く

式は README の「段2の式」の節。手で書いた数は使わない。
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
BLOCKS = HERE.parent / "perf_34" / "logs" / "blocks_index.tsv"
EVS = ("cycles_u", "instructions_u", "br_inst_u", "br_misp_u")
RB_EVS = ("cycles_u", "instructions_u", "l1_miss_u", "l2_hit_u")
GHZ = 3.408  # 換算の周波数 (bitboard_gen・f1_select_catch と同じ)
N_F1 = 246_803_167  # F1 で展開した局面 (#38 本走の forward.tsv の n_in の和)
FACTORS = (0.5, 0.75)  # perf_38: サイクルの換算は 0.5〜0.75 を掛けて読む


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def n_front() -> int:
    """U_loop で展開した局面の延べ数 (段1の完走のログ。6本で同じ)。"""
    vals = set()
    for p in sorted(LOGS.glob("r?_l?_main.log")):
        m = re.search(r"展開した局面 \(perf_34\)：(\d+)", p.read_text(encoding="utf-8"))
        if m:
            vals.add(int(m.group(1)))
    if len(vals) != 1:
        raise SystemExit(f"段1の完走の展開した局面が1つに決まらない: {vals}")
    return vals.pop()


def weights() -> dict[str, int]:
    out = {}
    for ln in BLOCKS.read_text(encoding="utf-8").splitlines():
        name, n, _ = ln.split("\t")
        out[name] = int(n)
    return out


def per_position() -> tuple[list[str], dict[tuple[str, str, str], dict[str, float]], dict[str, set[str]]]:
    """(周, 腕, ベンチ) → 量 → 1局面あたり。固定の分を引いて 2n (温めの周と測る周) で割り, ラウンド (段) の局面数で重みを付ける。"""
    rows = table(LOGS / "bench2.tsv")
    oh_rows = table(LOGS / "bench2_overhead.tsv")
    oh: dict[tuple[str, str], dict[str, float]] = {}
    for a in {r["arm"] for r in oh_rows}:
        for bn in ("fwd", "unmove"):
            sel = [r for r in oh_rows if r["arm"] == a and r["bench"] == bn]
            oh[(a, bn)] = {e: statistics.median(float(r[e]) for r in sel) for e in EVS}
    w = weights()
    acc: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sums: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        key = (r["rep"], r["arm"], r["bench"])
        wt = float(w[r["file"][:-4]])
        for e in EVS:
            acc[key][e] += (float(r[e]) - oh[(r["arm"], r["bench"])][e]) / (2 * int(r["n"])) * wt
        acc[key]["_w"] += wt
        acc[key]["_outs"] += float(r["outs"]) * wt
        sums[f"{r['bench']}/{r['file']}"].add(r["sum"])
    out = {}
    for key, d in acc.items():
        out[key] = {e: d[e] / d["_w"] for e in (*EVS, "_outs")}
    arms = sorted({r["arm"] for r in rows}, key=lambda a: (a != "base", a))
    return arms, out, sums


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    out: list[str] = ["# rank_fast 段2の集計（summary2.py が生ログから作る。手で書かない）", ""]
    w = out.append
    w("## 一致の検査")
    w("")
    for p in sorted(LOGS.glob("verify_*.txt")):
        lines = p.read_text(encoding="utf-8").splitlines()
        last = [ln for ln in lines if ln.startswith("局面 ")]
        w(f"- {p.stem[7:]}: {last[-1] if last else '（最後の行が無い）'}")
    w("")
    arms, pp, sums = per_position()
    reps = sorted({k[0] for k in pp})
    nf = n_front()
    w(f"## 文脈の中のベンチ（order。1局面あたり。{len(reps)} 周の中央値と範囲）")
    w("")
    w("- 番号の和の種類の数（ファイルごと。周と腕をまたいで 1 なら番号が同じ）: 最大 "
      f"{max(len(v) for v in sums.values())}")
    mins = [float(r["min_pct"]) for r in table(LOGS / "bench2.tsv")]
    w(f"- 数えた比率の最小 {min(mins):.2f}%")
    w("")
    w("| 腕 | ベンチ | cycles | instructions | 分岐 | 予測ミス | 後続（候補） |")
    w("|---|---|---|---|---|---|---|")
    for a in arms:
        for bn in ("fwd", "unmove"):
            v = {e: [pp[(r, a, bn)][e] for r in reps] for e in (*EVS, "_outs")}
            w(f"| {a} | {bn} | {mid(v['cycles_u'], '.1f')} | {mid(v['instructions_u'], '.1f')} | "
              f"{mid(v['br_inst_u'], '.1f')} | {mid(v['br_misp_u'], '.2f')} | {statistics.median(v['_outs']):.4f} |")
    w("")
    w("### base との差（同じ周の差を周ごとに取ってから中央値と範囲）")
    w("")
    w("| 腕 | ベンチ | cycles | instructions | 分岐 | 予測ミス |")
    w("|---|---|---|---|---|---|")
    diffs: dict[tuple[str, str], dict[str, list[float]]] = {}
    for a in arms[1:]:
        for bn in ("fwd", "unmove"):
            d = {e: [pp[(r, a, bn)][e] - pp[(r, "base", bn)][e] for r in reps] for e in EVS}
            diffs[(a, bn)] = d
            w(f"| {a} | {bn} | {mid(d['cycles_u'], '+.1f')} | {mid(d['instructions_u'], '+.1f')} | "
              f"{mid(d['br_inst_u'], '+.1f')} | {mid(d['br_misp_u'], '+.2f')} |")
    w("")
    w(f"### 換算（F1: fwd の cycles の差 × {N_F1:,} ÷ {GHZ} GHz、U_loop: unmove の cycles の差 × {nf:,} ÷ {GHZ} GHz）")
    w("")
    w("| 腕 | F1（掛ける前） | U_loop（掛ける前） | 合計（掛ける前） | 合計 × 0.5 | 合計 × 0.75 |")
    w("|---|---|---|---|---|---|")
    conv: dict[str, list[float]] = {}
    for a in arms[1:]:
        f1 = [x * N_F1 / (GHZ * 1e9) for x in diffs[(a, "fwd")]["cycles_u"]]
        ul = [x * nf / (GHZ * 1e9) for x in diffs[(a, "unmove")]["cycles_u"]]
        tot = [x + y for x, y in zip(f1, ul, strict=True)]
        conv[a] = tot
        w(f"| {a} | {mid(f1, '+.2f')} 秒 | {mid(ul, '+.2f')} 秒 | {mid(tot, '+.2f')} 秒 | "
          f"{statistics.median(tot) * FACTORS[0]:+.2f} 秒 | {statistics.median(tot) * FACTORS[1]:+.2f} 秒 |")
    w("")
    w("### 推し方（README の「推し方」。判定の量は fwd と unmove の order の cycles の base との差）")
    w("")
    ok = []
    for a in arms[1:]:
        below = [bn for bn in ("fwd", "unmove") if max(diffs[(a, bn)]["cycles_u"]) < 0]
        above = [bn for bn in ("fwd", "unmove") if min(diffs[(a, bn)]["cycles_u"]) > 0]
        verdict = "推す" if below else "推さない"
        if below:
            ok.append(a)
        w(f"- {a}: 0 をまたがずに下 {below or 'なし'}、0 をまたがずに上 {above or 'なし'} → **{verdict}**")
    if len(ok) >= 2:
        best = min(ok, key=lambda a: statistics.median(conv[a]))
        w(f"- 2本とも推せる: 換算の合計が大きい（負に大きい）のは **{best}**")
    w("")
    rb = table(LOGS / "rankbench_stage2.tsv")
    by = {(r["rep"], r["arm"], r["input"], r["mode"]): r for r in rb}
    rreps = sorted({r["rep"] for r in rb})
    w(f"## rankOf だけのベンチ（1呼び出しあたり。回し方 − none を周ごとに取ってから {len(rreps)} 周の中央値と範囲）")
    w("")
    rsums: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rb:
        if r["mode"] in ("thr", "chain"):
            rsums[(r["input"], r["arm"])].add(r["sum"])
    w("- 番号の和の種類の数（thr と chain を合わせて, 入力 × 腕ごと. 1 なら同じ）: "
      + ", ".join(f"{k[0]}/{k[1]} {len(v)}" for k, v in sorted(rsums.items())))
    w(f"- 数えた比率の最小 {min(float(r['min_pct']) for r in rb):.2f}%")
    w("")
    w("| 腕 | 入力 | 回し方 | cycles | instructions | L1 の外れ | base との差（cycles） |")
    w("|---|---|---|---|---|---|---|")
    for inp in ("fwd", "unmove"):
        for m in ("thr", "chain", "small"):
            for a in arms:
                v: dict[str, list[float]] = defaultdict(list)
                dd = []
                for rep in rreps:
                    r, z = by[(rep, a, inp, m)], by[(rep, a, inp, "none")]
                    n = int(r["calls"])
                    for e in RB_EVS:
                        v[e].append((int(r[e]) - int(z[e])) / n)
                    rb0, zb = by[(rep, "base", inp, m)], by[(rep, "base", inp, "none")]
                    dd.append(v["cycles_u"][-1] - (int(rb0["cycles_u"]) - int(zb["cycles_u"])) / int(rb0["calls"]))
                diff = "-" if a == "base" else mid(dd, "+.1f")
                w(f"| {a} | {inp} | {m} | {mid(v['cycles_u'], '.1f')} | {mid(v['instructions_u'], '.1f')} | "
                  f"{mid(v['l1_miss_u'], '.3f')} | {diff} |")
    text = "\n".join(out) + "\n"
    if "--write" in sys.argv:
        (LOGS / "summary_stage2.txt").write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
