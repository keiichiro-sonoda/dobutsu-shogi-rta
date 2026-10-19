#!/usr/bin/python3
"""実験 perf_39 の集計 (記録試行ではない)。手で書かず, 生ログからこれで作る。

    python3 experiments/perf_39/summary.py > experiments/perf_39/logs/summary.txt

式は README の「式」の節 (perf_38 と同じ。derived() は perf_38/summary.py の写し)。組ごとに別の本で数えるので,
どの量もその本の cycles で割ってから組み合わせる。回 (r1〜r3) ごとに8つの組から値を出し, 3回の中央値と範囲 (最小〜最大)。
- 分母: F1 は展開した局面 (forward.tsv の n_in の合計)。U_loop はフロンティアの延べ数 (main.log の「展開した局面 (perf_34)」)
  と候補の延べ数 (「前任の候補」)。全本で同じことを確かめる
- perf record (cycles:pp・mem_load_uops_retired.l2_miss:pp) は標本を区分 (bucket_u() / bucket_f()) に寄せ,
  割合 × その回の T1 の1局面あたり cycles (L2 のロードミスは C1 の l2_miss) で1局面あたりにする。区分の秒は割合 × その回の T1 の本の段の秒
- rank_fast の benchUnmove の lean (logs/summary_stage2.txt) と, perf_34 の U_loop (logs/summary.txt) と並べる
- 手数ごとの表は u_loop_depth.tsv (depth_log.patch) の T1 の3本の中央値
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
SETS = ("T1", "T2", "M1", "M2", "M3", "C1", "C2", "S1")
REPS = ("1", "2", "3")
STAGES = ("F1", "U_loop")
N_UNREACHABLE = 82_992_958  # 候補のうち到達しない局面で捨てるもの (experiments/unmove_prune)
START = re.compile(r"^=== 開始 (?P<label>r(?P<rep>\d)_(?P<kind>\w+)) \(")
DONE = re.compile(r"^=== 完了 (?P<label>\S+) ")
SRC = (ROOT / "impl" / "39_rank_lean" / "animal_shogi.c").read_text(encoding="utf-8").splitlines()


def line_of(text: str, start: int = 0) -> int:
    """text を含む最初の行 (1始まり。start 行より後ろ)。"""
    return next(i + 1 for i in range(start, len(SRC)) if text in SRC[i])


# U_loop の区分の行 (README の表。行の文の目印から決める)
L_STEP = line_of("int unmoveStep(")
L_PREF = line_of("__builtin_prefetch(&g_dtm[r[j]], 1, 3);", L_STEP)
L_SIEVE = (line_of("if (g_dtm[r[j]] != DTM_UNDECIDED) continue;", L_PREF) - 1, line_of("n_kept += (uint64_t)m;", L_PREF))
L_DECIDE = (line_of("for (int j = 0; j < m; j++) {", L_SIEVE[1]), line_of("found[nf++] = cand[j];", L_SIEVE[1]))
# F1 の先行判定の区画 (perf_38 と同じ目印)
L_PRE = (line_of("キャッチの先行判定."), line_of("if (hit) return 0;"))
GENERATOR = ("unmoveCandidates", "invBoard", "normalBoard", "unmoveMirror")


def bucket_u(where: str, chain: str, line: str) -> str:
    """U_loop の標本の区分 (README の「U_loop の区分」)。"""
    if where == "[kernel]":
        return "カーネル"
    if where.startswith(("python", "libpython")):
        return "Python"
    if where.startswith("libc"):
        return "libc"
    if where != "animal_shogi.so":
        return f"そのほか（{where}）"
    fs = chain.split(">")
    ln = int(line)
    if fs[0] in GENERATOR:
        return "逆向きの生成器"
    if fs[0] != "unmoveStep":
        return f".so のほかの関数（{fs[0]}）"
    if "rankOf" in fs:
        return "rankOf"
    if ln == L_PREF:
        return "g_dtm の先読み"
    if L_SIEVE[0] <= ln <= L_SIEVE[1]:
        return "未定の候補をふるう"
    if L_DECIDE[0] <= ln <= L_DECIDE[1]:
        return "決める"
    return "unmoveStep のそのほか"


def bucket_f(where: str, chain: str, line: str) -> str:
    """F1 の標本の区分 (perf_38 の bucket() を鎖で決めるようにしたもの)。"""
    if where == "[kernel]":
        return "カーネル"
    if where.startswith(("python", "libpython")):
        return "Python"
    if where.startswith("libc"):
        return "libc"
    if where != "animal_shogi.so":
        return f"そのほか（{where}）"
    fs = chain.split(">")
    inner = fs[-1]
    ln = int(line)
    text = SRC[ln - 1] if 0 < ln <= len(SRC) else ""
    if fs[0] == "nextBoardInvNormalNC" or fs[0] == "invBoard":
        if inner == "invBoard":
            return "生成器: invBoard"
        if inner == "komaSet" or (inner == "nextBoardInvNormalNC" and L_PRE[0] <= ln <= L_PRE[1]):
            return "生成器: 先行判定"
        return "生成器: 本体"
    if "rankOf" in fs:
        return "rankOf（番号の計算）"
    if inner == "seenTestAndSet":
        return "seenTestAndSet（発見済みの表）"
    if inner == "nextBoardSeenNormal":
        if "g_prep[rb] =" in text:
            return "nextBoardSeenNormal: g_prep[rb] の書き込み"
        if "__builtin_prefetch(&g_prep" in text:
            return "nextBoardSeenNormal: g_prep の先読み"
        if "__builtin_prefetch(&g_seen" in text:
            return "nextBoardSeenNormal: g_seen の先読み"
        return "nextBoardSeenNormal: ほか"
    if inner == "zeroPush":
        return "nextBoardSeenNormal: zeroPush"
    if fs[0].startswith("expand"):
        return "expandRound"
    return f".so のほかの関数（{fs[0]}）"


def gen_inner(chain: str) -> str:
    """逆向きの生成器の中の内訳 (一番内側の関数)。"""
    return chain.split(">")[-1]


def tsv(path: pathlib.Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def denominators(label: str) -> dict[str, int]:
    with (LOGS / f"{label}_forward.tsv").open(encoding="utf-8") as f:
        n_in = sum(int(r["n_in"]) for r in csv.DictReader(f, delimiter="\t"))
    text = (LOGS / f"{label}_main.log").read_text(encoding="utf-8")
    front = re.search(r"展開した局面 \(perf_34\)：(\d+)", text)
    cand = re.search(r"前任の候補：(\d+) \(手数が未定で残ったもの (\d+)\)", text)
    assert front and cand, f"{label}_main.log に分母の行が無い"
    return {"F1": n_in, "front": int(front.group(1)), "cand": int(cand.group(1)), "kept": int(cand.group(2))}


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


def derived(per: dict[str, dict[str, float]]) -> dict[str, float]:
    """組 → (イベント → 値) から, README の式の量を出す (perf_38/summary.py の derived() の写し)。"""

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


def bench_unmove() -> dict[str, float]:
    """rank_fast の段2の benchUnmove の lean の order の1局面あたり (中央値)。"""
    text = (ROOT / "experiments" / "rank_fast" / "logs" / "summary_stage2.txt").read_text(encoding="utf-8")
    m = re.search(r"^\| lean \| unmove \| ([\d.]+)（[^|]*\| ([\d.]+)（[^|]*\| ([\d.]+)（[^|]*\| ([\d.]+)（", text, re.M)
    assert m, "rank_fast の summary_stage2.txt に lean の unmove の行が無い"
    return dict(zip(("cycles", "instructions", "分岐", "分岐の予測ミス"), map(float, m.groups()), strict=True))


def perf34_u_loop() -> dict[str, float]:
    """perf_34 の U_loop の値 (中央値): topdown の割合と, 局面1個あたり。"""
    text = (ROOT / "experiments" / "perf_34" / "logs" / "summary.txt").read_text(encoding="utf-8")
    sec = text[text.index("## U_loop") :]
    out: dict[str, float] = {}
    for key, name in (
        ("retiring", "retiring"), ("bad_spec", "bad_spec"), ("frontend", "frontend"), ("backend", "backend"),
        ("memory_bound", "memory_bound"), ("core_bound", "core_bound"),
        ("stalls_mem_any/cyc", "stalls_mem_any/cyc"), ("stalls_l2_miss/cyc", "stalls_l2_miss/cyc"),
    ):  # fmt: skip
        m = re.search(rf"^- {re.escape(key)}: ([\d.]+)%", sec, re.M)
        if m:
            out[name] = float(m.group(1)) / 100
    for key, name in (
        ("cycles", "cycles"), ("instructions", "instructions"), ("branches", "分岐"),
        ("branch-misses", "分岐の予測ミス"), ("L1 ロードミス", "L1 ロードミス"), ("L2 ロードミス", "L2 ロードミス"),
        ("LLC ロードミス", "LLC ロードミス"), ("stalls_mem_any", "`stalls_mem_any` のサイクル"),
        ("stalls_l2_miss", "`stalls_l2_miss` のサイクル"),
    ):  # fmt: skip
        m = re.search(rf"^- {re.escape(key)}: ([\d.]+)（", sec, re.M)
        if m:
            out[name] = float(m.group(1))
    return out


def perf38_f1() -> dict[str, float]:
    """perf_38 の r38 の F1 の局面1つあたり (中央値)。"""
    text = (ROOT / "experiments" / "perf_38" / "logs" / "summary.txt").read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for name, _, _ in PER_POS:
        m = re.search(rf"^\| {re.escape(name)} \| [^|]+ \| ([\d.]+)（", text, re.M)
        if m:
            out[name] = float(m.group(1))
    return out


def gate_new() -> dict[str, float]:
    """門番 #39 の new の F1 と U_loop の秒 (perf なし。平均)。"""
    text = (ROOT / "experiments" / "gate_39_rank_lean" / "logs" / "summary.txt").read_text(encoding="utf-8")
    out = {}
    for k in STAGES:
        m = re.search(rf"^\| {k} \| [^|]+ \| ([\d.]+)（", text, re.M)
        assert m, f"門番 #39 の summary.txt に {k} の行が無い"
        out[k] = float(m.group(1))
    return out


def record(label: str, stage: str) -> list[tuple[str, str, str, str, str, int]]:
    """(event, where, chain, line, table, samples) の行。"""
    out = []
    with (LOGS / f"{label}_record_{stage}.tsv").open(encoding="utf-8") as f:
        rows = csv.DictReader((ln for ln in f if not ln.startswith("#")), delimiter="\t")
        for r in rows:
            out.append((r["event"], r["where"], r["chain"], r["line"], r["table"], int(r["samples"])))
    return out


def lstsq(xs: list[list[float]], ys: list[float]) -> tuple[list[float], float]:
    """最小二乗 (正規方程式をガウスの消去法で解く)。(係数, 決定係数)。"""
    k = len(xs[0])
    a = [[sum(x[i] * x[j] for x in xs) for j in range(k)] + [sum(x[i] * y for x, y in zip(xs, ys, strict=True))]
         for i in range(k)]  # fmt: skip
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(a[r][i]))
        a[i], a[p] = a[p], a[i]
        for r in range(k):
            if r != i:
                f = a[r][i] / a[i][i]
                a[r] = [u - f * v for u, v in zip(a[r], a[i], strict=True)]
    beta = [a[i][k] / a[i][i] for i in range(k)]
    pred = [sum(b * v for b, v in zip(beta, x, strict=True)) for x in xs]
    my = statistics.mean(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, pred, strict=True))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return beta, 1 - ss_res / ss_tot


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    started: dict[str, tuple[str, str]] = {}
    finished: set[str] = set()
    for line in (LOGS / "console.log").read_text(encoding="utf-8").splitlines():
        if m := START.match(line):
            started[m.group("label")] = (m.group("rep"), m.group("kind"))
        elif m := DONE.match(line):
            finished.add(m.group("label"))
    labels = [lb for lb in started if lb in finished]
    print("## 本数と検査")
    print()
    print(f"- 開始 {len(started)} 本 / 完了 {len(finished)} 本 / 種類 {sorted({k for _, k in started.values()})}")
    dens = {lb: denominators(lb) for lb in labels}
    for key in ("F1", "front", "cand", "kept"):
        print(f"- 分母 {key}: {sorted({d[key] for d in dens.values()})}（全本で同じなら1つ）")
    answers = [lb for lb in labels if (LOGS / f"{lb}_answer.txt").read_text().strip().endswith("PASS")]
    print(f"- 答えの検査（md5 一覧が #39 本走と同じ）が PASS の本: {len(answers)} / {len(labels)}")
    den = {k: statistics.median(d[k] for d in dens.values()) for k in ("F1", "front", "cand", "kept")}
    print()

    stats: dict[tuple[str, str, str], dict[str, float]] = {}
    pcts = []
    for lb in labels:
        rep, kind = started[lb]
        if kind in SETS:
            for st in STAGES:
                s, p = stat(lb, st)
                stats[(rep, st, kind)] = s
                pcts.append(p)
    print(f"- 多重化: perf stat の {len(pcts)} 個（本 × 区間）で, 数えた比率の最小 {min(pcts):.2f}%")
    print()

    g = gate_new()
    print("## 段の秒（perf を付けた分の重さ。門番 #39 の new は perf なし）")
    print()
    secs: dict[tuple[str, str], float] = {}
    for st, src in (("F1", "forward_summary"), ("U_loop", "retreat_summary")):
        stat_s = [tsv(LOGS / f"{lb}_{src}.tsv")[st] for lb in labels if started[lb][1] in SETS]
        rec_s = [tsv(LOGS / f"{lb}_{src}.tsv")[st] for lb in labels if started[lb][1] in ("cyc", "l2m")]
        for lb in labels:
            secs[(lb, st)] = tsv(LOGS / f"{lb}_{src}.tsv")[st]
        print(f"- {st}: perf stat の本 {mid(stat_s, '.2f')} 秒、perf record の本 {mid(rec_s, '.2f')} 秒 / 門番 #39 の new {g[st]:.2f} 秒"
              f"（stat の中央値で {statistics.median(stat_s) / g[st] - 1:+.1%}、record で {statistics.median(rec_s) / g[st] - 1:+.1%}）")  # fmt: skip
    print()

    per_rep: dict[tuple[str, str], dict[str, float]] = {}
    pos: dict[tuple[str, str], dict[str, float]] = {}
    for rep in REPS:
        for st in STAGES:
            if not all((rep, st, s) in stats for s in SETS):
                continue
            per = {s: stats[(rep, st, s)] for s in SETS}
            per_rep[(rep, st)] = derived(per)
            n = den["F1"] if st == "F1" else den["front"]
            pos[(rep, st)] = {name: per[s][e] / n for name, s, e in PER_POS}
    reps = sorted({r for r, _ in per_rep})
    p34 = perf34_u_loop()
    p38 = perf38_f1()
    print(f"## topdown（{len(reps)} 回の中央値と範囲。式は README。参考に perf_34 の U_loop（#34）を並べる）")
    print()
    print("| | F1 | U_loop | perf_34 の U_loop（#34） |")
    print("|---|---|---|---|")
    for title, key in FRACTIONS:
        a = [per_rep[(r, "F1")][key] for r in reps]
        b = [per_rep[(r, "U_loop")][key] for r in reps]
        ref = f"{p34[key]:.1%}" if key in p34 else "-"
        print(f"| {title} | {mid(a, '.1%')} | {mid(b, '.1%')} | {ref} |")
    a = [per_rep[(r, "F1")]["ipc"] for r in reps]
    b = [per_rep[(r, "U_loop")]["ipc"] for r in reps]
    print(f"| IPC | {mid(a, '.3f')} | {mid(b, '.3f')} | - |")
    print()
    print("### topdown の区分をサイクルに直したもの（区分の割合 × 1局面あたり cycles。U_loop はフロンティア1局面あたり）")
    print()
    print("| | F1 | U_loop | perf_34 の U_loop（#34） |")
    print("|---|---|---|---|")
    for title, key in FRACTIONS[:6]:
        a = [per_rep[(r, "F1")][key] * pos[(r, "F1")]["cycles"] for r in reps]
        b = [per_rep[(r, "U_loop")][key] * pos[(r, "U_loop")]["cycles"] for r in reps]
        ref = f"{p34[key] * p34['cycles']:.1f}" if key in p34 else "-"
        print(f"| {title} | {mid(a, '.1f')} | {mid(b, '.1f')} | {ref} |")
    print()
    print("### 1局面あたり（F1 は展開した局面、U_loop はフロンティア1局面と候補1つ。参考に perf_38 の r38（#38 の F1）と perf_34 の U_loop（#34））")
    print()
    print("| | F1 | perf_38 r38 | U_loop / フロンティア | U_loop / 候補 | perf_34 U_loop / フロンティア |")
    print("|---|---|---|---|---|---|")
    ratio = den["front"] / den["cand"]
    for name, _, _ in PER_POS:
        a = [pos[(r, "F1")][name] for r in reps]
        b = [pos[(r, "U_loop")][name] for r in reps]
        fmt = ".1f" if max(a + b) > 20 else ".3f"
        r38 = f"{p38[name]:{fmt}}" if name in p38 else "-"
        r34 = f"{p34[name]:{fmt}}" if name in p34 else "-"
        print(f"| {name} | {mid(a, fmt)} | {r38} | {mid(b, fmt)} | {mid([x * ratio for x in b], '.3f')} | {r34} |")
    print()

    bu = bench_unmove()
    print("## 生成器だけのベンチとの照らし合わせ（rank_fast の benchUnmove の lean。order の1局面あたり）")
    print()
    print("| | ベンチ | 本物の U_loop | 本物 − ベンチ | perf_34（#34）の本物 − ベンチ |")
    print("|---|---|---|---|---|")
    for k in ("cycles", "instructions", "分岐", "分岐の予測ミス"):
        real = [pos[(r, "U_loop")][k] for r in reps]
        print(f"| {k} | {bu[k]:.1f} | {mid(real, '.1f')} | {mid([x - bu[k] for x in real], '+.1f')} | "
              + ("428 cycles" if k == "cycles" else "232 命令" if k == "instructions" else "-") + " |")  # fmt: skip
    print()

    rec: dict[tuple[str, str, str], list[tuple[str, str, str, str, str, int]]] = {}
    for lb in labels:
        rep, kind = started[lb]
        if kind in ("cyc", "l2m"):
            for st in STAGES:
                rec[(rep, kind, st)] = record(lb, st)
    rreps = sorted({r for r, k, _ in rec if k == "cyc"})

    def shares(rep: str, kind: str, st: str, fn) -> tuple[dict[str, float], int]:  # noqa: ANN001
        rows = rec[(rep, kind, st)]
        tot = sum(n for *_, n in rows)
        out: dict[str, float] = defaultdict(float)
        for _ev, where, chain, line, table, n in rows:
            out[fn(where, chain, line, table)] += n / tot
        return out, tot

    def t1_label(rep: str) -> str:
        return f"r{rep}_T1"

    print("## どこで時間を使っているか: U_loop（cycles:pp。割合 × その回の T1 の cycles。秒は割合 × その回の T1 の本の U_loop の秒）")
    print()
    sh = {r: shares(r, "cyc", "U_loop", lambda w, c, ln, t: bucket_u(w, c, ln)) for r in rreps}
    print(f"標本の数: {[sh[r][1] for r in rreps]}")
    print()
    print("| 区分 | 割合 | cycles / フロンティア | cycles / 候補 | 秒 |")
    print("|---|---|---|---|---|")
    names = {b for r in rreps for b in sh[r][0]}
    rows_u = []
    for b in names:
        s = [sh[r][0].get(b, 0.0) for r in rreps]
        cyc = [x * pos[(r, "U_loop")]["cycles"] for x, r in zip(s, rreps, strict=True)]
        sec = [x * secs[(t1_label(r), "U_loop")] for x, r in zip(s, rreps, strict=True)]
        rows_u.append((statistics.median(s), b, s, cyc, sec))
    for _, b, s, cyc, sec in sorted(rows_u, reverse=True):
        print(f"| {b} | {mid(s, '.1%')} | {mid(cyc, '.1f')} | {mid([c * ratio for c in cyc], '.1f')} | {mid(sec, '.2f')} |")
    print()
    print("### 逆向きの生成器の中（一番内側の関数ごと。U_loop 全体に対する割合と cycles / フロンティア）")
    print()
    gi = {
        r: shares(r, "cyc", "U_loop", lambda w, c, ln, t: gen_inner(c) if bucket_u(w, c, ln) == "逆向きの生成器" else "-")
        for r in rreps
    }  # fmt: skip
    rows_g = []
    for b in {b for r in rreps for b in gi[r][0]} - {"-"}:
        s = [gi[r][0].get(b, 0.0) for r in rreps]
        rows_g.append((statistics.median(s), b, s, [x * pos[(r, "U_loop")]["cycles"] for x, r in zip(s, rreps, strict=True)]))
    for _, b, s, cyc in sorted(rows_g, reverse=True):
        print(f"- {b}: {mid(s, '.1%')}、{mid(cyc, '.1f')} cycles / フロンティア")
    print()
    print("### unmoveStep の行ごと（U_loop 全体に対する割合。0.5% 以上）")
    print()
    ls = {
        r: shares(r, "cyc", "U_loop", lambda w, c, ln, t: f"{ln}" if w == "animal_shogi.so" and c.split(">")[0] == "unmoveStep"
                  and "rankOf" not in c.split(">") else "-")
        for r in rreps
    }  # fmt: skip
    for b in sorted({b for r in rreps for b in ls[r][0]} - {"-"}, key=int):
        s = [ls[r][0].get(b, 0.0) for r in rreps]
        if statistics.median(s) >= 0.005:
            print(f"- {b} 行 `{SRC[int(b) - 1].strip()}`: {mid(s, '.1%')}")
    print()

    # 到達しない候補を減らす上限
    per_cand = {b: [c * ratio for c in cyc] for _, b, _s, cyc, _sec in rows_u}
    sec_per_cand = {b: [x / den["cand"] for x in sec] for _, b, _s, _cyc, sec in rows_u}
    keys = ("逆向きの生成器", "rankOf", "g_dtm の先読み", "未定の候補をふるう")
    up_c = [sum(per_cand.get(k, [0.0] * len(rreps))[i] for k in keys) for i in range(len(rreps))]
    up_s = [sum(sec_per_cand.get(k, [0.0] * len(rreps))[i] for k in keys) * N_UNREACHABLE for i in range(len(rreps))]
    print("### 到達しない候補を減らすレバーの上限（README の式）")
    print()
    print(f"- （逆向きの生成器 ＋ rankOf ＋ g_dtm の先読み ＋ ふるう）の候補1つあたり: {mid(up_c, '.1f')} cycles")
    print(f"- × 到達しない候補 {N_UNREACHABLE:,} ＝ {mid(up_s, '.2f')} 秒")
    print()

    print("## どこで時間を使っているか: F1（cycles:pp。割合 × その回の T1 の cycles）")
    print()
    shf = {r: shares(r, "cyc", "F1", lambda w, c, ln, t: bucket_f(w, c, ln)) for r in rreps}
    print(f"標本の数: {[shf[r][1] for r in rreps]}")
    print()
    print("| 区分 | 割合 | cycles / 局面 | 秒 |")
    print("|---|---|---|---|")
    rows_f = []
    for b in {b for r in rreps for b in shf[r][0]}:
        s = [shf[r][0].get(b, 0.0) for r in rreps]
        rows_f.append((statistics.median(s), b, s, [x * pos[(r, "F1")]["cycles"] for x, r in zip(s, rreps, strict=True)],
                       [x * secs[(t1_label(r), "F1")] for x, r in zip(s, rreps, strict=True)]))  # fmt: skip
    for _, b, s, cyc, sec in sorted(rows_f, reverse=True):
        print(f"| {b} | {mid(s, '.1%')} | {mid(cyc, '.1f')} | {mid(sec, '.2f')} |")
    print()

    lreps = sorted({r for r, k, _ in rec if k == "l2m"})
    for st, unit, fn in (
        ("U_loop", "フロンティア", lambda w, c, ln, t: bucket_u(w, c, ln)),
        ("F1", "局面", lambda w, c, ln, t: bucket_f(w, c, ln)),
    ):
        print(f"## L2 のロードミスの寄り先: {st}（mem_load_uops_retired.l2_miss:pp。割合 × その回の C1 の l2_miss / {unit}）")
        print()
        for title, f2 in (("読んだ配列", lambda w, c, ln, t: t if w == "animal_shogi.so" else f"（{w}）"), ("区分", fn)):
            sl = {r: shares(r, "l2m", st, f2) for r in lreps}
            print(f"### {title}（標本の数 {[sl[r][1] for r in lreps]}）")
            print()
            rows_l = []
            for b in {b for r in lreps for b in sl[r][0]}:
                s = [sl[r][0].get(b, 0.0) for r in lreps]
                rows_l.append((statistics.median(s), b, s, [x * pos[(r, st)]["L2 ロードミス"] for x, r in zip(s, lreps, strict=True)]))
            for m_, b, s, per in sorted(rows_l, reverse=True):
                if m_ >= 0.005:
                    print(f"- {b}: {mid(s, '.1%')}、{mid(per, '.4f')} / {unit}")
            print()

    print("## 手数ごとの表（u_loop_depth.tsv。T1 の3本の中央値。step は unmoveStep の呼び出し、py はその段のほか）")
    print()
    depth: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in reps:
        with (LOGS / f"{t1_label(r)}_u_loop_depth.tsv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                for k, v in row.items():
                    depth[int(row["nd"])][k].append(float(v))
    med = {nd: {k: statistics.median(v) for k, v in d.items()} for nd, d in depth.items()}
    tot = {k: sum(m[k] for m in med.values()) for k in next(iter(med.values()))}
    print(f"- 段の数 {len(med)}。フロンティア {tot['front']:,.0f}・候補 {tot['cand']:,.0f}・残した候補 {tot['kept']:,.0f}・決まった数 {tot['found']:,.0f}")
    print(f"- step: 壁時計 {tot['t_step']:.2f} 秒（ユーザー {tot['ut_step']:.2f}・カーネル {tot['st_step']:.2f}・minor fault {tot['min_step']:,.0f}）")
    print(f"- py: 壁時計 {tot['t_py']:.2f} 秒（ユーザー {tot['ut_py']:.2f}・カーネル {tot['st_py']:.2f}・minor fault {tot['min_py']:,.0f}）")
    nds = sorted(med)
    beta, r2 = lstsq([[med[n]["cand"], med[n]["front"], 1.0] for n in nds], [med[n]["t_step"] for n in nds])
    print(f"- step の秒 ≈ {beta[0] * 1e9:.1f} ns × 候補 ＋ {beta[1] * 1e9:.1f} ns × フロンティア ＋ {beta[2] * 1e3:.3f} ms（決定係数 {r2:.4f}）")
    beta2, r22 = lstsq([[med[n]["found"], 1.0] for n in nds], [med[n]["t_py"] for n in nds])
    print(f"- py の秒 ≈ {beta2[0] * 1e9:.1f} ns × 決まった数 ＋ {beta2[1] * 1e3:.3f} ms（決定係数 {r22:.4f}）")
    print()
    print("| 手数 | フロンティア | 候補 | 残した | 決まった | step 秒 | py 秒 | step の ns / 候補 |")
    print("|---|---|---|---|---|---|---|---|")
    for n in nds:
        m = med[n]
        per = m["t_step"] / m["cand"] * 1e9 if m["cand"] else 0.0
        print(f"| {n} | {m['front']:,.0f} | {m['cand']:,.0f} | {m['kept']:,.0f} | {m['found']:,.0f} | {m['t_step']:.3f} | {m['t_py']:.3f} | {per:.1f} |")
    print()

    for lb in labels:
        if started[lb][1] in ("cyc", "l2m"):
            for st in STAGES:
                p = LOGS / f"{lb}_record_stats_{st}.txt"
                print(f"- 間引き {lb} {st}: " + " / ".join(ln.strip() for ln in p.read_text().splitlines()[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
