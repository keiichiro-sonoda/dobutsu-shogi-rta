#!/usr/bin/python3
"""実験 rank_fast の段1の集計 (記録試行ではない)。

logs/ の生ログから logs/summary_stage1.txt を作る。

    python3 summary1.py            # 標準出力へ
    python3 summary1.py --write    # logs/summary_stage1.txt に書く

式は README の「段1の式」の節。手で書いた数は使わない。
"""

from __future__ import annotations

import csv
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
LOGS = HERE / "logs"
# 3回 × 2種類 (l1: cycles と L1 の外れ, l2: cycles と L2 で当たったロード). cycles は6本とも, ロードは種類の3本
RUNS = ("r1_l1", "r1_l2", "r2_l2", "r2_l1", "r3_l1", "r3_l2")
STAGES = ("F1", "U_loop", "U_draw")
# run_one.sh の周期 (3区間で同じ)
CYC = "cycles:pp"
L1 = "mem_load_uops_retired.l1_miss:pp"
L2H = "mem_load_uops_retired.l2_hit:pp"
PERIOD = {
    "F1": {CYC: 2000003, L1: 20011, L2H: 20011},
    "U_loop": {CYC: 2000003, L1: 20011, L2H: 20011},
    "U_draw": {CYC: 2000003, L1: 20011, L2H: 20011},
}

# rankOf の中の区分 (一番内側の関数, 行) → 区分.
# 行番号は impl/38_precheck/animal_shogi.c のもの (README の表と同じ)
CATS = [
    "ライオンのマスと g_rank_lion",
    "反転と詰め",
    "g_rank_pair",
    "g_rank_half",
    "組の表 (split・rmul・hand)",
    "掛けて足す",
    "rankOf: ほか",
]
CAT_OF: dict[tuple[str, int], str] = {}
for ln in (382, 383, 384, 385, 386):
    CAT_OF[("rankFindKoma", ln)] = CATS[0]
for ln in (402, 403):
    CAT_OF[("rankOf", ln)] = CATS[0]
for ln in (405, 406, 407):
    CAT_OF[("rankOf", ln)] = CATS[1]
for ln in (389, 390, 391, 392):
    CAT_OF[("rankSqueeze", ln)] = CATS[1]
for ln in (394, 395, 396):
    CAT_OF[("rankHalf", ln)] = CATS[2]
for ln in (408, 409, 410, 411):
    CAT_OF[("rankOf", ln)] = CATS[3]
for ln in (412, 414):
    CAT_OF[("rankOf", ln)] = CATS[4]
for ln in (413, 415, 416):
    CAT_OF[("rankOf", ln)] = CATS[5]
TABLES = (
    "g_rank_lion", "g_rank_code", "g_rank_pair", "g_rank_half",
    "g_rank_split", "g_rank_rmul", "g_rank_hand",
)
Row = tuple[str, str, str, int, str, int]


def med(xs: list[float]) -> str:
    return f"{statistics.median(xs):.1f}（{min(xs):.1f}〜{max(xs):.1f}）"


def med3(xs: list[float]) -> str:
    return f"{statistics.median(xs):.3f}（{min(xs):.3f}〜{max(xs):.3f}）"


def pct(xs: list[float]) -> str:
    return f"{100 * statistics.median(xs):.1f}%（{100 * min(xs):.1f}%〜{100 * max(xs):.1f}%）"


def kv(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        k, _, v = ln.partition("\t")
        out[k] = v
    return out


def record(label: str, stage: str) -> tuple[Counter[str], list[Row]]:
    """(イベントごとの標本の数, 行の並び (event, where, chain, line, table, samples))。"""
    total: Counter[str] = Counter()
    rows: list[Row] = []
    for ln in (LOGS / f"{label}_record_{stage}.tsv").read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if ln.startswith("# samples"):
            total[p[1]] = int(p[2])
        elif ln.startswith("event\t"):
            continue
        else:
            rows.append((p[0], p[1], p[2], int(p[3]) if p[3] != "-" else -1, p[4], int(p[5])))
    return total, rows


def in_rank(chain: str) -> bool:
    return "rankOf" in chain.split(">")


def cat_of(chain: str, line: int) -> str:
    inner = chain.split(">")[-1]
    return CAT_OF.get((inner, line), CATS[6])


def counts(label: str) -> dict[str, dict[str, float]]:
    """区間ごとの秒・局面・呼び出しの数。"""
    fs = kv(LOGS / f"{label}_forward_summary.tsv")
    rs = kv(LOGS / f"{label}_retreat_summary.tsv")
    with (LOGS / f"{label}_forward.tsv").open(encoding="utf-8") as f:
        fw = list(csv.DictReader(f, delimiter="\t"))
    main = (LOGS / f"{label}_main.log").read_text(encoding="utf-8")
    cand = int(re.search(r"前任の候補：(\d+)", main).group(1))  # type: ignore[union-attr]
    front = int(re.search(r"展開した局面 \(perf_34\)：(\d+)", main).group(1))  # type: ignore[union-attr]
    uk = int(re.search(r"総未知盤面数：(\d+)", main).group(1))  # type: ignore[union-attr]
    return {
        "F1": {"sec": float(fs["F1"]), "pos": sum(int(r["n_in"]) for r in fw),
               "calls": sum(int(r["n_new_pre"]) for r in fw)},
        "U_loop": {"sec": float(rs["U_loop"]), "pos": front, "calls": cand},
        "U_draw": {"sec": float(rs["U_draw"]), "pos": uk, "calls": uk},
    }


def stage1(out: list[str]) -> dict[str, dict[str, list[float]]]:
    w = out.append
    w("## 完走 6 本の検査")
    w("")
    con = (LOGS / "console_stage1.log").read_text(encoding="utf-8")
    began = len(re.findall(r"^=== 開始 r\d_l\d \(", con, re.M))
    done = len(re.findall(r"^=== 完了 r\d_l\d ", con, re.M))
    w(f"- 開始 {began} 本 / 完了 {done} 本")
    for lb in RUNS:
        ans = (LOGS / f"{lb}_answer.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
        w(f"- {lb}: {ans}")
    w("")
    res: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for st in STAGES:
        w(f"## {st}")
        w("")
        per = PERIOD[st]
        cat_rows: dict[str, list[float]] = defaultdict(list)
        tbl_l1: dict[str, list[float]] = defaultdict(list)
        tbl_l2h: dict[str, list[float]] = defaultdict(list)
        info = []
        for lb in RUNS:
            c = counts(lb)[st]
            total, rows = record(lb, st)
            stats = (LOGS / f"{lb}_record_stats_{st}.txt").read_text(encoding="utf-8")
            thr = re.search(r"THROTTLE events:\s+(\d+)", stats)
            lost = re.findall(r"LOST_SAMPLES events:\s+(\d+)", stats)
            cyc_samples = total[CYC]
            cyc_total = cyc_samples * per[CYC]
            rank_cyc = sum(n for ev, _wh, ch, _, _, n in rows if ev == CYC and in_rank(ch))
            share = rank_cyc / cyc_samples
            res[st]["share"].append(share)
            res[st]["sec"].append(share * c["sec"])
            res[st]["stage_sec"].append(c["sec"])
            res[st]["cyc_call"].append(share * cyc_total / c["calls"])
            res[st]["cyc_pos"].append(share * cyc_total / c["pos"])
            res[st]["ghz"].append(cyc_total / c["sec"] / 1e9)
            res[st]["calls"].append(c["calls"])
            res[st]["pos"].append(c["pos"])
            ghz = cyc_total / c["sec"] / 1e9
            info.append(
                f"{lb}: cycles の標本 {cyc_samples}（× 周期 ÷ 区間の秒 ＝ {ghz:.3f} GHz）、"
                f"L1 の外れ {total[L1]}、L2 で当たり {total[L2H]}、"
                f"THROTTLE {thr.group(1) if thr else 0}、LOST_SAMPLES {lost[0] if lost else 0}"
                "（perf report --stats に行が無いものは 0）"
            )
            cats: Counter[str] = Counter()
            for ev, _wh, ch, ln, _, n in rows:
                if ev == CYC and in_rank(ch):
                    cats[cat_of(ch, ln)] += n
            for k in CATS:
                cat_rows[k].append(cats[k] / cyc_samples * cyc_total / c["calls"])
            for ev, dst in ((L1, tbl_l1), (L2H, tbl_l2h)):
                if ev not in total:
                    continue
                tb: Counter[str] = Counter()
                for e, _wh, ch, _, t, n in rows:
                    if e == ev and in_rank(ch):
                        tb[t if t in TABLES else "ほか"] += n
                for k in (*TABLES, "ほか"):
                    dst[k].append(tb[k] * per[ev] / c["calls"])
                res[st][f"{ev}_call"].append(sum(tb.values()) * per[ev] / c["calls"])
        for s in info:
            w(f"- {s}")
        npos, ncall = int(res[st]["pos"][0]), int(res[st]["calls"][0])
        w(f"- 区間の秒 {med(res[st]['stage_sec'])}、局面 {npos:,}、"
          f"rankOf の呼び出し {ncall:,}（{ncall / npos:.3f} / 局面）")
        w("")
        w("| | 中央値（範囲）。cycles は6本、ロードは種類ごとの3本 |")
        w("|---|---|")
        w(f"| rankOf の標本の割合 | {pct(res[st]['share'])} |")
        w(f"| rankOf の秒（割合 × 区間の秒） | {med3(res[st]['sec'])} |")
        w(f"| rankOf の cycles / 呼び出し | {med(res[st]['cyc_call'])} |")
        w(f"| rankOf の cycles / 局面 | {med(res[st]['cyc_pos'])} |")
        w(f"| rankOf の中の L1 の外れ / 呼び出し | {med3(res[st][f'{L1}_call'])} |")
        w(f"| rankOf の中の L2 で当たったロード / 呼び出し | {med3(res[st][f'{L2H}_call'])} |")
        w("")
        w("rankOf の中の区分（cycles / 呼び出し。"
          "区分の標本 ÷ 区間の cycles の標本 × 区間の cycles ÷ 呼び出し）:")
        w("")
        w("| 区分 | cycles / 呼び出し | rankOf の中の割合 |")
        w("|---|---|---|")
        for k in CATS:
            part = [a / b for a, b in zip(cat_rows[k], res[st]["cyc_call"], strict=True)]
            w(f"| {k} | {med(cat_rows[k])} | {pct(part)} |")
        w("")
        w("表ごとの L1 の外れと L2 で当たったロード（rankOf の中の標本。/ 呼び出し）:")
        w("")
        w("| 表 | L1 の外れ | L2 で当たり |")
        w("|---|---|---|")
        for k in (*TABLES, "ほか"):
            w(f"| {k} | {med3(tbl_l1[k])} | {med3(tbl_l2h[k])} |")
        w("")
    tot = [sum(res[s]["sec"][i] for s in STAGES) for i in range(len(RUNS))]
    w(f"- **rankOf の秒の合計（F1 ＋ U_loop ＋ U_draw）: {med3(tot)}**（止める条件 3 は 2 秒未満）")
    w("")
    res["total"]["sec"] = tot
    return res


def rankbench(out: list[str], real: dict[str, dict[str, list[float]]]) -> None:
    w = out.append
    w("## rankOf だけのベンチ（1呼び出しあたり。"
      "回し方 − none を周ごとに取ってから 7 周の中央値と範囲）")
    w("")
    with (LOGS / "rankbench_stage1.tsv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    sums: dict[tuple[str, str], set[str]] = {(r["input"], r["mode"]): set() for r in rows}
    for r in rows:
        sums[(r["input"], r["mode"])].add(r["sum"])
    w(f"- 本数 {len(rows)}、数えた比率の最小 {min(float(r['min_pct']) for r in rows):.2f}%")
    w("- 検算の和の種類の数（周をまたいで 1 なら同じ）: "
      + ", ".join(f"{k[0]}/{k[1]} {len(v)}" for k, v in sorted(sums.items())))
    by = {(r["rep"], r["input"], r["mode"]): r for r in rows}
    for inp, st in (("fwd", "F1"), ("unmove", "U_loop")):
        w("")
        w(f"### {inp}（列の長さ {rows[[r['input'] for r in rows].index(inp)]['len']}）")
        w("")
        w("| 回し方 | cycles | instructions | IPC | L1 の外れ | L2 で当たり |")
        w("|---|---|---|---|---|---|")
        vals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for rep in sorted({r["rep"] for r in rows}):
            z = by[(rep, inp, "none")]
            for m in ("thr", "chain", "small"):
                r = by[(rep, inp, m)]
                n = int(r["calls"])
                for k in ("cycles_u", "instructions_u", "l1_miss_u", "l2_hit_u"):
                    vals[m][k].append((int(r[k]) - int(z[k])) / n)
        for m in ("thr", "chain", "small"):
            v = vals[m]
            ipc = [a / b for a, b in zip(v["instructions_u"], v["cycles_u"], strict=True)]
            w(f"| {m} | {med(v['cycles_u'])} | {med(v['instructions_u'])} | {med3(ipc)} | "
              f"{med3(v['l1_miss_u'])} | {med3(v['l2_hit_u'])} |")
        thr, chain, small = (vals[m]["cycles_u"] for m in ("thr", "chain", "small"))
        rc = statistics.median(real[st]["cyc_call"])
        w("")
        w(f"- chain − thr: {med([a - b for a, b in zip(chain, thr, strict=True)])}、"
          f"thr − small: {med([a - b for a, b in zip(thr, small, strict=True)])}")
        w(f"- 本物の {st} の rankOf {rc:.1f} cycles / 呼び出し（6本の中央値）を3つに分ける"
          "（README の「主因の決め方」）:")
        ts, tt = statistics.median(small), statistics.median(thr)
        w(f"  - 計算（small）: {ts:.1f}")
        w(f"  - L2 の待ち（thr − small）: {tt - ts:.1f}")
        w(f"  - 重ねきれない分（本物 − thr）: {rc - tt:.1f}")


def main() -> int:
    out = ["# rank_fast 段1の集計（summary1.py が生ログから作る。手で書かない）", ""]
    real = stage1(out)
    rankbench(out, real)
    text = "\n".join(out) + "\n"
    if "--write" in sys.argv:
        (LOGS / "summary_stage1.txt").write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
