#!/usr/bin/python3
"""実験 perf_38 の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/perf_38/summary.py > experiments/perf_38/logs/summary.txt

式は README の「式」の節 (perf_34 と同じ。derived() は perf_34/summary.py の写し)。組ごとに別の本で数えるので,
どの量もその本の cycles で割ってから組み合わせる。回 (r1〜r3) ごと・腕ごとに8つの組から値を出し, 3回の中央値と
範囲 (最小〜最大) を並べる。腕どうしの差 (r38 − r37) は同じ回の2本の差を取ってから中央値と範囲。
- 局面1つあたりの分母は F1 で展開した局面 (forward.tsv の n_in の合計)。全本で同じことを確かめる
- perf record (cycles:pp・mem_load_uops_retired.l3_miss:pp) は標本を区分 (bucket()) に寄せ, 割合 × その回・その腕の
  T1 の1局面あたり cycles (LLC のロードミスは C1 の l3_miss) で1局面あたりにする
- 生成器だけのベンチ (experiments/f1_select_catch/logs/summary.txt の order の base・precheck) と並べる
- F1 の秒は門番 #38 の F1 (experiments/gate_38_precheck/logs/summary.txt) と並べる (perf の分の重さ)
"""

from __future__ import annotations

import csv
import pathlib
import re
import statistics
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = HERE / "logs"
ARMS = ("r37", "r38")
IMPL = {"r37": "37_mirror1", "r38": "38_precheck"}
SETS = ("T1", "T2", "M1", "M2", "M3", "C1", "C2", "S1")
REPS = ("1", "2", "3")
FREQ_GHZ = 3.408  # f1_select_catch と同じ換算の周波数
N_F1 = 246_803_167
START = re.compile(r"^=== 開始 (?P<label>r(?P<rep>\d)_(?P<kind>\w+)_(?P<arm>r3[78])) \(")
DONE = re.compile(r"^=== 完了 (?P<label>\S+) ")
BENCH = re.compile(r"^\| (base|precheck|precheck − base) \| order \| (.+) \|$")


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def n_in(label: str) -> int:
    with (LOGS / f"{label}_forward.tsv").open(encoding="utf-8") as f:
        return sum(int(r["n_in"]) for r in csv.DictReader(f, delimiter="\t"))


def stat(label: str) -> tuple[dict[str, float], float]:
    """(イベント → 値, 多重化の最小の比率 %)。"""
    out: dict[str, float] = {}
    pct = 100.0
    for line in (LOGS / f"{label}_stat_F1.csv").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split(",")
        if cols[0].startswith("<"):
            raise SystemExit(f"{label}: {cols[2]} が数えられていない")
        out[cols[2]] = float(cols[0])
        pct = min(pct, float(cols[4]))
    return out, pct


def derived(per: dict[str, dict[str, float]]) -> dict[str, float]:
    """組 → (イベント → 値) から, README の式の量を出す (perf_34/summary.py の derived() の写し)。"""

    def pc(s: str, e: str) -> float:  # その本の1サイクルあたり
        return per[s][e] / per[s]["cycles"]

    d: dict[str, float] = {}
    d["retiring"] = pc("T1", "uops_retired.retire_slots") / 4
    d["frontend"] = pc("T1", "idq_uops_not_delivered.core") / 4
    d["bad_spec"] = (pc("T1", "uops_issued.any") - pc("T1", "uops_retired.retire_slots")) / 4 + pc(
        "T2", "int_misc.recovery_cycles"
    )
    d["backend"] = 1 - d["retiring"] - d["frontend"] - d["bad_spec"]
    ipc = statistics.mean(per[s]["instructions"] / per[s]["cycles"] for s in SETS if s != "S1")
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
    d["sb/cyc"] = pc("S1", "resource_stalls.sb")
    d["ipc"] = ipc
    return d


FRACTIONS = (
    ("retiring", "retiring"),
    ("bad speculation", "bad_spec"),
    ("frontend bound", "frontend"),
    ("backend bound", "backend"),
    ("うち memory bound", "memory_bound"),
    ("うち core bound", "core_bound"),
    ("`stalls_mem_any` / `cycles`", "stalls_mem_any/cyc"),
    ("`stalls_l2_miss` / `cycles`", "stalls_l2_miss/cyc"),
    ("`resource_stalls.sb` / `cycles`（S1）", "sb/cyc"),
)
PER_POS = (
    ("cycles", "T1", "cycles"),
    ("instructions", "T1", "instructions"),
    ("分岐", "M3", "br_inst_retired.all_branches"),
    ("分岐の予測ミス", "T2", "br_misp_retired.all_branches"),
    ("L1 ロードミス", "C1", "mem_load_uops_retired.l1_miss"),
    ("L2 ロードミス", "C1", "mem_load_uops_retired.l2_miss"),
    ("LLC ロードミス", "C1", "mem_load_uops_retired.l3_miss"),
    ("dTLB ミスの歩き", "C2", "dtlb_load_misses.miss_causes_a_walk"),
    ("dTLB 歩きのサイクル", "C2", "dtlb_load_misses.walk_duration"),
    ("`stalls_mem_any` のサイクル", "M1", "cycle_activity.stalls_mem_any"),
    ("`stalls_l2_miss` のサイクル", "M3", "cycle_activity.stalls_l2_miss"),
    ("書き込みの命令（S1 `mem_uops_retired.all_stores`）", "S1", "mem_uops_retired.all_stores"),
    ("書き込みの溜まりで止まったサイクル（S1 `resource_stalls.sb`）", "S1", "resource_stalls.sb"),
    ("書き込みの読み込みの L2 外れ（S1 `l2_rqsts.rfo_miss`）", "S1", "l2_rqsts.rfo_miss"),
)


def mid(xs: list[float], fmt: str) -> str:
    return f"{statistics.median(xs):{fmt}}（{min(xs):{fmt}}〜{max(xs):{fmt}}）"


def bench() -> dict[str, list[float]]:
    """f1_select_catch のベンチの order の1局面あたり: 名前 → [cycles, instructions, 分岐, 予測ミス] (中央値)。"""
    out: dict[str, list[float]] = {}
    text = (ROOT / "experiments" / "f1_select_catch" / "logs" / "summary.txt").read_text(encoding="utf-8")
    for ln in text.splitlines():
        if m := BENCH.match(ln):
            out.setdefault(m.group(1), [float(c.split("（")[0]) for c in m.group(2).split(" | ")])
    return out


def gate_f1() -> tuple[float, float]:
    text = (ROOT / "experiments" / "gate_38_precheck" / "logs" / "summary.txt").read_text(encoding="utf-8")
    m = re.search(r"^\| F1 \| ([\d.]+)（[^）]*） \| ([\d.]+)（", text, re.M)
    assert m, "門番 #38 の summary.txt に F1 の行が無い"
    return float(m.group(1)), float(m.group(2))


def source(arm: str) -> list[str]:
    return (ROOT / "impl" / IMPL[arm] / "animal_shogi.c").read_text(encoding="utf-8").splitlines()


def precheck_lines(src: list[str]) -> set[int]:
    """先行判定の区画の行 (1始まり)。r37 には無い。"""
    lo = next((i + 1 for i, ln in enumerate(src) if "キャッチの先行判定." in ln), None)
    hi = next((i + 1 for i, ln in enumerate(src) if "if (hit) return 0;" in ln), None)
    return set(range(lo, hi + 1)) if lo and hi else set()


def bucket(arm: str, where: str, inline: str, line: str) -> str:
    """標本の区分。名前と行の文で分ける (インライン展開されたものは一番内側の関数で)。"""
    if where == "[kernel]":
        return "カーネル"
    if where.startswith(("python", "libpython")):
        return "Python"
    if where.startswith("libc"):
        return "libc"
    if where != "animal_shogi.so":
        return f"そのほか（{where}）"
    src = SOURCES[arm]
    ln = int(line)
    text = src[ln - 1] if 0 < ln <= len(src) else ""
    if inline == "komaSet" or (inline == "nextBoardInvNormalNC" and ln in PRECHECK[arm]):
        return "生成器: 先行判定"
    if inline in ("nextBoardInvNormalNC", "normalBoard"):
        return "生成器: 本体"
    if inline == "invBoard":
        return "生成器: invBoard"
    if inline.startswith("rank"):
        return "rankOf（番号の計算）"
    if inline == "seenTestAndSet":
        return "seenTestAndSet（発見済みの表）"
    if inline == "nextBoardSeenNormal":
        if "g_prep[rb] =" in text:
            return "nextBoardSeenNormal: g_prep[rb] の書き込み"
        if "__builtin_prefetch(&g_prep" in text:
            return "nextBoardSeenNormal: g_prep の先読み"
        if "__builtin_prefetch(&g_seen" in text:
            return "nextBoardSeenNormal: g_seen の先読み"
        return "nextBoardSeenNormal: ほか"
    if inline == "zeroPush":
        return "nextBoardSeenNormal: zeroPush"
    if inline.startswith("expand"):
        return "expandRound"
    return f"animal_shogi.so: {inline}"


SOURCES = {a: source(a) for a in ARMS}
PRECHECK = {a: precheck_lines(SOURCES[a]) for a in ARMS}


def record(label: str) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """(イベント → 区分 → 標本の数, イベント → 標本の合計)。"""
    arm = label.rsplit("_", 1)[1]
    per: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    tot: dict[str, int] = defaultdict(int)
    with (LOGS / f"{label}_record.tsv").open(encoding="utf-8") as f:
        rows = csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t")
        for r in rows:
            n = int(r["samples"])
            b = bucket(arm, r["where"], r["inline"], r["line"])
            per[r["event"]][b] += n
            tot[r["event"]] += n
    return per, tot


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    started: dict[str, tuple[str, str, str]] = {}
    finished: set[str] = set()
    for line in (LOGS / "console.log").read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            started[m.group("label")] = (m.group("rep"), m.group("kind"), m.group("arm"))
        elif m := DONE.match(line):
            finished.add(m.group("label"))
    kinds = {k for _, k, _ in started.values()}
    print("## 本数と検査")
    print()
    print(f"- 開始 {len(started)} 本 / 完了 {len(finished)} 本 / 種類 {sorted(kinds)}")
    ns = {lb: n_in(lb) for lb in finished}
    print(f"- F1 で展開した局面（n_in の合計）: {sorted(set(ns.values()))}（全本で同じなら1つ）")
    answers = [lb for lb in finished if (LOGS / f"{lb}_answer.txt").read_text().strip().endswith("PASS")]
    print(f"- 答えの検査（md5 一覧が #37 本走と同じ）が PASS の本: {len(answers)} / {len(finished)}")
    n = statistics.median(ns.values())
    print()

    stats: dict[tuple[str, str, str], dict[str, float]] = {}
    pcts = []
    for lb, (rep, kind, arm) in started.items():
        if kind in SETS and lb in finished:
            s, p = stat(lb)
            stats[(rep, arm, kind)] = s
            pcts.append(p)
    print(f"- 多重化: perf stat の {len(pcts)} 本で, 数えた比率の最小 {min(pcts):.2f}%")
    print()

    sec = {
        arm: [tsv(LOGS / f"{lb}_forward_summary.tsv")["F1"] for lb, (_, k, a) in started.items()
              if a == arm and k != "record" and lb in finished]
        for arm in ARMS
    }  # fmt: skip
    rec_sec = {
        arm: [tsv(LOGS / f"{lb}_forward_summary.tsv")["F1"] for lb, (_, k, a) in started.items()
              if a == arm and k == "record" and lb in finished]
        for arm in ARMS
    }  # fmt: skip
    g37, g38 = gate_f1()
    print("## F1 の秒（perf を付けた分の重さ。門番 #38 の F1 は perf なし）")
    print()
    for arm, g in (("r37", g37), ("r38", g38)):
        st = sec[arm]
        print(f"- {arm}: perf stat の本 {mid(st, '.2f')} 秒、perf record の本 {mid(rec_sec[arm], '.2f')} 秒 / "
              f"門番 #38 {g:.2f} 秒（stat の中央値で {statistics.median(st) / g - 1:+.1%}）")  # fmt: skip
    print()

    per_rep: dict[tuple[str, str], dict[str, float]] = {}
    pos: dict[tuple[str, str], dict[str, float]] = {}
    for rep in REPS:
        for arm in ARMS:
            if not all((rep, arm, s) in stats for s in SETS):
                continue
            per = {s: stats[(rep, arm, s)] for s in SETS}
            per_rep[(rep, arm)] = derived(per)
            pos[(rep, arm)] = {name: per[s][e] / n for name, s, e in PER_POS}
    reps = sorted({r for r, _ in per_rep})
    print(f"## F1 の topdown（{len(reps)} 回の中央値と範囲。式は README）")
    print()
    print("| | r37 | r38 | r38 − r37 |")
    print("|---|---|---|---|")
    for title, key in FRACTIONS:
        a = [per_rep[(r, "r37")][key] for r in reps]
        b = [per_rep[(r, "r38")][key] for r in reps]
        d = [y - x for x, y in zip(a, b, strict=True)]
        print(f"| {title} | {mid(a, '.1%')} | {mid(b, '.1%')} | {mid([x * 100 for x in d], '+.1f')} ポイント |")
    a = [per_rep[(r, "r37")]["ipc"] for r in reps]
    b = [per_rep[(r, "r38")]["ipc"] for r in reps]
    print(f"| IPC | {mid(a, '.3f')} | {mid(b, '.3f')} | {mid([y - x for x, y in zip(a, b, strict=True)], '+.3f')} |")
    print()
    print("### 局面1つあたり（分母は F1 で展開した局面）")
    print()
    print("| | r37 | r38 | r38 − r37 |")
    print("|---|---|---|---|")
    for name, _, _ in PER_POS:
        a = [pos[(r, "r37")][name] for r in reps]
        b = [pos[(r, "r38")][name] for r in reps]
        fmt = ".1f" if max(a) > 20 else ".3f"
        d = [y - x for x, y in zip(a, b, strict=True)]
        print(f"| {name} | {mid(a, fmt)} | {mid(b, fmt)} | {mid(d, '+' + fmt)} |")
    print()
    print("### topdown の区分をサイクルに直した差（区分の割合 × 1局面あたり cycles。r38 − r37）")
    print()
    for title, key in FRACTIONS[:6]:
        d = [
            per_rep[(r, "r38")][key] * pos[(r, "r38")]["cycles"]
            - per_rep[(r, "r37")][key] * pos[(r, "r37")]["cycles"]
            for r in reps
        ]
        print(f"- {title}: {mid(d, '+.1f')} cycles / 局面")
    print()

    b = bench()
    print("## 生成器だけのベンチとの照らし合わせ（ベンチは f1_select_catch の order。1局面あたり）")
    print()
    real = {
        k: [pos[(r, "r38")][k] - pos[(r, "r37")][k] for r in reps]
        for k in ("cycles", "instructions", "分岐", "分岐の予測ミス")
    }
    print("| | ベンチ base | ベンチ precheck | ベンチの差 | 本物 r37 | 本物 r38 | 本物の差 | 本物 ÷ ベンチ |")
    print("|---|---|---|---|---|---|---|---|")
    for i, k in enumerate(("cycles", "instructions", "分岐", "分岐の予測ミス")):
        r37 = statistics.median(pos[(r, "r37")][k] for r in reps)
        r38 = statistics.median(pos[(r, "r38")][k] for r in reps)
        bd = b["precheck − base"][i]
        rd = statistics.median(real[k])
        print(f"| {k} | {b['base'][i]:.1f} | {b['precheck'][i]:.1f} | {bd:+.1f} | {r37:.1f} | {r38:.1f} "
              f"| {mid(real[k], '+.1f')} | {rd / bd:.0%} |")  # fmt: skip
    print()
    r37c = statistics.median(pos[(r, "r37")]["cycles"] for r in reps)
    print(f"- 本物 − ベンチ base の cycles（生成器と番号の計算の外の仕事とメモリの待ちの上限）: r37 "
          f"{r37c - b['base'][0]:.1f}、r38 {statistics.median(pos[(r, 'r38')]['cycles'] for r in reps) - b['precheck'][0]:.1f}")  # fmt: skip
    print(f"- 消えた cycles（ベンチの差 − 本物の差）: {b['precheck − base'][0] - statistics.median(real['cycles']):+.1f} / 局面"
          f"（F1 の秒にして {(b['precheck − base'][0] - statistics.median(real['cycles'])) * N_F1 / (FREQ_GHZ * 1e9):+.2f} 秒）")  # fmt: skip
    print()

    print("## どこで時間を使っているか（perf record。区分ごとの1局面あたり ＝ 標本の割合 × その回・その腕の T1 の cycles）")
    print()
    rec: dict[tuple[str, str], tuple[dict[str, dict[str, int]], dict[str, int]]] = {}
    for lb, (rep, kind, arm) in started.items():
        if kind == "record" and lb in finished:
            rec[(rep, arm)] = record(lb)
    for ev, scale in (("cycles:pp", "cycles"), ("mem_load_uops_retired.l3_miss:pp", "LLC ロードミス")):
        names = sorted({bk for (_r, _a), (per, _t) in rec.items() for bk in per.get(ev, {})})
        print(f"### {ev}（1局面あたりは × {scale}）")
        print()
        tots = {a: [rec[(r, a)][1].get(ev, 0) for r in reps if (r, a) in rec] for a in ARMS}
        print(f"標本の数: r37 {tots['r37']}、r38 {tots['r38']}")
        print()
        print("| 区分 | r37 の割合 | r38 の割合 | r37 / 局面 | r38 / 局面 | r38 − r37 |")
        print("|---|---|---|---|---|---|")
        rows = []
        for bk in names:
            sh = {a: [rec[(r, a)][0][ev].get(bk, 0) / rec[(r, a)][1][ev] for r in reps if (r, a) in rec] for a in ARMS}
            pp = {a: [s * pos[(r, a)][scale] for s, r in zip(sh[a], reps, strict=True)] for a in ARMS}
            d = [y - x for x, y in zip(pp["r37"], pp["r38"], strict=True)]
            rows.append((statistics.median(d), bk, sh, pp, d))
        fmt = ".1f" if scale == "cycles" else ".4f"
        for _, bk, sh, pp, d in sorted(rows, key=lambda x: x[0]):
            print(f"| {bk} | {mid(sh['r37'], '.1%')} | {mid(sh['r38'], '.1%')} | {mid(pp['r37'], fmt)} "
                  f"| {mid(pp['r38'], fmt)} | {mid(d, '+' + fmt)} |")  # fmt: skip
        print()
    for (rep, arm), _ in sorted(rec.items()):
        p = LOGS / f"r{rep}_record_{arm}_record_stats.txt"
        if p.exists():
            print(f"- 間引き r{rep} {arm}: " + " / ".join(ln.strip() for ln in p.read_text().splitlines()[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
