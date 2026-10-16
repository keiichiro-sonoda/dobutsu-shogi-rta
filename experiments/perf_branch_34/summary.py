#!/usr/bin/python3
"""実験 perf_branch_34 の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/perf_branch_34/summary.py > experiments/perf_branch_34/logs/summary.txt

読むもの (logs/):
- <r>_pebs_<段>_misp.tsv  予測ミスの標本を分岐の番地ごとに数えたもの (周期 10,007)
- <r>_lbr_<段>_lbr.tsv    LBR から組み立てた分岐ごとの「取られた」「取られて外れた」
  「取られなかった」
- <ラベル>_forward.tsv / _main.log / _forward_summary.tsv / _retreat_summary.tsv  局面数と段の秒
- bench_branch.tsv・bench_overhead.tsv・blocks_index.tsv・split_index.tsv (副のベンチ)
- categories.tsv (回す前に決めた束ね方)
- experiments/perf_34/logs/ の r1〜r3 の perf stat (段の分岐の総数とサイクル. 率と秒の換算に使う)

量の定義:
- 予測ミスの推定 ＝ 標本 × 10,007。段の中の割合 ＝ その分岐の標本 ÷ 段の標本の合計 (.so の外も含む)
- 実行の推定 ＝ LBR の (取られた ＋ 取られなかった) を, .so の中の合計で割って段の分岐の総数
  (perf_34 の br_inst_retired.all_branches の中央値) を掛けたもの. .so の外の分岐も総数に
  入っているので,
  .so の中の分岐の実行はわずかに多めに出る (率はわずかに低めに出る)
- 率 ＝ 予測ミスの推定 ÷ 実行の推定. LBR の「取られた側の外れの率」(取られて外れた ÷ 取られた)
  も並べる
- 上限の秒 ＝ 予測ミスの推定 × (15 または 20 サイクル) ÷ 周波数. 周波数 ＝ perf_34 の段の
  サイクルの中央値 ÷ この実験の base の段の秒. **全部消せた場合の上限で, 見込みではない**
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
STAGES = ("F1", "U_loop")
REPS = ("r1", "r2", "r3")
PERIOD = 10007
BUNDLES = {
    "F1": (
        "駒の種類と空き",
        "盤の端",
        "行き先の駒",
        "キャッチ",
        "トライ・成り",
        "持ち駒の数",
        "左右の正規化",
        "表の引き当て",
        "局面の種類",
        "ループの回数",
        "その他",
    ),
    "U_loop": (
        "王手の数",
        "X の駒か",
        "駒の種類",
        "盤の端",
        "元のマスが空いているか",
        "キャッチ",
        "持ち駒・取った駒の数",
        "左右の正規化",
        "表の引き当て",
        "ループの回数",
        "その他",
    ),
}
OUTSIDE = "段の外 (Python・libc・カーネル)"
UNMAPPED = "分岐に対応づけられない番地"
NOT_IN_TABLE = "対応表に無い行"


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def categories() -> dict[int, tuple[str, str]]:
    out = {}
    for ln in (HERE / "categories.tsv").read_text(encoding="utf-8").splitlines():
        if ln[:1].isdigit():
            line, bundle, what = ln.split("\t")
            out[int(line)] = (bundle, what)
    return out


def table(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t"))


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def positions(label: str, logs: pathlib.Path = LOGS) -> dict[str, int]:
    with (logs / f"{label}_forward.tsv").open(encoding="utf-8") as f:
        n_in = sum(int(r["n_in"]) for r in csv.DictReader(f, delimiter="\t"))
    text = (logs / f"{label}_main.log").read_text(encoding="utf-8")
    front = int(re.search(r"展開した局面 \(perf_34\)：(\d+)", text).group(1))
    cand = int(re.search(r"前任の候補：(\d+)", text).group(1))
    return {"F1": n_in, "U_loop": front, "cand": cand}


def stage_sec(label: str) -> dict[str, float]:
    f = tsv(LOGS / f"{label}_forward_summary.tsv")
    r = tsv(LOGS / f"{label}_retreat_summary.tsv")
    return {"F1": f["F1"], "U_loop": r["U_loop"]}


def p34_stat(label: str, stage: str, event: str) -> float:
    for ln in (P34 / f"{label}_stat_{stage}.csv").read_text(encoding="utf-8").splitlines():
        cols = ln.split(",")
        if len(cols) > 2 and cols[2] == event:
            return float(cols[0])
    raise SystemExit(f"perf_34 の {label} {stage} に {event} が無い")


def p34_per_pos(stage: str, setname: str, event: str) -> float:
    vals = []
    for r in REPS:
        lb = f"{r}_{setname}"
        vals.append(p34_stat(lb, stage, event) / positions(lb, P34)[stage])
    return statistics.median(vals)


def main() -> int:
    cats = categories()
    base = stage_sec("base")
    npos = positions("base")
    print("## 段と量の基準")
    print()
    for st in STAGES:
        br = p34_per_pos(st, "M3", "br_inst_retired.all_branches")
        cy = p34_per_pos(st, "T1", "cycles")
        print(
            f"- {st}: 展開した局面 {npos[st]:,} / base の段の秒 {base[st]:.2f} / "
            f"perf_34 の分岐 {br:.1f}・サイクル {cy:.1f} (1局面あたり, 3回の中央値) / "
            f"周波数の換算 {cy * npos[st] / base[st] / 1e9:.3f} GHz"
        )
    print(f"- U_loop の候補: {npos['cand']:,}")
    for lb in (*[f"{r}_pebs" for r in REPS], *[f"{r}_lbr" for r in REPS]):
        s = stage_sec(lb)
        print(
            f"- {lb} の段の秒: F1 {s['F1']:.2f} / U_loop {s['U_loop']:.2f} (base との差は比べない)"
        )
    print()

    for st in STAGES:
        n = npos[st]
        br_total = p34_per_pos(st, "M3", "br_inst_retired.all_branches") * n
        cyc_pos = p34_per_pos(st, "T1", "cycles")
        freq = cyc_pos * n / base[st]
        # 予測ミス: 回ごとに 分岐 → 標本, と外側
        misp: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {}
        info: dict[str, tuple[str, str, int]] = {}
        for r in REPS:
            rows = table(LOGS / f"{r}_pebs_{st}_misp.tsv")
            m: dict[str, int] = defaultdict(int)
            for row in rows:
                if row["where"] == "animal_shogi.so":
                    m[row["addr"]] += int(row["samples"])
                    info[row["addr"]] = (row["func"], row["inline"], int(row["line"]))
                elif row["where"] == "unmapped":
                    m[UNMAPPED] += int(row["samples"])
                else:
                    m[OUTSIDE] += int(row["samples"])
            misp[r] = m
            totals[r] = sum(m.values())
        # LBR: 回ごとに 分岐 → (実行, 取られた, 取られて外れた)
        lbr: dict[str, dict[str, tuple[int, int, int]]] = {}
        for r in REPS:
            rows = table(LOGS / f"{r}_lbr_{st}_lbr.tsv")
            lbr[r] = {
                row["addr"]: (
                    int(row["taken"]) + int(row["not_taken"]),
                    int(row["taken"]),
                    int(row["taken_misp"]),
                )
                for row in rows
            }
            for row in rows:
                info.setdefault(row["addr"], (row["func"], row["inline"], int(row["line"])))

        def share(r: str, k: str, misp=misp, totals=totals) -> float:  # type: ignore[no-untyped-def]
            return misp[r].get(k, 0) / totals[r]

        def exec_est(r: str, k: str, lbr=lbr, br_total=br_total) -> float:  # type: ignore[no-untyped-def]
            tot = sum(v[0] for v in lbr[r].values())
            return lbr[r].get(k, (0, 0, 0))[0] / tot * br_total

        keys = sorted(
            {k for r in REPS for k in misp[r]},
            key=lambda k: -statistics.median(share(r, k) for r in REPS),
        )
        print(f"## {st}: 分岐ごと（予測ミスの多い順。3回の中央値と範囲）")
        print()
        print(
            f"標本: {', '.join(f'{r} {totals[r]:,}' for r in REPS)}。"
            f"予測ミスの推定 / 局面: "
            f"{mid([totals[r] * PERIOD / n for r in REPS], '.2f')}"
        )
        print()
        print(
            "| 順 | 関数（インライン） | 行 | 番地 | 束 | 何を判定しているか | 段の中の割合 | "
            "ミス / 局面 | 率（推定） | 取られた側の外れの率（LBR） | 累積 |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        cum = 0.0
        shown = 0
        for k in keys:
            sh = [share(r, k) for r in REPS]
            cum += statistics.median(sh)
            if k in (OUTSIDE, UNMAPPED):
                print(f"| | {k} | | | | | {mid(sh, '.1%')} | | | | {cum:.1%} |")
                continue
            f, g, ln = info[k]
            bundle, what = cats.get(ln, (NOT_IN_TABLE, ""))
            fn = f if f == g else f"{f}（{g}）"
            per = [misp[r].get(k, 0) * PERIOD / n for r in REPS]
            rate = []
            tk = []
            for r in REPS:
                e = exec_est(r, k)
                if e > 0:
                    rate.append(misp[r].get(k, 0) * PERIOD / e)
                t = lbr[r].get(k, (0, 0, 0))
                if t[1] > 0:
                    tk.append(t[2] / t[1])
            rs = mid(rate, ".1%") if rate else "-"
            ts = mid(tk, ".1%") if tk else "（取られた記録なし）"
            shown += 1
            print(
                f"| {shown} | {fn} | {ln} | {k} | {bundle} | {what} | {mid(sh, '.1%')} | "
                f"{mid(per, '.3f')} | {rs} | {ts} | {cum:.1%} |"
            )
            if cum >= 0.8 or shown >= 30:
                break
        print()
        print(f"ここまでで段の予測ミスの {cum:.1%}（上位 {shown} 個の分岐と、表に出た外側）")
        print()

        # 上位5個の顔ぶれ
        tops = []
        for r in REPS:
            ks = sorted(
                (k for k in misp[r] if k not in (OUTSIDE, UNMAPPED)), key=lambda k: -misp[r][k]
            )
            tops.append(ks[:5])
        same = all(set(t) == set(tops[0]) for t in tops)
        order = all(t == tops[0] for t in tops)
        print(f"### {st}: 上位5個の分岐の顔ぶれ")
        print()
        for r, t in zip(REPS, tops, strict=True):
            print(f"- {r}: {', '.join(f'{k}（{info[k][2]}行）' for k in t)}")
        print(
            f"- 顔ぶれ: {'3回とも同じ' if same else '**揃わない**'}"
            f" / 順位: {'同じ' if order else '入れ替わりあり'}"
        )
        print()

        # 束ごと
        print(f"### {st}: 束ごと（3回の中央値と範囲。上限の秒は全部消せた場合で, 見込みではない）")
        print()
        print(
            "| 束 | 段の中の割合 | ミス / 局面 | 上限の秒（15 サイクル） "
            "| 上限の秒（20 サイクル） |"
        )
        print("|---|---|---|---|---|")
        bsum: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for i, r in enumerate(REPS):
            for k, v in misp[r].items():
                b = k if k in (OUTSIDE, UNMAPPED) else cats.get(info[k][2], (NOT_IN_TABLE, ""))[0]
                bsum[b][i] += v
        order_b = [*BUNDLES[st], NOT_IN_TABLE, UNMAPPED, OUTSIDE]
        for b in [*order_b, *sorted(set(bsum) - set(order_b))]:
            if b not in bsum:
                continue
            sh = [bsum[b][i] / totals[r] for i, r in enumerate(REPS)]
            per = [bsum[b][i] * PERIOD / n for i in range(3)]
            s15 = [bsum[b][i] * PERIOD * 15 / freq for i in range(3)]
            s20 = [bsum[b][i] * PERIOD * 20 / freq for i in range(3)]
            print(
                f"| {b} | {mid(sh, '.1%')} | {mid(per, '.3f')} | {mid(s15, '.2f')} | "
                f"{mid(s20, '.2f')} |"
            )
        print()

        # LBR との照合
        print(f"### {st}: LBR との照合（取られて外れた回数の上位5個と、PEBS の順位）")
        print()
        pebs_rank = {
            k: i + 1 for i, k in enumerate(k for k in keys if k not in (OUTSIDE, UNMAPPED))
        }
        for r in REPS:
            lt = sorted(lbr[r], key=lambda k: -lbr[r][k][2])[:5]
            s = ", ".join(f"{k}（{info[k][2]}行, PEBS {pebs_rank.get(k, '-')} 位）" for k in lt)
            print(f"- {r}: {s}")
        tot_lbr = [sum(v[0] for v in lbr[r].values()) for r in REPS]
        print(f"- LBR から組み立てた実行の延べ (.so の中): {', '.join(f'{x:,}' for x in tot_lbr)}")
        print()

        # キャッチの return 0 の行
        if st == "F1":
            catch_lines = {ln for ln, (b, _) in cats.items() if b == "キャッチ"}
            cs = [
                sum(v for k, v in misp[r].items() if k in info and info[k][2] in catch_lines)
                / totals[r]
                for r in REPS
            ]
            print(f"キャッチの行 ({sorted(catch_lines)}) の分岐そのものの割合: {mid(cs, '.1%')}")
            print()

    bench()
    return 0


def bench() -> None:
    path = LOGS / "bench_branch.tsv"
    if not path.exists():
        print("（ベンチの結果が無い）")
        return
    rows = table(path)
    oh = table(LOGS / "bench_overhead.tsv")
    total: dict[str, int] = {}
    for line in (LOGS / "blocks_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, _ = line.split("\t")
        total[name] = int(n)
    split: dict[str, tuple[int, int, int]] = {}
    for line in (LOGS / "split_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, c, o = line.split("\t")
        split[name] = (int(n), int(c), int(o))
    evs = ("cycles_u", "instructions_u", "br_misp_u", "br_inst_u")
    print(
        "## 副: 生成器だけのベンチ（ユーザー側。固定の分を引き, 2 × 局面数で割った1局面あたり。"
        "3周の中央値と範囲）"
    )
    print()
    print("| 段 | 入力 | cycles | instructions | 分岐 | 予測ミス |")
    print("|---|---|---|---|---|---|")
    res: dict[tuple[str, str], dict[str, list[float]]] = {}
    for mode, st in (("fwd", "F1"), ("unmove", "U_loop")):
        ohv = {e: statistics.median(float(r[e]) for r in oh if r["mode"] == mode) for e in evs}
        inputs = ("order", "random", "catch", "other") if mode == "fwd" else ("order", "random")
        for inp in inputs:
            out: dict[str, list[float]] = defaultdict(list)
            for rep in sorted({r["rep"] for r in rows}):
                rs = [
                    r for r in rows if r["rep"] == rep and r["mode"] == mode and r["input"] == inp
                ]
                if not rs:
                    continue
                for e in evs:
                    num = 0.0
                    den = 0.0
                    for r in rs:
                        stem = r["file"][:-4]
                        if inp == "order":
                            w = total[stem]
                        elif inp == "catch":
                            w = total[stem] * split[stem][1] / split[stem][0]
                        elif inp == "other":
                            w = total[stem] * split[stem][2] / split[stem][0]
                        else:
                            w = 1.0
                        v = (float(r[e]) - ohv[e]) / (2 * int(r["n"]))
                        num += v * w
                        den += w
                    out[e].append(num / den)
            res[(st, inp)] = out
            print(
                f"| {st} | {inp} | {mid(out['cycles_u'], '.1f')} "
                f"| {mid(out['instructions_u'], '.1f')} | "
                f"{mid(out['br_inst_u'], '.1f')} | {mid(out['br_misp_u'], '.2f')} |"
            )
    print()
    for st in STAGES:
        o, r = res[(st, "order")], res[(st, "random")]
        dc = [b - a for a, b in zip(o["cycles_u"], r["cycles_u"], strict=True)]
        dm = [b - a for a, b in zip(o["br_misp_u"], r["br_misp_u"], strict=True)]
        ex15 = [m * 15 / c for m, c in zip(dm, dc, strict=True)]
        ex20 = [m * 20 / c for m, c in zip(dm, dc, strict=True)]
        print(
            f"- {st}: random − order は cycles {mid(dc, '+.1f')}, 予測ミス {mid(dm, '+.2f')}。"
            f"予測ミスの差 × 15〜20 サイクルが cycles の差に占める割合 "
            f"{mid(ex15, '.0%')}〜{mid(ex20, '.0%')}"
        )
    k = sum(v[1] for v in split.values())
    n = sum(v[0] for v in split.values())
    c, ot = res[("F1", "catch")], res[("F1", "other")]
    print(
        f"- F1 のブロックのキャッチ局面: {k:,} / {n:,}（{k / n:.1%}）。"
        f"生成器だけでの予測ミス / 局面: キャッチ局面 {mid(c['br_misp_u'], '.2f')}, "
        f"それ以外 {mid(ot['br_misp_u'], '.2f')}"
    )


if __name__ == "__main__":
    sys.exit(main())
