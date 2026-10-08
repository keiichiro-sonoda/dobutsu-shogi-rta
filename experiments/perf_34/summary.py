#!/usr/bin/python3
"""実験 perf_34 の集計 (記録試行ではない)。

    python3 experiments/perf_34/summary.py > experiments/perf_34/logs/summary.txt

式は README の「式」の節。組ごとに別の本で数えるので, どの量もその本の cycles で割ってから
組み合わせる。
回 (r1〜r3) ごとに7つの組から値を出し, 3回の中央値と範囲 (最小〜最大) を並べる。
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
START = re.compile(r"^=== 開始 (?P<label>\S+) \((?P<kind>[^\s:]+(?::\w+)?): ")
STAGES = ("F1", "U_loop")
SETS = ("T1", "T2", "M1", "M2", "M3", "C1", "C2")


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def stage_sec(label: str) -> dict[str, float]:
    f = tsv(LOGS / f"{label}_forward_summary.tsv")
    r = tsv(LOGS / f"{label}_retreat_summary.tsv")
    return {"F1": f["F1"], "U_loop": r["U_loop"]}


def counts(label: str) -> dict[str, int]:
    with (LOGS / f"{label}_forward.tsv").open(encoding="utf-8") as f:
        n_in = sum(int(r["n_in"]) for r in csv.DictReader(f, delimiter="\t"))
    text = (LOGS / f"{label}_main.log").read_text(encoding="utf-8")
    front = int(re.search(r"展開した局面 \(perf_34\)：(\d+)", text).group(1))
    cand = int(re.search(r"前任の候補：(\d+)", text).group(1))
    return {"F1": n_in, "U_loop": front, "cand": cand}


def stat(label: str, stage: str) -> tuple[dict[str, float], float]:
    """(イベント → 値, 多重化の最小の比率 %)。"""
    out: dict[str, float] = {}
    pct = 100.0
    for line in (LOGS / f"{label}_stat_{stage}.csv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split(",")
        if cols[0].startswith("<"):
            raise SystemExit(f"{label} {stage}: {cols[2]} が数えられていない")
        out[cols[2]] = float(cols[0])
        pct = min(pct, float(cols[4]))
    return out, pct


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def derived(per: dict[str, dict[str, float]]) -> dict[str, float]:
    """組 → (イベント → 値) から, README の式の量を出す。"""

    def pc(s: str, e: str) -> float:  # その本の1サイクルあたり
        return per[s][e] / per[s]["cycles"]

    d: dict[str, float] = {}
    d["retiring"] = pc("T1", "uops_retired.retire_slots") / 4
    d["frontend"] = pc("T1", "idq_uops_not_delivered.core") / 4
    d["bad_spec"] = (pc("T1", "uops_issued.any") - pc("T1", "uops_retired.retire_slots")) / 4 + pc(
        "T2", "int_misc.recovery_cycles"
    )
    d["backend"] = 1 - d["retiring"] - d["frontend"] - d["bad_spec"]
    ipc = statistics.mean(per[s]["instructions"] / per[s]["cycles"] for s in SETS)
    fetch_lat = pc("T2", "idq_uops_not_delivered.cycles_0_uops_deliv.core")
    ge = (
        pc("M2", "uops_executed.cycles_ge_3_uops_exec")
        if ipc > 1.8
        else pc("M2", "uops_executed.cycles_ge_2_uops_exec")
    )
    rs = pc("M3", "rs_events.empty_cycles") if fetch_lat > 0.1 else 0.0
    sb = pc("M1", "resource_stalls.sb")
    den = (
        pc("M1", "cycle_activity.stalls_total")
        + pc("M2", "uops_executed.cycles_ge_1_uop_exec")
        - ge
        - rs
        + sb
    )
    d["memory_bound"] = d["backend"] * (pc("M1", "cycle_activity.stalls_mem_any") + sb) / den
    d["core_bound"] = d["backend"] - d["memory_bound"]
    d["stalls_mem_any/cyc"] = pc("M1", "cycle_activity.stalls_mem_any")
    d["stalls_l2_miss/cyc"] = pc("M3", "cycle_activity.stalls_l2_miss")
    d["ipc"] = ipc
    return d


PER_POS = (
    ("cycles", "T1", "cycles"),
    ("instructions", "T1", "instructions"),
    ("branches", "M3", "br_inst_retired.all_branches"),
    ("branch-misses", "T2", "br_misp_retired.all_branches"),
    ("L1 ロードミス", "C1", "mem_load_uops_retired.l1_miss"),
    ("L2 ロードミス", "C1", "mem_load_uops_retired.l2_miss"),
    ("LLC ロードミス", "C1", "mem_load_uops_retired.l3_miss"),
    ("dTLB ミスの歩き", "C2", "dtlb_load_misses.miss_causes_a_walk"),
    ("dTLB 歩きのサイクル", "C2", "dtlb_load_misses.walk_duration"),
    ("dTLB STLB で当たり", "C2", "dtlb_load_misses.stlb_hit"),
    ("stalls_mem_any", "M1", "cycle_activity.stalls_mem_any"),
    ("stalls_l2_miss", "M3", "cycle_activity.stalls_l2_miss"),
)
REPORT = re.compile(r"^\s*([\d.]+)%\s+(\S+)\s+\[(.)\]\s+(.+?)\s*$")


def report(label: str, stage: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in (LOGS / f"{label}_report_{stage}.txt").read_text(encoding="utf-8").splitlines():
        if m := REPORT.match(line):
            out[f"{m.group(2)} {m.group(4)}"] = float(m.group(1))
    return out


def bench() -> None:
    path = LOGS / "bench.tsv"
    if not path.exists():
        print("（ベンチの結果が無い）")
        return
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    total: dict[str, int] = {}
    for line in (LOGS / "blocks_index.tsv").read_text(encoding="utf-8").splitlines():
        name, n, _ = line.split("\t")
        total[name] = int(n)
    print("| 段 | 入力 | ns/局面（5周の中央値と範囲） | 段の秒の見積もり | 後続（候補）/ 局面 |")
    print("|---|---|---|---|---|")
    for mode, stage, prefix in (("fwd", "F1", "f1_"), ("unmove", "U_loop", "u_")):
        est: list[float] = []
        ns_o: list[float] = []
        for rep in sorted({r["rep"] for r in rows}):
            rs = [
                r for r in rows if r["rep"] == rep and r["mode"] == mode and r["input"] == "order"
            ]
            sec = sum(total[r["file"][:-4]] * float(r["ns_per_pos"]) * 1e-9 for r in rs)
            n = sum(total[r["file"][:-4]] for r in rs if r["file"].startswith(prefix))
            est.append(sec)
            ns_o.append(sec * 1e9 / n)
        outs = [r for r in rows if r["mode"] == mode and r["input"] == "order" and r["rep"] == "1"]
        w = sum(total[r["file"][:-4]] * float(r["outs_per_pos"]) for r in outs) / sum(
            total[r["file"][:-4]] for r in outs
        )
        print(
            f"| {stage} | order（重み付き） | {mid(ns_o, '.1f')} | {mid(est, '.2f')} 秒 | {w:.3f} |"
        )
        rnd = [r for r in rows if r["mode"] == mode and r["input"] == "random"]
        ns_r = [float(r["ns_per_pos"]) for r in rnd]
        print(f"| {stage} | random | {mid(ns_r, '.1f')} | | {float(rnd[0]['outs_per_pos']):.3f} |")


def main() -> int:
    kinds: dict[str, str] = {}
    for line in (LOGS / "console.log").read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            kinds[m.group("label")] = m.group("kind")
    base = stage_sec("base")
    nbase = counts("base")
    print("## 段の秒（perf の分の重さ）")
    print()
    print("| 本 | 種類 | F1 | `U_loop` | F1 − base | `U_loop` − base |")
    print("|---|---|---|---|---|---|")
    for label, kind in kinds.items():
        s = stage_sec(label)
        print(
            f"| {label} | {kind} | {s['F1']:.2f} | {s['U_loop']:.2f} | "
            f"{s['F1'] - base['F1']:+.2f} | {s['U_loop'] - base['U_loop']:+.2f} |"
        )
    print()
    print(
        f"base の局面数: F1 {nbase['F1']:,} / U_loop {nbase['U_loop']:,} (候補 {nbase['cand']:,})"
    )
    for stage in STAGES:
        print(f"base の {stage} の1局面あたり: {base[stage] * 1e9 / nbase[stage]:.1f} ns")
    print()

    reps = sorted({lb.split("_")[0] for lb in kinds if re.match(r"r\d_", lb)})
    for stage in STAGES:
        print(f"## {stage}")
        print()
        d_all: dict[str, list[float]] = defaultdict(list)
        pp: dict[str, list[float]] = defaultdict(list)
        pcand: dict[str, list[float]] = defaultdict(list)
        pct_min: dict[str, float] = {}
        for r in reps:
            per: dict[str, dict[str, float]] = {}
            for s in SETS:
                lb = f"{r}_{s}"
                per[s], pct = stat(lb, stage)
                pct_min[lb] = pct
                n = counts(lb)
                for name, ss, ev in PER_POS:
                    if ss == s:
                        pp[name].append(per[s][ev] / n[stage])
                        pcand[name].append(per[s][ev] / n["cand"])
            for k, v in derived(per).items():
                d_all[k].append(v)
        print("### 大まかな内訳（スロットの割合。3回の中央値と範囲）")
        print()
        for k in (
            "retiring",
            "bad_spec",
            "frontend",
            "backend",
            "memory_bound",
            "core_bound",
            "stalls_mem_any/cyc",
            "stalls_l2_miss/cyc",
            "ipc",
        ):
            fmt = ".3f" if k == "ipc" else ".1%"
            print(f"- {k}: {mid(d_all[k], fmt)}")
        print()
        print("### 局面1個あたり" + ("（右は候補1個あたり）" if stage == "U_loop" else ""))
        print()
        for name, _, _ in PER_POS:
            extra = f" / {mid(pcand[name], '.3f')}" if stage == "U_loop" else ""
            print(f"- {name}: {mid(pp[name], '.3f')}{extra}")
        print()
        bad = {k: v for k, v in pct_min.items() if v < 100.0}
        print(f"多重化: {bad if bad else 'なし (全組 100%)'}")
        print()
        print("### 関数ごとの割合（perf record。3回の中央値。0.5% 以上）")
        print()
        rec = [report(f"{r}_record", stage) for r in reps]
        keys = sorted(
            {k for x in rec for k in x}, key=lambda k: -statistics.median(x.get(k, 0) for x in rec)
        )
        for k in keys:
            vals = [x.get(k, 0.0) for x in rec]
            if statistics.median(vals) >= 0.5:
                print(f"- {k}: {mid(vals, '.2f')}%")
        print()
    print("## perf を使わない照らし合わせ")
    print()
    bench()
    return 0


if __name__ == "__main__":
    sys.exit(main())
